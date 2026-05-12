"""Network system and command tools (1 read + 7 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiBadRequestError, UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import (
    JsonObject,
    build_named_arg_body,
    get_server_context,
    redact_secrets,
    reject_dangerous_keys,
    validate_mac,
)

# ── Option-1 allowlist for unifi_network_update_settings (#202) ────────────
#
# A flat scalar -> nested-dict path. Each entry tells the named-arg builder
# where to place the value in the outgoing ``rest/setting`` PUT body. The
# named-arg surface IS the allowlist — anything not listed here cannot be
# set via the named API.
#
# Conservatively scoped to fields that:
#   - are name-only / identity-style settings (no auth, no callbacks),
#   - do not collide with the dangerous-key denylist (``super_*``,
#     ``radius_*``, ``*_url``, ``*_command``, ``mac_filter_*``, admin
#     role flags, command verbs all stay out),
#   - have an obvious, stable destination on the Network controller.
#
# Easier to expand later than to retract. Adding a new safe field is one
# line here plus one kwarg on the tool signature.
_SETTINGS_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "mgmt_timezone": ("mgmt", "timezone"),
    "locale_country": ("locale", "country"),
    "ntp_server_1": ("ntp", "ntp_server_1"),
    "ntp_server_2": ("ntp", "ntp_server_2"),
}

# UniFi switches expose ports indexed 1..N starting at 1. The largest stock SKU
# is the Pro 48 PoE; capping at 52 keeps headroom for a few hypothetical SFP
# expansion slots while rejecting agent-supplied ``0``, negative, or absurd
# values that would otherwise reach the controller untouched. See #151.
_PORT_IDX_MIN = 1
_PORT_IDX_MAX = 52


def _validate_port_idx(port_idx: int) -> None:
    """Raise ``UniFiBadRequestError`` if ``port_idx`` is outside the supported range."""
    if not isinstance(port_idx, int) or not (_PORT_IDX_MIN <= port_idx <= _PORT_IDX_MAX):
        raise UniFiBadRequestError(f"port_idx must be between {_PORT_IDX_MIN} and {_PORT_IDX_MAX} (got {port_idx!r})")


def register_system_tools(mcp: FastMCP) -> None:
    """Register system and command tools."""

    @mcp.tool(tags={"network"})
    async def unifi_network_get_settings(ctx: Context) -> dict[str, Any]:
        """Get controller settings.

        SMTP credentials, RADIUS shared secrets, ``super_*_password`` /
        ``super_*_url`` callback fields, and other credential keys are
        redacted before the response leaves this tool — see
        ``unifi_mcp._redaction`` (#146).

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response with sensitive fields redacted.
        """
        try:
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["network"].get_settings())
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_update_settings(
        ctx: Context,
        *,
        mgmt_timezone: str | None = None,
        locale_country: str | None = None,
        ntp_server_1: str | None = None,
        ntp_server_2: str | None = None,
        data: JsonObject | None = None,
    ) -> dict[str, Any]:
        """Update controller settings using named scalar args.

        Pass only the fields to change. Sections that handle authentication,
        callbacks, or admin escalation (``super_*``, ``radius_*``,
        ``mac_filter_*``, ``auto_upgrade``, ``*_url``, ``*_command``,
        admin role flags) are intentionally NOT exposed here — they have
        dedicated tools or stay behind the dangerous-key denylist.

        Args:
            ctx: FastMCP request context.
            mgmt_timezone: IANA timezone string (``mgmt.timezone``), e.g.
                ``"America/Los_Angeles"``.
            locale_country: ISO country code for the controller locale
                (``locale.country``), e.g. ``"US"``.
            ntp_server_1: Primary NTP server hostname or IP
                (``ntp.ntp_server_1``).
            ntp_server_2: Secondary NTP server hostname or IP
                (``ntp.ntp_server_2``).
            data: DEPRECATED — raw settings dict. Kept for back-compat
                with existing agents; prefer the named scalar args above.
                Still passes through the dangerous-key denylist. Cannot
                be combined with any named arg.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot update settings in read-only mode")
            body = build_named_arg_body(
                tool_name="unifi_network_update_settings",
                field_paths=_SETTINGS_FIELD_PATHS,
                named_values={
                    "mgmt_timezone": mgmt_timezone,
                    "locale_country": locale_country,
                    "ntp_server_1": ntp_server_1,
                    "ntp_server_2": ntp_server_2,
                },
                data=data,
            )
            reject_dangerous_keys(body, tool_name="unifi_network_update_settings")
            return await context.clients["network"].update_settings(body)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_run_speedtest(ctx: Context) -> dict[str, Any]:
        """Run a speed test on the controller's WAN connection.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot run speed test in read-only mode")
            return await context.clients["network"].run_speedtest()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_create_backup(ctx: Context) -> dict[str, Any]:
        """Create a backup of the controller configuration.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot create backup in read-only mode")
            return await context.clients["network"].create_backup()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_upgrade_device(ctx: Context, mac: str) -> dict[str, Any]:
        """Upgrade a device to the latest firmware.

        Args:
            mac: MAC address of the device to upgrade.

        Returns:
            The upstream API response.
        """
        try:
            validate_mac(mac, field="mac")
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot upgrade device in read-only mode")
            return await context.clients["network"].upgrade_device(mac)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_power_cycle_port(ctx: Context, mac: str, port_idx: int) -> dict[str, Any]:
        """Power cycle a PoE port on a switch.

        Args:
            mac: MAC address of the switch.
            port_idx: Port index to power cycle. Bounded to ``1..52``; values
                outside this range raise ``UniFiBadRequestError``.

        Returns:
            The upstream API response.
        """
        try:
            validate_mac(mac, field="mac")
            _validate_port_idx(port_idx)
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot power cycle port in read-only mode")
            return await context.clients["network"].power_cycle_port(mac, port_idx)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_unauthorize_guest(ctx: Context, mac: str) -> dict[str, Any]:
        """Revoke guest authorization for a client.

        Args:
            mac: MAC address of the guest client.

        Returns:
            The upstream API response.
        """
        try:
            validate_mac(mac, field="mac")
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot unauthorize guest in read-only mode")
            return await context.clients["network"].unauthorize_guest(mac)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_archive_events(ctx: Context) -> dict[str, Any]:
        """Archive all alarms and events.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot archive events in read-only mode")
            return await context.clients["network"].archive_events()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_reset_dpi(ctx: Context) -> dict[str, Any]:
        """Reset all DPI (Deep Packet Inspection) counters.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot reset DPI in read-only mode")
            return await context.clients["network"].reset_dpi()
        except Exception as e:
            handle_client_error(e)

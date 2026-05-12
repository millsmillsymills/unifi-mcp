"""Switch port-profile management tools (2 read + 4 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiBadRequestError, UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import (
    JsonObject,
    get_server_context,
    redact_secrets,
    reject_dangerous_keys,
    validate_id,
    validate_mac,
)

# Mirrors the bound in ``tools/network/system.py`` — kept local rather than
# imported so the two tool modules stay independently auditable. See #151.
_PORT_IDX_MIN = 1
_PORT_IDX_MAX = 52


def register_port_profile_tools(mcp: FastMCP) -> None:
    """Register port-profile tools (see #93)."""

    # ── Read tools ──────────────────────────────────────────────────────

    @mcp.tool(tags={"network"})
    async def unifi_network_list_port_profiles(ctx: Context) -> dict[str, Any]:
        """List all switch port profiles (VLAN, PoE, storm-control configs).

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response with sensitive fields redacted.
        """
        try:
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["network"].list_port_profiles())
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_get_port_profile(ctx: Context, profile_id: str) -> dict[str, Any]:
        """Get a specific switch port profile by id.

        Args:
            profile_id: The port-profile ID (``_id`` from ``list_port_profiles``).

        Returns:
            The upstream API response with sensitive fields redacted.
        """
        try:
            validate_id(profile_id, field="profile_id")
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["network"].get_port_profile(profile_id))
        except Exception as e:
            handle_client_error(e)

    # ── Write tools ─────────────────────────────────────────────────────

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_create_port_profile(ctx: Context, data: JsonObject) -> dict[str, Any]:
        """Create a switch port profile.

        The controller requires at least ``name``, ``poe_mode`` (e.g. ``auto``),
        and ``forward`` (e.g. ``all`` / ``native`` / ``customize``). Pass a
        full payload via ``data`` — it's forwarded verbatim.

        Args:
            data: Full port-profile payload.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot create port profile in read-only mode")
            reject_dangerous_keys(data, tool_name="unifi_network_create_port_profile")
            return await context.clients["network"].create_port_profile(data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_update_port_profile(ctx: Context, profile_id: str, data: JsonObject) -> dict[str, Any]:
        """Update a switch port profile. Pass only fields to change.

        Args:
            profile_id: The port-profile ID to update.
            data: Fields to update (e.g. ``{"poe_mode": "off"}``).

        Returns:
            The upstream API response.
        """
        try:
            validate_id(profile_id, field="profile_id")
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot update port profile in read-only mode")
            reject_dangerous_keys(data, tool_name="unifi_network_update_port_profile")
            return await context.clients["network"].update_port_profile(profile_id, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_delete_port_profile(ctx: Context, profile_id: str) -> dict[str, Any]:
        """Delete a switch port profile.

        Every switch port currently bound to this profile falls back to the
        default profile, which may reset VLAN tagging and PoE mode — treat
        this as destructive on any production site.

        Args:
            profile_id: The port-profile ID to delete.

        Returns:
            The upstream API response.
        """
        try:
            validate_id(profile_id, field="profile_id")
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot delete port profile in read-only mode")
            return await context.clients["network"].delete_port_profile(profile_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_assign_port_profile(
        ctx: Context, mac: str, port_idx: int, profile_id: str
    ) -> dict[str, Any]:
        """Assign a port profile to a specific switch port.

        Args:
            mac: MAC address of the switch.
            port_idx: 1-based port number on the switch. Bounded to ``1..52``;
                values outside this range raise ``UniFiBadRequestError``.
            profile_id: The port-profile ID to apply.

        Returns:
            The upstream API response.

        Note:
            Splices a ``port_overrides`` entry onto the device so the named
            port adopts the profile's VLAN / PoE / storm-control config.
            Destructive — can drop clients on that port if the new profile
            changes their link config.
        """
        try:
            validate_mac(mac, field="mac")
            validate_id(profile_id, field="profile_id")
            if not isinstance(port_idx, int) or not (_PORT_IDX_MIN <= port_idx <= _PORT_IDX_MAX):
                raise UniFiBadRequestError(
                    f"port_idx must be between {_PORT_IDX_MIN} and {_PORT_IDX_MAX} (got {port_idx!r})"
                )
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot assign port profile in read-only mode")
            return await context.clients["network"].assign_port_profile(mac, port_idx, profile_id)
        except Exception as e:
            handle_client_error(e)

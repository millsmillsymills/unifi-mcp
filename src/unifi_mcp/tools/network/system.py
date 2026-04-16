"""Network system and command tools (1 read + 7 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_system_tools(mcp: FastMCP) -> None:
    """Register system and command tools."""

    @mcp.tool(tags={"network"})
    async def network_get_settings(ctx: Context) -> dict[str, Any]:
        """Get controller settings."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["network"].get_settings()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_update_settings(ctx: Context, data: dict[str, Any]) -> dict[str, Any]:
        """Update controller settings. Pass only fields to change.

        Args:
            data: Settings fields to update.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update settings in read-only mode")
            return await context.clients["network"].update_settings(data)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_run_speedtest(ctx: Context) -> dict[str, Any]:
        """Run a speed test on the controller's WAN connection."""
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot run speed test in read-only mode")
            return await context.clients["network"].run_speedtest()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_create_backup(ctx: Context) -> dict[str, Any]:
        """Create a backup of the controller configuration."""
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot create backup in read-only mode")
            return await context.clients["network"].create_backup()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_upgrade_device(ctx: Context, mac: str) -> dict[str, Any]:
        """Upgrade a device to the latest firmware.

        Args:
            mac: MAC address of the device to upgrade.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot upgrade device in read-only mode")
            return await context.clients["network"].upgrade_device(mac)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_power_cycle_port(ctx: Context, mac: str, port_idx: int) -> dict[str, Any]:
        """Power cycle a PoE port on a switch.

        Args:
            mac: MAC address of the switch.
            port_idx: Port index to power cycle.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot power cycle port in read-only mode")
            return await context.clients["network"].power_cycle_port(mac, port_idx)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_unauthorize_guest(ctx: Context, mac: str) -> dict[str, Any]:
        """Revoke guest authorization for a client.

        Args:
            mac: MAC address of the guest client.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot unauthorize guest in read-only mode")
            return await context.clients["network"].unauthorize_guest(mac)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_archive_events(ctx: Context) -> dict[str, Any]:
        """Archive all alarms and events."""
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot archive events in read-only mode")
            return await context.clients["network"].archive_events()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_reset_dpi(ctx: Context) -> dict[str, Any]:
        """Reset all DPI (Deep Packet Inspection) counters."""
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot reset DPI in read-only mode")
            return await context.clients["network"].reset_dpi()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

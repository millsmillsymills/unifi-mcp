"""Network system and command tools (1 read + 7 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import JsonObject, get_server_context, reject_dangerous_keys


def register_system_tools(mcp: FastMCP) -> None:
    """Register system and command tools."""

    @mcp.tool(tags={"network"})
    async def unifi_network_get_settings(ctx: Context) -> dict[str, Any]:
        """Get controller settings.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].get_settings()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_update_settings(ctx: Context, data: JsonObject) -> dict[str, Any]:
        """Update controller settings. Pass only fields to change.

        Args:
            data: Settings fields to update.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot update settings in read-only mode")
            reject_dangerous_keys(data, tool_name="unifi_network_update_settings")
            return await context.clients["network"].update_settings(data)
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
            port_idx: Port index to power cycle.

        Returns:
            The upstream API response.
        """
        try:
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

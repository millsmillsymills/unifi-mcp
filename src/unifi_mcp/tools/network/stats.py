"""Network statistics and monitoring tools (9 read-only tools)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error
from unifi_mcp.tools._common import get_server_context


def register_stats_tools(mcp: FastMCP) -> None:
    """Register network stats tools."""

    @mcp.tool(tags={"network"})
    async def unifi_network_get_health(ctx: Context) -> dict[str, Any]:
        """Get health status for all network subsystems (www, wlan, lan, wan).

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].get_health()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_list_events(ctx: Context, limit: int = 100) -> dict[str, Any]:
        """List recent network events and alerts.

        Args:
            limit: Maximum number of events to return (default: 100).

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_events(limit=limit)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_list_devices(ctx: Context) -> dict[str, Any]:
        """List all adopted network devices with full details (APs, switches, gateways).

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_devices()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_list_devices_basic(ctx: Context) -> dict[str, Any]:
        """List all adopted network devices with basic info only (faster than full list).

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_devices_basic()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_list_active_clients(ctx: Context) -> dict[str, Any]:
        """List all currently connected network clients.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_active_clients()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_list_configured_clients(ctx: Context) -> dict[str, Any]:
        """List all configured (known) clients, including those not currently connected.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_configured_clients()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_list_all_clients(ctx: Context) -> dict[str, Any]:
        """List all clients (active and historical) across all time.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_all_clients()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_get_dpi_stats(ctx: Context, dpi_type: str = "by_app") -> dict[str, Any]:
        """Get deep packet inspection (DPI) statistics.

        Args:
            dpi_type: Type of DPI stats — "by_app" or "by_cat" (by category).

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].get_dpi_stats(dpi_type=dpi_type)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_get_sysinfo(ctx: Context) -> dict[str, Any]:
        """Get controller system information (version, timezone, etc.).

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].get_sysinfo()
        except Exception as e:
            handle_client_error(e)

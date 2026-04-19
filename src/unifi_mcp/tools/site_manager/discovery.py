"""Site Manager discovery tools — read-only host, site, and device listing."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_site_manager_tools(mcp: FastMCP) -> None:
    """Register all Site Manager tools on the given FastMCP server."""

    @mcp.tool(tags={"site_manager"})
    async def site_manager_list_hosts(ctx: Context) -> dict[str, Any]:
        """List all hosts (controllers) registered in UniFi Site Manager."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["site_manager"].list_hosts()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"site_manager"})
    async def site_manager_list_sites(ctx: Context) -> dict[str, Any]:
        """List all sites across all hosts in UniFi Site Manager."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["site_manager"].list_sites()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"site_manager"})
    async def site_manager_list_devices(ctx: Context, host_id: str | None = None) -> dict[str, Any]:
        """List all devices in UniFi Site Manager, optionally filtered by host ID."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["site_manager"].list_devices(host_id=host_id)
        except Exception as e:
            handle_client_error(e)

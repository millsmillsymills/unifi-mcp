"""Site Manager discovery tools — read-only host, site, and device listing."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error

logger = logging.getLogger(__name__)


def register_site_manager_tools(mcp: FastMCP) -> None:
    """Register all Site Manager tools on the given FastMCP server."""

    @mcp.tool(tags={"site_manager"})
    async def site_manager_list_hosts(ctx: Context) -> dict[str, Any]:
        """List all hosts (controllers) registered in UniFi Site Manager."""
        try:
            client: Any = ctx.lifespan_context.clients["site_manager"]  # type: ignore[attr-defined]
            result: dict[str, Any] = await client.list_hosts()
            return result
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"site_manager"})
    async def site_manager_list_sites(ctx: Context) -> dict[str, Any]:
        """List all sites across all hosts in UniFi Site Manager."""
        try:
            client: Any = ctx.lifespan_context.clients["site_manager"]  # type: ignore[attr-defined]
            result: dict[str, Any] = await client.list_sites()
            return result
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"site_manager"})
    async def site_manager_list_devices(ctx: Context, host_id: str | None = None) -> dict[str, Any]:
        """List all devices in UniFi Site Manager, optionally filtered by host ID."""
        try:
            client: Any = ctx.lifespan_context.clients["site_manager"]  # type: ignore[attr-defined]
            result: dict[str, Any] = await client.list_devices(host_id=host_id)
            return result
        except Exception as e:
            handle_client_error(e)

"""Protect accessory device tools — chimes, lights, sensors, viewers (4 read)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_protect_device_tools(mcp: FastMCP) -> None:
    """Register Protect accessory device tools."""

    @mcp.tool(tags={"protect"})
    async def protect_list_chimes(ctx: Context) -> list[dict[str, Any]]:
        """List all Protect chime devices."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].list_chimes()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_list_lights(ctx: Context) -> list[dict[str, Any]]:
        """List all Protect smart light devices."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].list_lights()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_list_sensors(ctx: Context) -> list[dict[str, Any]]:
        """List all Protect sensor devices."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].list_sensors()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_list_viewers(ctx: Context) -> list[dict[str, Any]]:
        """List all Protect viewport devices."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].list_viewers()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

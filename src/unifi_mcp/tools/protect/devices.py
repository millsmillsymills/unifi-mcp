"""Protect accessory device tools — chimes, lights, sensors, viewers (4 read)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error
from unifi_mcp.tools._common import get_server_context


def register_protect_device_tools(mcp: FastMCP) -> None:
    """Register Protect accessory device tools."""

    @mcp.tool(tags={"protect"})
    async def protect_list_chimes(ctx: Context) -> list[dict[str, Any]]:
        """List all Protect chime devices.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["protect"].list_chimes()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_list_lights(ctx: Context) -> list[dict[str, Any]]:
        """List all Protect smart light devices.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["protect"].list_lights()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_list_sensors(ctx: Context) -> list[dict[str, Any]]:
        """List all Protect sensor devices.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["protect"].list_sensors()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_list_viewers(ctx: Context) -> list[dict[str, Any]]:
        """List all Protect viewport devices.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["protect"].list_viewers()
        except Exception as e:
            handle_client_error(e)

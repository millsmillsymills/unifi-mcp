"""Protect NVR tools (1 read + 1 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import JsonObject, get_server_context


def register_nvr_tools(mcp: FastMCP) -> None:
    """Register NVR tools."""

    @mcp.tool(tags={"protect"})
    async def unifi_protect_get_nvr(ctx: Context) -> dict[str, Any]:
        """Get NVR (Network Video Recorder) status and configuration.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["protect"].get_nvr()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "protect"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_protect_update_nvr(ctx: Context, data: JsonObject) -> dict[str, Any]:
        """Update NVR settings. Pass only fields to change.

        Args:
            data: NVR settings to update.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot update NVR in read-only mode")
            return await context.clients["protect"].update_nvr(data)
        except Exception as e:
            handle_client_error(e)

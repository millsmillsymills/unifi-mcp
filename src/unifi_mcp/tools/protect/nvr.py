"""Protect NVR tools (2 read + 1 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_nvr_tools(mcp: FastMCP) -> None:
    """Register NVR tools."""

    @mcp.tool(tags={"protect"})
    async def protect_get_bootstrap(ctx: Context) -> dict[str, Any]:
        """Get the full Protect bootstrap data (NVR, cameras, users, groups)."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].get_bootstrap()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_get_nvr(ctx: Context) -> dict[str, Any]:
        """Get NVR (Network Video Recorder) status and configuration."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].get_nvr()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "protect"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def protect_update_nvr(ctx: Context, data: dict[str, Any]) -> dict[str, Any]:
        """Update NVR settings. Pass only fields to change.

        Args:
            data: NVR settings to update.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update NVR in read-only mode")
            return await context.clients["protect"].update_nvr(data)
        except Exception as e:
            handle_client_error(e)

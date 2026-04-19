"""Protect media tools — snapshots and video exports (2 tools)."""

from __future__ import annotations

import base64
from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error
from unifi_mcp.tools._common import get_server_context


def register_media_tools(mcp: FastMCP) -> None:
    """Register Protect media tools."""

    @mcp.tool(tags={"protect"})
    async def protect_get_snapshot(ctx: Context, camera_id: str, timestamp: int | None = None) -> dict[str, Any]:
        """Get a JPEG snapshot from a camera.

        Args:
            camera_id: The camera ID.
            timestamp: Unix timestamp in milliseconds for a historical snapshot (optional, omit for live).
        """
        try:
            context = get_server_context(ctx)
            data: bytes = await context.clients["protect"].get_snapshot(camera_id, timestamp=timestamp)
            return {
                "format": "jpeg",
                "data_base64": base64.b64encode(data).decode("ascii"),
                "size_bytes": len(data),
            }
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_export_video(ctx: Context, camera_id: str, start: int, end: int) -> dict[str, Any]:
        """Export a video clip from a camera for a time range.

        Args:
            camera_id: The camera ID.
            start: Start timestamp in Unix milliseconds.
            end: End timestamp in Unix milliseconds.
        """
        try:
            context = get_server_context(ctx)
            data: bytes = await context.clients["protect"].export_video(camera_id, start, end)
            return {
                "format": "mp4",
                "data_base64": base64.b64encode(data).decode("ascii"),
                "size_bytes": len(data),
            }
        except Exception as e:
            handle_client_error(e)

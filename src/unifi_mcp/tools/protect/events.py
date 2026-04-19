"""Protect event listing tools (1 read)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_event_tools(mcp: FastMCP) -> None:
    """Register Protect event tools."""

    @mcp.tool(tags={"protect"})
    async def protect_list_events(
        ctx: Context,
        start: str | None = None,
        end: str | None = None,
        camera_ids: list[str] | None = None,
        types: list[str] | None = None,
        smart_detect_types: list[str] | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List Protect events with rich filtering.

        Args:
            start: Start time as ISO 8601 timestamp (optional).
            end: End time as ISO 8601 timestamp (optional).
            camera_ids: Filter by camera IDs (optional).
            types: Filter by event types — "motion", "ring", "smartDetect" (optional).
            smart_detect_types: Filter by smart detection types — "person", "vehicle", "animal" (optional).
            limit: Maximum number of events to return (default: 30).
            offset: Offset for pagination (default: 0).
        """
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].list_events(
                start=start,
                end=end,
                camera_ids=camera_ids,
                types=types,
                smart_detect_types=smart_detect_types,
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            handle_client_error(e)

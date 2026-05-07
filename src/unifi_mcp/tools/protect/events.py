"""Protect event listing tools (1 read)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error
from unifi_mcp.tools._common import get_server_context


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

        Returns:
            The upstream API response (a list of event records).

        Args:
            start: ISO 8601 start time (optional).
            end: ISO 8601 end time (optional).
            camera_ids: Filter by camera IDs (optional).
            types: Event types — "motion", "ring", "smartDetect" (optional).
            smart_detect_types: Smart-detect types — "person", "vehicle",
                "animal" (optional).
            limit: Maximum events to return (default 30).
            offset: Pagination offset (default 0).
        """
        try:
            context = get_server_context(ctx)
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

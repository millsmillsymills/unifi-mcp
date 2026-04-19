"""Protect camera tools (2 read + 3 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_camera_tools(mcp: FastMCP) -> None:
    """Register Protect camera tools."""

    @mcp.tool(tags={"protect"})
    async def protect_list_cameras(ctx: Context) -> list[dict[str, Any]]:
        """List all cameras managed by UniFi Protect."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].list_cameras()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"protect"})
    async def protect_get_camera(ctx: Context, camera_id: str) -> dict[str, Any]:
        """Get detailed info for a specific camera.

        Args:
            camera_id: The camera ID.
        """
        try:
            context = _get_ctx(ctx)
            return await context.clients["protect"].get_camera(camera_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "protect"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def protect_update_camera(ctx: Context, camera_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update camera settings. Pass only fields to change.

        Args:
            camera_id: The camera ID.
            data: Camera settings to update (e.g., {"name": "Front Door", "ledSettings": {"isEnabled": true}}).
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update camera in read-only mode")
            return await context.clients["protect"].update_camera(camera_id, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "protect"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def protect_set_recording_mode(
        ctx: Context,
        camera_id: str,
        mode: str,
        pre_padding: int | None = None,
        post_padding: int | None = None,
    ) -> dict[str, Any]:
        """Set the recording mode for a camera.

        Args:
            camera_id: The camera ID.
            mode: Recording mode — "always", "motion", "never", "schedule".
            pre_padding: Pre-event recording padding in seconds (optional).
            post_padding: Post-event recording padding in seconds (optional).
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot set recording mode in read-only mode")
            return await context.clients["protect"].set_recording_mode(
                camera_id, mode, pre_padding=pre_padding, post_padding=post_padding
            )
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "protect"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def protect_set_smart_detection(ctx: Context, camera_id: str, object_types: list[str]) -> dict[str, Any]:
        """Configure smart detection object types for a camera.

        Args:
            camera_id: The camera ID.
            object_types: List of object types to detect — e.g., ["person", "vehicle", "animal"].
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot set smart detection in read-only mode")
            return await context.clients["protect"].set_smart_detection(camera_id, object_types)
        except Exception as e:
            handle_client_error(e)

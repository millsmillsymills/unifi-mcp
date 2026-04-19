"""Protect API client for UniFi Protect NVRs."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from unifi_mcp.clients.base import BaseUniFiClient
from unifi_mcp.errors import UniFiError

logger = logging.getLogger(__name__)


class ProtectClient(BaseUniFiClient):
    """Client for the UniFi Protect API on a local controller.

    Communicates with the controller's proxy API at
    ``/proxy/protect/api/``.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        verify_ssl: bool = False,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._path_prefix = "/proxy/protect/api/"
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            verify_ssl=verify_ssl,
            timeout=timeout,
            max_retries=max_retries,
        )

    # -- Read methods -------------------------------------------------------

    async def get_bootstrap(self) -> dict[str, Any]:
        """Get full NVR bootstrap data."""
        result: dict[str, Any] = await self.get("bootstrap")
        return result

    async def list_cameras(self) -> list[dict[str, Any]]:
        """List all cameras."""
        result: list[dict[str, Any]] = await self.get("cameras")
        return result

    async def get_camera(self, camera_id: str) -> dict[str, Any]:
        """Get a specific camera by ID."""
        result: dict[str, Any] = await self.get(f"cameras/{camera_id}")
        return result

    async def list_events(
        self,
        start: str | None = None,
        end: str | None = None,
        camera_ids: list[str] | None = None,
        types: list[str] | None = None,
        smart_detect_types: list[str] | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List events with optional filters.

        Args:
            start: Start timestamp for the query range.
            end: End timestamp for the query range.
            camera_ids: Filter by camera IDs (comma-separated in query).
            types: Filter by event types (comma-separated in query).
            smart_detect_types: Filter by smart detection types (comma-separated in query).
            limit: Maximum number of events to return.
            offset: Number of events to skip.
        """
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if camera_ids is not None:
            params["cameras"] = ",".join(camera_ids)
        if types is not None:
            params["types"] = ",".join(types)
        if smart_detect_types is not None:
            params["smartDetectTypes"] = ",".join(smart_detect_types)

        result: list[dict[str, Any]] = await self.get("events", params=params)
        return result

    async def get_nvr(self) -> dict[str, Any]:
        """Get NVR system information."""
        result: dict[str, Any] = await self.get("nvr")
        return result

    async def list_chimes(self) -> list[dict[str, Any]]:
        """List all chimes."""
        result: list[dict[str, Any]] = await self.get("chimes")
        return result

    async def list_lights(self) -> list[dict[str, Any]]:
        """List all lights."""
        result: list[dict[str, Any]] = await self.get("lights")
        return result

    async def list_sensors(self) -> list[dict[str, Any]]:
        """List all sensors."""
        result: list[dict[str, Any]] = await self.get("sensors")
        return result

    async def list_viewers(self) -> list[dict[str, Any]]:
        """List all viewers."""
        result: list[dict[str, Any]] = await self.get("viewers")
        return result

    # -- Write methods ------------------------------------------------------

    async def update_camera(self, camera_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update camera settings."""
        result: dict[str, Any] = await self.put(f"cameras/{camera_id}", json=data)
        return result

    async def set_recording_mode(
        self,
        camera_id: str,
        mode: str,
        pre_padding: int | None = None,
        post_padding: int | None = None,
    ) -> dict[str, Any]:
        """Set the recording mode for a camera.

        Args:
            camera_id: The camera ID.
            mode: Recording mode (e.g. ``always``, ``motion``, ``never``).
            pre_padding: Optional pre-event recording padding in seconds.
            post_padding: Optional post-event recording padding in seconds.
        """
        recording_settings: dict[str, Any] = {"mode": mode}
        if pre_padding is not None:
            recording_settings["prePaddingSecs"] = pre_padding
        if post_padding is not None:
            recording_settings["postPaddingSecs"] = post_padding

        result: dict[str, Any] = await self.put(
            f"cameras/{camera_id}",
            json={"recordingSettings": recording_settings},
        )
        return result

    async def set_smart_detection(self, camera_id: str, object_types: list[str]) -> dict[str, Any]:
        """Set smart detection object types for a camera.

        Args:
            camera_id: The camera ID.
            object_types: List of smart detection object types to enable.
        """
        result: dict[str, Any] = await self.put(
            f"cameras/{camera_id}",
            json={"smartDetectSettings": {"objectTypes": object_types}},
        )
        return result

    async def update_nvr(self, data: dict[str, Any]) -> dict[str, Any]:
        """Update NVR settings."""
        result: dict[str, Any] = await self.put("nvr", json=data)
        return result

    # -- Media methods ------------------------------------------------------

    async def get_snapshot(self, camera_id: str, timestamp: int | None = None) -> bytes:
        """Get a snapshot image from a camera.

        Args:
            camera_id: The camera ID.
            timestamp: Optional Unix timestamp (ms) for a historical snapshot.

        Returns:
            Raw snapshot bytes (JPEG).
        """
        params: dict[str, int] = {}
        if timestamp is not None:
            params["ts"] = timestamp
        return await self.get_raw(f"cameras/{camera_id}/snapshot", params=params)

    async def export_video(self, camera_id: str, start: int, end: int, *, max_bytes: int | None = None) -> bytes:
        """Export a video clip from a camera.

        Args:
            camera_id: The camera ID.
            start: Start timestamp in milliseconds.
            end: End timestamp in milliseconds.
            max_bytes: If set, stream the response and abort if the export
                exceeds this many bytes. Prevents OOM on unbounded clips.

        Returns:
            Raw video bytes.
        """
        return await self.get_raw(
            f"cameras/{camera_id}/video/export",
            params={"start": start, "end": end},
            max_bytes=max_bytes,
        )

    # -- Lifecycle ----------------------------------------------------------

    async def validate_connection(self) -> bool:
        """Validate connectivity by fetching NVR info."""
        try:
            await self.get_nvr()
        except (UniFiError, httpx.HTTPError):
            logger.debug("Protect API connection validation failed", exc_info=True)
            return False
        else:
            return True

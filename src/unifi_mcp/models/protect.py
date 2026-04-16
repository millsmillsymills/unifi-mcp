"""Pydantic models for UniFi Protect API responses."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from unifi_mcp.models.common import UniFiBaseModel


class Camera(UniFiBaseModel):
    """A Protect camera."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    mac: str | None = None
    model: str | None = None
    type: str | None = None
    state: str | None = None
    is_connected: bool | None = Field(default=None, alias="isConnected")
    host: str | None = None
    recording_settings: dict[str, Any] | None = Field(default=None, alias="recordingSettings")
    smart_detect_settings: dict[str, Any] | None = Field(default=None, alias="smartDetectSettings")
    last_motion: int | None = Field(default=None, alias="lastMotion")


class ProtectEvent(UniFiBaseModel):
    """A Protect event (motion, smart detection, etc.)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    type: str | None = None
    start: int | None = None
    end: int | None = None
    camera: str | None = None
    score: int | None = None
    smart_detect_types: list[str] | None = Field(default=None, alias="smartDetectTypes")
    smart_detect_events: list[str] | None = Field(default=None, alias="smartDetectEvents")


class NVR(UniFiBaseModel):
    """The Protect NVR (Network Video Recorder)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    mac: str | None = None
    host: str | None = None
    version: str | None = None
    firmware_version: str | None = Field(default=None, alias="firmwareVersion")
    uptime: int | None = None
    last_seen: int | None = Field(default=None, alias="lastSeen")
    is_connected: bool | None = Field(default=None, alias="isConnected")
    storage_info: dict[str, Any] | None = Field(default=None, alias="storageInfo")
    recording_retention_duration_ms: int | None = Field(default=None, alias="recordingRetentionDurationMs")


class Chime(UniFiBaseModel):
    """A Protect chime."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    mac: str | None = None
    type: str | None = None
    state: str | None = None
    is_connected: bool | None = Field(default=None, alias="isConnected")


class Light(UniFiBaseModel):
    """A Protect flood light."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    mac: str | None = None
    type: str | None = None
    state: str | None = None
    is_connected: bool | None = Field(default=None, alias="isConnected")
    is_pir_motion_detected: bool | None = Field(default=None, alias="isPirMotionDetected")


class Sensor(UniFiBaseModel):
    """A Protect sensor."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    mac: str | None = None
    type: str | None = None
    state: str | None = None
    is_connected: bool | None = Field(default=None, alias="isConnected")
    stats: dict[str, Any] | None = None

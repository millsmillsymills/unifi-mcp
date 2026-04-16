"""Pydantic models for UniFi Site Manager API responses."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from unifi_mcp.models.common import UniFiBaseModel


class CloudHost(UniFiBaseModel):
    """A host (controller) registered in UniFi Site Manager."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    reported_state: dict[str, Any] | None = Field(default=None, alias="reportedState")
    hardware_id: str | None = Field(default=None, alias="hardwareId")
    type: str | None = None
    name: str | None = None


class CloudSite(UniFiBaseModel):
    """A site within UniFi Site Manager."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    host_id: str | None = Field(default=None, alias="hostId")
    status: str | None = None


class CloudDevice(UniFiBaseModel):
    """A device registered in UniFi Site Manager."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    mac: str | None = None
    model: str | None = None
    host_id: str | None = Field(default=None, alias="hostId")
    status: str | None = None

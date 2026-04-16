"""Shared model types for UniFi APIs."""

from __future__ import annotations

from pydantic import BaseModel


class UniFiBaseModel(BaseModel):
    """Base model that tolerates unknown fields from UniFi APIs."""

    model_config = {"extra": "allow"}

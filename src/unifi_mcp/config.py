"""Configuration management for UniFi MCP server using pydantic-settings."""

from __future__ import annotations

import enum
import logging

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class UniFiMode(enum.StrEnum):
    """Server operation mode."""

    READONLY = "readonly"
    READWRITE = "readwrite"


class UniFiConfig(BaseSettings):
    """Configuration loaded from environment variables and .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Mode
    unifi_mode: UniFiMode = UniFiMode.READONLY

    # Network API
    unifi_network_host: str = "192.168.1.1"
    unifi_network_port: int = Field(default=443, ge=1, le=65535)
    unifi_network_api: SecretStr | None = None
    unifi_network_site: str = "default"
    unifi_network_verify_ssl: bool = False

    # Protect API
    unifi_protect_host: str | None = None
    unifi_protect_port: int = Field(default=443, ge=1, le=65535)
    unifi_protect_api: SecretStr | None = None
    unifi_protect_verify_ssl: bool = False

    # Site Manager API
    unifi_site_manager_api: SecretStr | None = None

    # General
    unifi_request_timeout: int = Field(default=30, gt=0)
    unifi_max_retries: int = Field(default=3, ge=0)
    # Cap raw-byte responses to keep a malicious or misconfigured request
    # from OOMing the server. Video exports and snapshots have very different
    # expected-size distributions (exports: tens to hundreds of MB; snapshots:
    # single MB), so they get independent caps.
    unifi_max_export_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    unifi_max_snapshot_bytes: int = Field(default=50 * 1024 * 1024, gt=0)

    @model_validator(mode="after")
    def _default_protect_host(self) -> UniFiConfig:
        """Default Protect host to Network host when not explicitly set.

        WARNING: on deployments where Protect runs on a separate NVR (e.g.
        UCK-G2-Plus on a different IP from the gateway), leaving
        ``UNIFI_PROTECT_HOST`` unset points Protect at the wrong device.
        ``validate_connection`` then fails, and all Protect tools deregister
        at startup. See #104 for the lifespan-level diagnostic.

        When the fallback fires *and* a Protect API key is configured, emit
        an INFO log so the operator can see that the default was applied and
        decide whether it matches their topology.
        """
        if self.unifi_protect_host is None:
            if self.unifi_protect_api is not None:
                logger.info(
                    "UNIFI_PROTECT_HOST not set; defaulting to UNIFI_NETWORK_HOST=%s. "
                    "If Protect runs on a different device (e.g. a separate UCK NVR), "
                    "set UNIFI_PROTECT_HOST explicitly to avoid a silent "
                    "validate_connection failure.",
                    self.unifi_network_host,
                )
            self.unifi_protect_host = self.unifi_network_host
        return self

    @property
    def writes_enabled(self) -> bool:
        """Whether write tools are enabled.

        True only when ``UNIFI_MODE=readwrite`` is set explicitly. The default
        ``readonly`` mode leaves the server in a safe, mutation-free posture.
        """
        return self.unifi_mode == UniFiMode.READWRITE

    @property
    def network_enabled(self) -> bool:
        """Whether Network API is configured."""
        return self.unifi_network_api is not None

    @property
    def protect_enabled(self) -> bool:
        """Whether Protect API is configured."""
        return self.unifi_protect_api is not None

    @property
    def site_manager_enabled(self) -> bool:
        """Whether Site Manager API is configured."""
        return self.unifi_site_manager_api is not None

    @property
    def network_base_url(self) -> str:
        """Base URL for Network API."""
        return f"https://{self.unifi_network_host}:{self.unifi_network_port}"

    @property
    def protect_base_url(self) -> str:
        """Base URL for Protect API."""
        host = self.unifi_protect_host or self.unifi_network_host
        return f"https://{host}:{self.unifi_protect_port}"

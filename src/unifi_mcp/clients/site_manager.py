"""Site Manager API client for UniFi cloud services."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from unifi_mcp.clients.base import BaseUniFiClient
from unifi_mcp.errors import UniFiError

logger = logging.getLogger(__name__)

SITE_MANAGER_BASE_URL = "https://api.ui.com"


class SiteManagerClient(BaseUniFiClient):
    """Client for the UniFi Site Manager cloud API.

    The Site Manager API is a public cloud service (api.ui.com) that provides
    a unified view of all hosts, sites, and devices across an account.
    """

    _path_prefix: str = "/v1/"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            base_url=SITE_MANAGER_BASE_URL,
            api_key=api_key,
            verify_ssl=True,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def list_hosts(self) -> dict[str, Any]:
        """List all hosts (controllers) registered in Site Manager."""
        result: dict[str, Any] = await self.get("hosts")
        return result

    async def list_sites(self) -> dict[str, Any]:
        """List all sites across all hosts."""
        result: dict[str, Any] = await self.get("sites")
        return result

    async def list_devices(self, host_id: str | None = None) -> dict[str, Any]:
        """List all devices, optionally filtered by host ID."""
        params: dict[str, str] = {}
        if host_id is not None:
            params["hostId"] = host_id
        result: dict[str, Any] = await self.get("devices", params=params)
        return result

    async def validate_connection(self) -> bool:
        """Validate connectivity by attempting to list hosts.

        Returns False on any UniFi or HTTP error. The caught exception is
        stored on ``self._last_validation_error`` so the lifespan can
        surface the failure class in its WARN log.
        """
        try:
            await self.list_hosts()
        except (UniFiError, httpx.HTTPError) as exc:
            self._last_validation_error = exc
            logger.debug("Site Manager connection validation failed", exc_info=True)
            return False
        else:
            self._last_validation_error = None
            return True

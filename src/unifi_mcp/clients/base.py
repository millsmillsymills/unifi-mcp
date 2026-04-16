"""Base API client with retry, auth, and error mapping."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from unifi_mcp.errors import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiError,
    UniFiNotFoundError,
    UniFiRateLimitError,
)


class BaseUniFiClient:
    """Base client for UniFi APIs with retry, auth, and error mapping.

    Subclasses must set ``_path_prefix`` and implement ``validate_connection()``.
    """

    _path_prefix: str = ""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        verify_ssl: bool = False,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            verify=verify_ssl,
            timeout=httpx.Timeout(timeout),
        )

    # ── HTTP helpers ────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        """Build full path with prefix."""
        return f"{self._path_prefix}{path}"

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map HTTP status codes to typed exceptions."""
        if response.is_success:
            return
        status = response.status_code
        body = response.text[:200]
        if status in (401, 403):
            raise UniFiAuthError(f"HTTP {status}: {body}", status_code=status)
        if status == 404:
            raise UniFiNotFoundError(f"HTTP {status}: {body}", status_code=status)
        if status == 429:
            raise UniFiRateLimitError(f"HTTP {status}: {body}", status_code=status)
        raise UniFiError(f"HTTP {status}: {body}", status_code=status)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Execute an HTTP request with retry on transient errors."""

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
            reraise=True,
        )
        async def _do() -> httpx.Response:
            return await self._client.request(method, self._url(path), **kwargs)

        try:
            response = await _do()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise UniFiConnectionError(str(exc)) from exc

        self._raise_for_status(response)
        return response

    def _parse_json(self, response: httpx.Response) -> Any:
        """Parse JSON response body, wrapping decode errors as UniFiError."""
        try:
            return response.json()
        except ValueError as exc:
            body = response.text[:200]
            raise UniFiError(
                f"Invalid JSON in response (HTTP {response.status_code}): {body}",
                status_code=response.status_code,
            ) from exc

    async def get(self, path: str, **kwargs: Any) -> Any:
        """HTTP GET, returns parsed JSON."""
        response = await self._request("GET", path, **kwargs)
        return self._parse_json(response)

    async def post(self, path: str, **kwargs: Any) -> Any:
        """HTTP POST, returns parsed JSON."""
        response = await self._request("POST", path, **kwargs)
        if response.status_code == 204 or not response.content:
            return {}
        return self._parse_json(response)

    async def put(self, path: str, **kwargs: Any) -> Any:
        """HTTP PUT, returns parsed JSON."""
        response = await self._request("PUT", path, **kwargs)
        if response.status_code == 204 or not response.content:
            return {}
        return self._parse_json(response)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        """HTTP DELETE, returns parsed JSON or empty dict."""
        response = await self._request("DELETE", path, **kwargs)
        if response.status_code == 204 or not response.content:
            return {}
        return self._parse_json(response)

    async def get_raw(self, path: str, **kwargs: Any) -> bytes:
        """HTTP GET, returns raw bytes (for media endpoints)."""
        response = await self._request("GET", path, **kwargs)
        result: bytes = response.content
        return result

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def validate_connection(self) -> bool:
        """Validate that the API is reachable and authenticated.

        Subclasses should override with a lightweight health-check request.
        """
        raise NotImplementedError

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

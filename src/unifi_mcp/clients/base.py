"""Base API client with retry, auth, and error mapping."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from unifi_mcp.errors import (
    UniFiAuthError,
    UniFiBadRequestError,
    UniFiConnectionError,
    UniFiError,
    UniFiNotFoundError,
    UniFiRateLimitError,
    UniFiServerError,
    UniFiTimeoutError,
)

logger = logging.getLogger(__name__)

# Upper bound on a single Retry-After sleep. Ubiquiti sometimes returns very
# generous values; capping keeps a single tool call bounded.
_MAX_RETRY_AFTER_SECONDS = 30


class BaseUniFiClient(ABC):
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

    @staticmethod
    def _parse_retry_after(header_value: str | None) -> int | None:
        """Parse a Retry-After header value in seconds.

        Handles the integer-seconds form (`Retry-After: 30`). The HTTP-date
        form is rare on JSON APIs and not parsed here; unparseable values
        return None.
        """
        if header_value is None:
            return None
        try:
            seconds = int(header_value.strip())
        except (TypeError, ValueError):
            return None
        return max(seconds, 0)

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map HTTP status codes to typed exceptions."""
        if response.is_success:
            return
        status = response.status_code
        body = response.text[:200]
        if status == 400:
            raise UniFiBadRequestError(f"HTTP {status}: {body}", status_code=status)
        if status in (401, 403):
            raise UniFiAuthError(f"HTTP {status}: {body}", status_code=status)
        if status == 404:
            raise UniFiNotFoundError(f"HTTP {status}: {body}", status_code=status)
        if status == 429:
            retry_after = self._parse_retry_after(response.headers.get("retry-after"))
            raise UniFiRateLimitError(
                f"HTTP {status}: {body}",
                status_code=status,
                retry_after=retry_after,
            )
        if 500 <= status < 600:
            raise UniFiServerError(f"HTTP {status}: {body}", status_code=status)
        raise UniFiError(f"HTTP {status}: {body}", status_code=status)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Execute an HTTP request with retry on transient errors.

        ConnectError is always retried (the request never reached the server).
        TimeoutException is only retried for GET/HEAD — for POST/PUT/DELETE/PATCH
        the server may have processed the write before the response was lost,
        and a retry would cause double-execution.

        HTTP 429 is retried for idempotent methods (GET/HEAD), sleeping for
        the ``Retry-After`` duration (capped at ``_MAX_RETRY_AFTER_SECONDS``)
        or 1 second if the header is absent. Bounded by ``self._max_retries``.
        """
        method_upper = method.upper()
        retry_on: tuple[type[BaseException], ...] = (httpx.ConnectError,)
        if method_upper in ("GET", "HEAD"):
            retry_on = (httpx.ConnectError, httpx.TimeoutException)

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(retry_on),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _do() -> httpx.Response:
            return await self._client.request(method, self._url(path), **kwargs)

        rate_limit_attempts = 0
        while True:
            try:
                response = await _do()
            except httpx.TimeoutException as exc:
                raise UniFiTimeoutError(str(exc)) from exc
            except httpx.ConnectError as exc:
                raise UniFiConnectionError(str(exc)) from exc

            try:
                self._raise_for_status(response)
            except UniFiRateLimitError as exc:
                # Honor Retry-After on idempotent methods only; a POST/PUT/DELETE
                # that returned 429 may have partially processed, and a retry
                # could cause double-execution.
                if method_upper not in ("GET", "HEAD"):
                    raise
                if rate_limit_attempts >= self._max_retries:
                    raise
                sleep_seconds = min(exc.retry_after or 1, _MAX_RETRY_AFTER_SECONDS)
                rate_limit_attempts += 1
                logger.warning(
                    "Rate limited (429) on %s %s; sleeping %ds before retry %d/%d",
                    method_upper,
                    path,
                    sleep_seconds,
                    rate_limit_attempts,
                    self._max_retries,
                )
                await asyncio.sleep(sleep_seconds)
                continue

            return response

    def _parse_json(self, response: httpx.Response) -> Any:
        """Parse JSON response body, wrapping decode errors as UniFiError.

        Raises UniFiAuthError when the controller returns HTML on a JSON
        endpoint. UniFi OS serves the SPA portal (HTML) on ``/proxy/<api>/*``
        when the request hits a path that rejects the configured auth — a
        signature of wrong ``_path_prefix``, key-for-wrong-host, or an
        API that requires session auth. Classifying this case as "auth /
        path mismatch" instead of generic "invalid JSON" lets the operator
        act on it.
        """
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith("text/html"):
            body = response.text[:200]
            raise UniFiAuthError(
                f"Controller returned HTML instead of JSON on HTTP {response.status_code} — "
                f"likely an auth/path mismatch (hit the UniFi OS portal). Check host, "
                f"port, and API-key scope. Body: {body}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            body = response.text[:200]
            raise UniFiError(
                f"Invalid JSON in response (HTTP {response.status_code}): {body}",
                status_code=None,
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

    async def get_raw(self, path: str, *, max_bytes: int | None = None, **kwargs: Any) -> bytes:
        """HTTP GET returning raw bytes (for media endpoints).

        When ``max_bytes`` is set the response is streamed and aborted as soon
        as the accumulated payload exceeds the cap, raising ``UniFiError``
        instead of silently consuming unbounded memory.

        Both branches share the same transient-error retry semantics as
        ``_request``: ``ConnectError`` and ``TimeoutException`` are retried
        (bounded by ``max_retries``), status-code errors are mapped to typed
        UniFi exceptions.
        """
        if max_bytes is None:
            response = await self._request("GET", path, **kwargs)
            result: bytes = response.content
            return result

        url = self._url(path)
        retry_on: tuple[type[BaseException], ...] = (httpx.ConnectError, httpx.TimeoutException)

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(retry_on),
            reraise=True,
        )
        async def _stream_once() -> bytes:
            """Stream one request attempt, enforcing max_bytes mid-stream.

            Transport errors raised in here bubble out of the context manager
            and are caught by tenacity for retry. Mapped UniFi errors bubble
            unchanged (they aren't in ``retry_on``).
            """
            async with self._client.stream("GET", url, **kwargs) as response:
                if not response.is_success:
                    # _raise_for_status reads response.text, which on a
                    # streaming response requires the body to be loaded first.
                    await response.aread()
                    self._raise_for_status(response)
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise UniFiError(
                            f"Response exceeded max_bytes={max_bytes} while streaming {path}",
                            status_code=response.status_code,
                        )
                    chunks.append(chunk)
                return b"".join(chunks)

        try:
            return await _stream_once()
        except httpx.TimeoutException as exc:
            raise UniFiTimeoutError(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise UniFiConnectionError(str(exc)) from exc

    # ── Lifecycle ───────────────────────────────────────────────────────

    @abstractmethod
    async def validate_connection(self) -> bool:
        """Validate that the API is reachable and authenticated.

        Subclasses must override with a lightweight health-check request.

        Returns False on any UniFi or HTTP error.

        NOTE: a False return causes the server lifespan to deregister every
        tool for this API via ``server.disable(tags={api_name})``. Failure
        modes that feel transient — a wrong ``_path_prefix``, expired API
        key, transient 404, SSL mismatch — will make all of this API's
        tools disappear from the MCP tool list with only a log line. See
        #104 for the diagnostic enhancement that surfaces *why* validation
        failed.
        """

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

"""Base API client with retry, auth, and error mapping."""

from __future__ import annotations

import asyncio
import logging
import os
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

from unifi_mcp.clients._pinning import CertPinningTransport
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

# Sensitive keys that must be masked before an error body is logged at DEBUG
# or stringified into a UniFi exception. UniFi controllers echo the submitted
# JSON in some 400 responses, so a Wi-Fi passphrase or RADIUS secret can come
# back unmasked in an error body — match #146's redaction set so a value
# never appears in two different forms depending on the call site. See #148.
_SENSITIVE_KEYS = frozenset(
    {
        "x_passphrase",
        "x_password",
        "password",
        "passphrase",
        "radius_secret",
        "wpa_psk",
        "private_key",
        "ssotoken",
        "bearer",
        "token",
        "api_key",
        "apikey",
        "secret",
    }
)

# Placeholder substituted for redacted values so the operator can still see
# the structure of the response without the credential.
_REDACTED = "***REDACTED***"


def _redact_sensitive(value: Any) -> Any:
    """Return a copy of ``value`` with sensitive keys replaced.

    Walks nested dicts and lists. String comparisons are case-insensitive
    and also match ``super_*_password`` / ``super_*_url`` callback keys
    that have leaked controller config in the past. Non-container values
    pass through untouched.
    """
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, sub in value.items():
            key_str = str(key)
            lowered = key_str.lower()
            if lowered in _SENSITIVE_KEYS or (
                lowered.startswith("super_") and (lowered.endswith("_password") or lowered.endswith("_url"))
            ):
                redacted[key_str] = _REDACTED
            else:
                redacted[key_str] = _redact_sensitive(sub)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _log_raw_bodies_enabled() -> bool:
    """Whether the operator opted into untouched-body DEBUG logging.

    Read from the environment directly (rather than through ``UniFiConfig``)
    so the helper stays available to callers that construct clients without
    a config object — notably tests. Truthy values: ``1``, ``true``, ``yes``
    (case-insensitive).
    """
    return os.environ.get("UNIFI_LOG_RAW_BODIES", "").strip().lower() in {"1", "true", "yes"}


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
        cert_fingerprint: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._max_retries = max_retries
        client_kwargs: dict[str, Any] = {
            "base_url": base_url,
            "headers": {"X-API-Key": api_key},
            "timeout": httpx.Timeout(timeout),
        }
        if cert_fingerprint is not None:
            # Pinning takes precedence over verify_ssl: chain/hostname checks
            # are disabled inside the pinning transport because the pin is
            # the trust anchor.
            client_kwargs["transport"] = CertPinningTransport(expected_fingerprint=cert_fingerprint)
        else:
            client_kwargs["verify"] = verify_ssl
        self._client = httpx.AsyncClient(**client_kwargs)
        # Captured by validate_connection on failure so the lifespan can
        # report WHY the API was disabled (auth vs. unreachability vs. path
        # mismatch) instead of a generic "validate_connection failed". See
        # #104.
        self._last_validation_error: BaseException | None = None

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

    @staticmethod
    def _extract_error_body(response: httpx.Response) -> str:
        """Return a short, actionable error description from a response body.

        UniFi APIs wrap error details in structured JSON; extracting the
        useful field beats truncating raw JSON at 200 chars and cutting the
        message off mid-word. Recognized envelopes:

        - Network legacy: ``{"meta": {"rc": "error", "msg": "api.err.X"}}``
        - Protect integration: ``{"error": {"message": "..."}}``
        - Simpler forms: ``{"error": "..."}`` or ``{"message": "..."}``

        Sensitive keys (passphrases, secrets, tokens) are masked at this
        boundary so downstream WARN logs and ``ToolError`` strings never
        carry reflected credentials (#148). When ``UNIFI_LOG_RAW_BODIES`` is
        unset (default), the DEBUG body log also receives the redacted form;
        operators that need the untouched body for diagnosis must opt in.
        """
        raw_log_enabled = _log_raw_bodies_enabled()
        try:
            parsed = response.json()
        except ValueError:
            parsed = None

        if parsed is not None:
            safe_payload = _redact_sensitive(parsed)
            if raw_log_enabled:
                logger.debug("Error response body (HTTP %d): %s", response.status_code, response.text)
            else:
                logger.debug("Error response body (HTTP %d, redacted): %s", response.status_code, safe_payload)
            if isinstance(safe_payload, dict):
                meta = safe_payload.get("meta") if isinstance(safe_payload.get("meta"), dict) else None
                err = safe_payload.get("error")
                candidates: list[Any] = [
                    meta.get("msg") if meta else None,
                    err.get("message") if isinstance(err, dict) else None,
                    err if isinstance(err, str) else None,
                    safe_payload.get("message"),
                ]
                for candidate in candidates:
                    if isinstance(candidate, str) and candidate:
                        return candidate
            # Structured but unrecognized — surface a stable opaque hint
            # rather than a 200-char slice that could leak HTML scraps.
            return "<unparseable body, see DEBUG log>"

        # Non-JSON body.
        if raw_log_enabled:
            logger.debug("Error response body (HTTP %d): %s", response.status_code, response.text)
        else:
            logger.debug(
                "Error response body (HTTP %d, %d bytes): redacted (set UNIFI_LOG_RAW_BODIES=1 to log)",
                response.status_code,
                len(response.text),
            )
        if not response.text.strip():
            # Empty (or whitespace-only) body: surface a hint instead of an
            # uninformative dangling "HTTP 401: " so operators have something
            # to look up. WWW-Authenticate is the most useful auth-error clue.
            www_auth = response.headers.get("www-authenticate")
            if www_auth:
                return f"(empty body; WWW-Authenticate: {www_auth})"
            return "(empty body)"
        return "<unparseable body, see DEBUG log>"

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map HTTP status codes to typed exceptions."""
        if response.is_success:
            return
        status = response.status_code
        body = self._extract_error_body(response)
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

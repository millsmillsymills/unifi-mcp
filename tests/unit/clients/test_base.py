"""Tests for the base UniFi API client."""

import logging

import httpx
import pytest
import respx

from unifi_mcp.clients.base import BaseUniFiClient
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

BASE_URL = "https://10.0.0.1:443"


class _ConcreteClient(BaseUniFiClient):
    """Minimal concrete subclass so the abstract base can be instantiated in tests."""

    async def validate_connection(self) -> bool:
        return True


@pytest.fixture
def client():
    return _ConcreteClient(
        base_url=BASE_URL,
        api_key="test-api-key",
        verify_ssl=False,
        timeout=5,
        max_retries=2,
    )


class TestGetRequest:
    @respx.mock
    async def test_get_returns_json(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(200, json={"data": [{"id": "1"}]}))
        result = await client.get("/test")
        assert result == {"data": [{"id": "1"}]}

    @respx.mock
    async def test_api_key_header_included(self, client):
        route = respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(200, json={}))
        await client.get("/test")
        assert route.calls[0].request.headers["X-API-Key"] == "test-api-key"


class TestPostRequest:
    @respx.mock
    async def test_post_returns_json(self, client):
        respx.post(f"{BASE_URL}/test").mock(return_value=httpx.Response(200, json={"meta": {"rc": "ok"}}))
        result = await client.post("/test", json={"name": "foo"})
        assert result == {"meta": {"rc": "ok"}}

    @respx.mock
    async def test_post_204_returns_empty_dict(self, client):
        respx.post(f"{BASE_URL}/test").mock(return_value=httpx.Response(204))
        result = await client.post("/test")
        assert result == {}


class TestPutRequest:
    @respx.mock
    async def test_put_returns_json(self, client):
        respx.put(f"{BASE_URL}/test/123").mock(return_value=httpx.Response(200, json={"data": [{"_id": "123"}]}))
        result = await client.put("/test/123", json={"name": "updated"})
        assert result == {"data": [{"_id": "123"}]}

    @respx.mock
    async def test_put_204_returns_empty_dict(self, client):
        respx.put(f"{BASE_URL}/test/123").mock(return_value=httpx.Response(204))
        result = await client.put("/test/123", json={"name": "updated"})
        assert result == {}

    @respx.mock
    async def test_put_empty_body_returns_empty_dict(self, client):
        respx.put(f"{BASE_URL}/test/123").mock(return_value=httpx.Response(200, content=b""))
        result = await client.put("/test/123", json={})
        assert result == {}


class TestDeleteRequest:
    @respx.mock
    async def test_delete_204_returns_empty_dict(self, client):
        respx.delete(f"{BASE_URL}/test/123").mock(return_value=httpx.Response(204))
        result = await client.delete("/test/123")
        assert result == {}

    @respx.mock
    async def test_delete_returns_json_body_when_present(self, client):
        respx.delete(f"{BASE_URL}/test/123").mock(return_value=httpx.Response(200, json={"meta": {"rc": "ok"}}))
        result = await client.delete("/test/123")
        assert result == {"meta": {"rc": "ok"}}


class TestErrorMapping:
    @respx.mock
    async def test_401_raises_auth_error(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(401, text="Unauthorized"))
        with pytest.raises(UniFiAuthError, match="401"):
            await client.get("/test")

    @respx.mock
    async def test_403_raises_auth_error(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(403, text="Forbidden"))
        with pytest.raises(UniFiAuthError, match="403"):
            await client.get("/test")

    @respx.mock
    async def test_404_raises_not_found(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(404, text="Not Found"))
        with pytest.raises(UniFiNotFoundError, match="404"):
            await client.get("/test")

    @respx.mock
    async def test_429_raises_rate_limit(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(429, text="Too Many Requests"))
        with pytest.raises(UniFiRateLimitError, match="429"):
            await client.get("/test")

    @respx.mock
    async def test_400_raises_bad_request(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(400, text="Bad Request"))
        with pytest.raises(UniFiBadRequestError, match="400"):
            await client.get("/test")

    @respx.mock
    async def test_500_raises_server_error(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(500, text="Internal Server Error"))
        with pytest.raises(UniFiServerError, match="500"):
            await client.get("/test")
        # Still a UniFiError subclass, so existing catchers keep working.

    @respx.mock
    async def test_502_raises_server_error(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(502, text="Bad Gateway"))
        with pytest.raises(UniFiServerError, match="502"):
            await client.get("/test")

    @respx.mock
    async def test_418_raises_generic_unifi_error(self, client):
        respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(418, text="I'm a teapot"))
        with pytest.raises(UniFiError, match="418"):
            await client.get("/test")


class TestMalformedJson:
    @respx.mock
    async def test_200_with_invalid_json_raises_unifi_error_with_none_status_code(self, client):
        respx.get(f"{BASE_URL}/test").mock(
            return_value=httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})
        )
        with pytest.raises(UniFiError, match="Invalid JSON") as exc_info:
            await client.get("/test")
        assert exc_info.value.status_code is None

    @respx.mock
    async def test_200_with_empty_body_on_get_raises_unifi_error(self, client):
        respx.get(f"{BASE_URL}/test").mock(
            return_value=httpx.Response(200, content=b"", headers={"content-type": "application/json"})
        )
        with pytest.raises(UniFiError, match="Invalid JSON") as exc_info:
            await client.get("/test")
        assert exc_info.value.status_code is None

    @respx.mock
    async def test_200_with_html_body_raises_auth_error_not_invalid_json(self, client):
        """UniFi OS returns the SPA portal HTML on 200 when the request hits a
        path that rejects X-API-KEY (e.g. a protected proxy endpoint that
        requires cookie auth). This must classify as an auth/path mismatch,
        not a generic "Invalid JSON" error.
        """
        html_portal = b'<!doctype html><html lang="en"><head><title>UniFi OS</title></head><body></body></html>'
        respx.get(f"{BASE_URL}/test").mock(
            return_value=httpx.Response(200, content=html_portal, headers={"content-type": "text/html; charset=utf-8"})
        )
        with pytest.raises(UniFiAuthError, match="HTML instead of JSON") as exc_info:
            await client.get("/test")
        assert exc_info.value.status_code == 200
        assert "auth/path mismatch" in str(exc_info.value)

    @respx.mock
    async def test_200_with_html_content_type_any_casing_caught(self, client):
        """Content-type header is case-insensitive; the sniff must lowercase before comparing."""
        respx.get(f"{BASE_URL}/test").mock(
            return_value=httpx.Response(200, content=b"<!DOCTYPE html>", headers={"content-type": "TEXT/HTML"})
        )
        with pytest.raises(UniFiAuthError):
            await client.get("/test")


class TestRetry:
    @respx.mock
    async def test_retries_on_connect_error_then_succeeds(self, client):
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.ConnectError("Connection refused"),
            httpx.Response(200, json={"ok": True}),
        ]
        result = await client.get("/test")
        assert result == {"ok": True}
        assert route.call_count == 2

    @respx.mock
    async def test_raises_connection_error_after_retries_exhausted(self, client):
        respx.get(f"{BASE_URL}/test").mock(side_effect=httpx.ConnectError("Connection refused"))
        with pytest.raises(UniFiConnectionError, match="Connection refused"):
            await client.get("/test")

    @respx.mock
    async def test_no_retry_on_auth_error(self, client):
        route = respx.get(f"{BASE_URL}/test").mock(return_value=httpx.Response(401, text="Unauthorized"))
        with pytest.raises(UniFiAuthError):
            await client.get("/test")
        assert route.call_count == 1

    @respx.mock
    async def test_timeout_on_get_is_retried(self, client):
        # GET is idempotent, so TimeoutException retries up to max_retries.
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.ReadTimeout("slow"),
            httpx.Response(200, json={"ok": True}),
        ]
        result = await client.get("/test")
        assert result == {"ok": True}
        assert route.call_count == 2

    @respx.mock
    async def test_timeout_on_post_is_not_retried(self, client):
        # POST is non-idempotent; a timeout must not be retried — the server
        # may have processed the write before the response was lost.
        route = respx.post(f"{BASE_URL}/test").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(UniFiTimeoutError):
            await client.post("/test", json={"x": 1})
        assert route.call_count == 1

    @respx.mock
    async def test_timeout_on_put_is_not_retried(self, client):
        route = respx.put(f"{BASE_URL}/test/1").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(UniFiTimeoutError):
            await client.put("/test/1", json={"x": 1})
        assert route.call_count == 1

    @respx.mock
    async def test_timeout_on_delete_is_not_retried(self, client):
        route = respx.delete(f"{BASE_URL}/test/1").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(UniFiTimeoutError):
            await client.delete("/test/1")
        assert route.call_count == 1

    @respx.mock
    async def test_connect_error_on_post_is_retried(self, client):
        # ConnectError is safe on every method — the request never reached the server.
        route = respx.post(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ]
        result = await client.post("/test", json={"x": 1})
        assert result == {"ok": True}
        assert route.call_count == 2

    @respx.mock
    async def test_retry_emits_warning_log_on_before_sleep(self, client, caplog):
        """A transient ConnectError followed by success must leave a WARNING
        log trail so operators debugging flaky controllers can see retries
        fired. Without ``before_sleep_log``, retries are invisible.
        """
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ]
        with caplog.at_level(logging.WARNING, logger="unifi_mcp.clients.base"):
            result = await client.get("/test")
        assert result == {"ok": True}
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, f"expected WARNING-level before_sleep log; got {caplog.records!r}"
        assert any("retrying" in r.getMessage().lower() for r in warnings), (
            f"expected a retry log; got messages: {[r.getMessage() for r in warnings]}"
        )


class TestRateLimitRetry:
    """Retry-After handling for idempotent 429 responses.

    Ubiquiti's integration API returns 429 with a Retry-After header when
    rate-limited. A single server-side retry removes the round-trip for
    transient bursts without surfacing the rate limit to the MCP client.
    """

    @respx.mock
    async def test_429_with_retry_after_on_get_is_retried_then_succeeds(self, client, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("unifi_mcp.clients.base.asyncio.sleep", fake_sleep)

        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.Response(429, text="rate limited", headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
        result = await client.get("/test")
        assert result == {"ok": True}
        assert route.call_count == 2
        assert slept == [2]

    @respx.mock
    async def test_429_without_retry_after_falls_back_to_one_second(self, client, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("unifi_mcp.clients.base.asyncio.sleep", fake_sleep)

        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json={"ok": True}),
        ]
        result = await client.get("/test")
        assert result == {"ok": True}
        assert slept == [1]

    @respx.mock
    async def test_429_retry_after_is_capped(self, client, monkeypatch):
        """An unreasonably large Retry-After must be capped so a single
        tool call doesn't block for many minutes."""
        from unifi_mcp.clients.base import _MAX_RETRY_AFTER_SECONDS

        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("unifi_mcp.clients.base.asyncio.sleep", fake_sleep)

        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.Response(429, text="rate limited", headers={"Retry-After": "3600"}),
            httpx.Response(200, json={"ok": True}),
        ]
        await client.get("/test")
        assert slept == [_MAX_RETRY_AFTER_SECONDS]

    @respx.mock
    async def test_429_on_post_is_not_retried(self, client):
        """POST is non-idempotent; retrying 429 risks double-execution if the
        server partially processed the request before rate-limiting.
        """
        from unifi_mcp.errors import UniFiRateLimitError

        route = respx.post(f"{BASE_URL}/test").mock(
            return_value=httpx.Response(429, text="rate limited", headers={"Retry-After": "1"})
        )
        with pytest.raises(UniFiRateLimitError):
            await client.post("/test", json={"x": 1})
        assert route.call_count == 1

    @respx.mock
    async def test_429_on_put_is_not_retried(self, client):
        from unifi_mcp.errors import UniFiRateLimitError

        route = respx.put(f"{BASE_URL}/test/1").mock(return_value=httpx.Response(429, text="rate limited"))
        with pytest.raises(UniFiRateLimitError):
            await client.put("/test/1", json={"x": 1})
        assert route.call_count == 1

    @respx.mock
    async def test_429_exhausts_retries_and_surfaces_rate_limit_error(self, client, monkeypatch):
        from unifi_mcp.errors import UniFiRateLimitError

        async def fake_sleep(seconds: float) -> None:
            pass

        monkeypatch.setattr("unifi_mcp.clients.base.asyncio.sleep", fake_sleep)

        # Client is configured with max_retries=2 in the fixture.
        route = respx.get(f"{BASE_URL}/test").mock(
            return_value=httpx.Response(429, text="rate limited", headers={"Retry-After": "1"})
        )
        with pytest.raises(UniFiRateLimitError, match="429"):
            await client.get("/test")
        # Bounded: initial request + max_retries retries.
        assert route.call_count == 1 + client._max_retries

    @respx.mock
    async def test_rate_limit_error_carries_retry_after(self, client):
        """The parsed Retry-After value is attached to the raised exception
        even on non-retried methods, so downstream logic (or the agent) can
        see how long to wait."""
        from unifi_mcp.errors import UniFiRateLimitError

        respx.post(f"{BASE_URL}/test").mock(
            return_value=httpx.Response(429, text="rate limited", headers={"Retry-After": "42"})
        )
        with pytest.raises(UniFiRateLimitError) as exc_info:
            await client.post("/test", json={"x": 1})
        assert exc_info.value.retry_after == 42
        assert exc_info.value.status_code == 429

    def test_parse_retry_after_handles_invalid_values(self, client):
        """Non-integer Retry-After values must not crash; return None."""
        assert client._parse_retry_after(None) is None
        assert client._parse_retry_after("") is None
        assert client._parse_retry_after("not-a-number") is None
        assert client._parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None  # HTTP-date form unsupported
        assert client._parse_retry_after("  5  ") == 5
        assert client._parse_retry_after("-3") == 0  # clamped non-negative


class TestPathPrefix:
    @respx.mock
    async def test_path_prefix_applied(self):
        client = _ConcreteClient(
            base_url=BASE_URL,
            api_key="key",
        )
        client._path_prefix = "/proxy/network/api/s/default/"
        respx.get(f"{BASE_URL}/proxy/network/api/s/default/stat/device").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        result = await client.get("stat/device")
        assert result == {"data": []}


class TestGetRaw:
    @respx.mock
    async def test_get_raw_returns_bytes(self, client):
        respx.get(f"{BASE_URL}/snap").mock(return_value=httpx.Response(200, content=b"\xff\xd8\xff\xe0"))
        result = await client.get_raw("/snap")
        assert result == b"\xff\xd8\xff\xe0"

    @respx.mock
    async def test_get_raw_with_max_bytes_under_cap_returns_full_body(self, client):
        payload = b"x" * 1024
        respx.get(f"{BASE_URL}/clip").mock(return_value=httpx.Response(200, content=payload))
        result = await client.get_raw("/clip", max_bytes=2048)
        assert result == payload

    @respx.mock
    async def test_get_raw_with_max_bytes_exceeded_raises(self, client):
        payload = b"x" * 2048
        respx.get(f"{BASE_URL}/clip").mock(return_value=httpx.Response(200, content=payload))
        with pytest.raises(UniFiError, match="max_bytes=1024"):
            await client.get_raw("/clip", max_bytes=1024)

    @respx.mock
    async def test_get_raw_streamed_raises_on_http_error(self, client):
        respx.get(f"{BASE_URL}/clip").mock(return_value=httpx.Response(404, text="Not Found"))
        with pytest.raises(UniFiNotFoundError):
            await client.get_raw("/clip", max_bytes=1024)

    @respx.mock
    async def test_get_raw_streaming_retries_connect_error(self, client):
        """The streaming branch must share the tenacity retry semantics of
        ``_request``: a transient ConnectError retries and succeeds on the
        second attempt.
        """
        route = respx.get(f"{BASE_URL}/clip")
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.Response(200, content=b"\xff\xd8\xff\xe0ok"),
        ]
        result = await client.get_raw("/clip", max_bytes=1024)
        assert result == b"\xff\xd8\xff\xe0ok"
        assert route.call_count == 2

    @respx.mock
    async def test_get_raw_streaming_maps_connect_error_when_retries_exhausted(self, client):
        """ConnectError after exhausted retries must surface as
        UniFiConnectionError, not a raw httpx exception that would fall
        through handle_client_error's 'Unexpected error' branch.
        """
        respx.get(f"{BASE_URL}/clip").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(UniFiConnectionError, match="refused"):
            await client.get_raw("/clip", max_bytes=1024)

    @respx.mock
    async def test_get_raw_streaming_maps_timeout(self, client):
        """ReadTimeout in the streaming path must map to UniFiTimeoutError."""
        respx.get(f"{BASE_URL}/clip").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(UniFiTimeoutError, match="slow"):
            await client.get_raw("/clip", max_bytes=1024)

    @respx.mock
    async def test_get_raw_streaming_does_not_retry_max_bytes_exceeded(self, client):
        """max_bytes exceeded is a deliberate abort, not transient — must not
        retry (tenacity only retries on Connect/Timeout).
        """
        payload = b"x" * 4096
        route = respx.get(f"{BASE_URL}/clip").mock(return_value=httpx.Response(200, content=payload))
        with pytest.raises(UniFiError, match="max_bytes=1024"):
            await client.get_raw("/clip", max_bytes=1024)
        assert route.call_count == 1


class TestClose:
    async def test_close_calls_aclose(self, client):
        await client.close()
        assert client._client.is_closed

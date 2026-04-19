"""Tests for the base UniFi API client."""

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


class TestClose:
    async def test_close_calls_aclose(self, client):
        await client.close()
        assert client._client.is_closed

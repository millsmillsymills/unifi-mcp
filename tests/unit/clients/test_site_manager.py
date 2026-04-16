"""Tests for the Site Manager API client."""

from __future__ import annotations

import httpx
import pytest
import respx

from unifi_mcp.clients.site_manager import SITE_MANAGER_BASE_URL, SiteManagerClient

API_PREFIX = f"{SITE_MANAGER_BASE_URL}/v1/"


@pytest.fixture
def client():
    return SiteManagerClient(
        api_key="test-sm-key",
        timeout=5,
        max_retries=2,
    )


class TestListHosts:
    @respx.mock
    async def test_list_hosts_calls_correct_endpoint(self, client):
        route = respx.get(f"{API_PREFIX}hosts").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "host-1", "name": "UDR Ultra"}]})
        )
        result = await client.list_hosts()
        assert route.called
        assert result == {"data": [{"id": "host-1", "name": "UDR Ultra"}]}

    @respx.mock
    async def test_list_hosts_sends_api_key_header(self, client):
        route = respx.get(f"{API_PREFIX}hosts").mock(return_value=httpx.Response(200, json={"data": []}))
        await client.list_hosts()
        assert route.calls[0].request.headers["X-API-Key"] == "test-sm-key"


class TestListSites:
    @respx.mock
    async def test_list_sites_calls_correct_endpoint(self, client):
        route = respx.get(f"{API_PREFIX}sites").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "site-1", "name": "Default"}]})
        )
        result = await client.list_sites()
        assert route.called
        assert result == {"data": [{"id": "site-1", "name": "Default"}]}


class TestListDevices:
    @respx.mock
    async def test_list_devices_without_host_id(self, client):
        route = respx.get(f"{API_PREFIX}devices").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "dev-1"}]})
        )
        result = await client.list_devices()
        assert route.called
        assert result == {"data": [{"id": "dev-1"}]}
        # No query params when host_id is None
        assert "hostId" not in str(route.calls[0].request.url.params)

    @respx.mock
    async def test_list_devices_with_host_id(self, client):
        route = respx.get(f"{API_PREFIX}devices").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "dev-1", "hostId": "host-1"}]})
        )
        result = await client.list_devices(host_id="host-1")
        assert route.called
        assert result == {"data": [{"id": "dev-1", "hostId": "host-1"}]}
        assert route.calls[0].request.url.params["hostId"] == "host-1"


class TestValidateConnection:
    @respx.mock
    async def test_validate_returns_true_on_success(self, client):
        respx.get(f"{API_PREFIX}hosts").mock(return_value=httpx.Response(200, json={"data": []}))
        result = await client.validate_connection()
        assert result is True

    @respx.mock
    async def test_validate_returns_false_on_failure(self, client):
        respx.get(f"{API_PREFIX}hosts").mock(return_value=httpx.Response(401, text="Unauthorized"))
        result = await client.validate_connection()
        assert result is False


class TestSSLVerification:
    def test_ssl_verification_is_enabled(self, client):
        # Site Manager uses a public cloud API, so SSL must be verified
        verify = client._client._transport._pool._ssl_context
        assert verify is not None


class TestPathPrefix:
    def test_path_prefix_is_v1(self, client):
        assert client._path_prefix == "/v1/"

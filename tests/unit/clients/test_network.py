"""Tests for the Network API client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.clients.network import NetworkClient

BASE_URL = "https://10.0.0.1:443"
SITE = "default"
API_PREFIX = f"{BASE_URL}/proxy/network/api/s/{SITE}/"

_fixtures_path = Path(__file__).resolve().parent.parent.parent / "fixtures" / "network_responses.json"
FIXTURES = json.loads(_fixtures_path.read_text())


@pytest.fixture
def client():
    return NetworkClient(
        base_url=BASE_URL,
        api_key="test-net-key",
        site=SITE,
        timeout=5,
        max_retries=2,
    )


class TestGetHealth:
    @respx.mock
    async def test_get_health_calls_correct_endpoint(self, client):
        route = respx.get(f"{API_PREFIX}stat/health").mock(return_value=httpx.Response(200, json=FIXTURES["health"]))
        result = await client.get_health()
        assert route.called
        assert result == FIXTURES["health"]


class TestListDevices:
    @respx.mock
    async def test_list_devices_calls_correct_endpoint(self, client):
        route = respx.get(f"{API_PREFIX}stat/device").mock(return_value=httpx.Response(200, json=FIXTURES["devices"]))
        result = await client.list_devices()
        assert route.called
        assert result == FIXTURES["devices"]


class TestListActiveClients:
    @respx.mock
    async def test_list_active_clients_calls_correct_endpoint(self, client):
        route = respx.get(f"{API_PREFIX}stat/sta").mock(return_value=httpx.Response(200, json=FIXTURES["clients"]))
        result = await client.list_active_clients()
        assert route.called
        assert result == FIXTURES["clients"]


class TestListWlans:
    @respx.mock
    async def test_list_wlans_calls_correct_endpoint(self, client):
        route = respx.get(f"{API_PREFIX}rest/wlanconf").mock(return_value=httpx.Response(200, json=FIXTURES["wlans"]))
        result = await client.list_wlans()
        assert route.called
        assert result == FIXTURES["wlans"]


class TestCreateWlan:
    @respx.mock
    async def test_create_wlan_sends_post_with_payload(self, client):
        payload = {"name": "GuestWiFi", "security": "wpapsk", "wpa_mode": "wpa2"}
        route = respx.post(f"{API_PREFIX}rest/wlanconf").mock(
            return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [payload]})
        )
        result = await client.create_wlan(payload)
        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body == payload
        assert result["data"][0]["name"] == "GuestWiFi"


class TestUpdateWlan:
    @respx.mock
    async def test_update_wlan_sends_put_with_correct_id(self, client):
        payload = {"name": "UpdatedWiFi"}
        route = respx.put(f"{API_PREFIX}rest/wlanconf/wlan1").mock(
            return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [payload]})
        )
        result = await client.update_wlan("wlan1", payload)
        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body == payload
        assert result["data"][0]["name"] == "UpdatedWiFi"


class TestDeleteWlan:
    @respx.mock
    async def test_delete_wlan_sends_delete_with_correct_id(self, client):
        route = respx.delete(f"{API_PREFIX}rest/wlanconf/wlan1").mock(
            return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
        )
        result = await client.delete_wlan("wlan1")
        assert route.called
        assert result["meta"]["rc"] == "ok"


class TestRestartDevice:
    @respx.mock
    async def test_restart_device_sends_correct_cmd_payload(self, client):
        route = respx.post(f"{API_PREFIX}cmd/devmgr").mock(
            return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
        )
        await client.restart_device("aa:bb:cc:dd:ee:01")
        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body == {"cmd": "restart", "mac": "aa:bb:cc:dd:ee:01"}


class TestBlockClient:
    @respx.mock
    async def test_block_client_sends_correct_cmd_payload(self, client):
        # block_client now pre-checks the MAC (#96), so mock both endpoints.
        mac = "aa:bb:cc:dd:ee:02"
        respx.get(f"{API_PREFIX}stat/alluser").mock(
            return_value=httpx.Response(200, json={"data": [{"mac": mac}]}),
        )
        route = respx.post(f"{API_PREFIX}cmd/stamgr").mock(
            return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
        )
        await client.block_client(mac)
        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body == {"cmd": "block-sta", "mac": mac}


class TestValidateConnection:
    @respx.mock
    async def test_validate_returns_true_on_success(self, client):
        respx.get(f"{API_PREFIX}stat/sysinfo").mock(return_value=httpx.Response(200, json=FIXTURES["sysinfo"]))
        result = await client.validate_connection()
        assert result is True

    @respx.mock
    async def test_validate_returns_false_on_connection_error(self, client):
        respx.get(f"{API_PREFIX}stat/sysinfo").mock(side_effect=httpx.ConnectError("Connection refused"))
        result = await client.validate_connection()
        assert result is False

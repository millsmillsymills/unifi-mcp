"""Per-method coverage for NetworkClient methods not covered in test_network.py (#72)."""

from __future__ import annotations

import httpx
import pytest
import respx

from unifi_mcp.clients.network import NetworkClient

BASE_URL = "https://10.0.0.1:443"
SITE = "default"
API_PREFIX = f"{BASE_URL}/proxy/network/api/s/{SITE}/"


@pytest.fixture
def client() -> NetworkClient:
    return NetworkClient(base_url=BASE_URL, api_key="test-key", site=SITE, timeout=5, max_retries=1)


class TestReadMethods:
    @respx.mock
    async def test_list_events_applies_limit(self, client):
        route = respx.get(f"{API_PREFIX}stat/event").mock(return_value=httpx.Response(200, json={"data": []}))
        await client.list_events(limit=50)
        assert route.calls[0].request.url.params["_limit"] == "50"

    @respx.mock
    async def test_list_devices_basic(self, client):
        respx.get(f"{API_PREFIX}stat/device-basic").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.list_devices_basic() == {"data": []}

    @respx.mock
    async def test_list_configured_clients(self, client):
        respx.get(f"{API_PREFIX}rest/user").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.list_configured_clients() == {"data": []}

    @respx.mock
    async def test_list_all_clients(self, client):
        route = respx.get(f"{API_PREFIX}stat/alluser").mock(return_value=httpx.Response(200, json={"data": []}))
        await client.list_all_clients()
        assert route.calls[0].request.url.params["type"] == "all"
        assert route.calls[0].request.url.params["conn"] == "all"

    @respx.mock
    async def test_get_dpi_stats(self, client):
        route = respx.get(f"{API_PREFIX}stat/dpi").mock(return_value=httpx.Response(200, json={"data": []}))
        await client.get_dpi_stats(dpi_type="by_cat")
        assert route.calls[0].request.url.params["type"] == "by_cat"

    @respx.mock
    async def test_get_sysinfo(self, client):
        respx.get(f"{API_PREFIX}stat/sysinfo").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.get_sysinfo() == {"data": []}

    @respx.mock
    async def test_get_wlan(self, client):
        respx.get(f"{API_PREFIX}rest/wlanconf/w-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.get_wlan("w-1") == {"data": []}

    @respx.mock
    async def test_list_networks(self, client):
        respx.get(f"{API_PREFIX}rest/networkconf").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.list_networks() == {"data": []}

    @respx.mock
    async def test_get_network(self, client):
        respx.get(f"{API_PREFIX}rest/networkconf/n-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.get_network("n-1") == {"data": []}

    @respx.mock
    async def test_list_firewall_rules(self, client):
        respx.get(f"{API_PREFIX}rest/firewallrule").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.list_firewall_rules() == {"data": []}

    @respx.mock
    async def test_get_firewall_rule(self, client):
        respx.get(f"{API_PREFIX}rest/firewallrule/r-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.get_firewall_rule("r-1") == {"data": []}

    @respx.mock
    async def test_list_firewall_groups(self, client):
        respx.get(f"{API_PREFIX}rest/firewallgroup").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.list_firewall_groups() == {"data": []}

    @respx.mock
    async def test_get_firewall_group(self, client):
        respx.get(f"{API_PREFIX}rest/firewallgroup/g-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.get_firewall_group("g-1") == {"data": []}

    @respx.mock
    async def test_list_port_forwards(self, client):
        respx.get(f"{API_PREFIX}rest/portforward").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.list_port_forwards() == {"data": []}

    @respx.mock
    async def test_get_port_forward(self, client):
        respx.get(f"{API_PREFIX}rest/portforward/pf-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.get_port_forward("pf-1") == {"data": []}

    @respx.mock
    async def test_list_routes(self, client):
        respx.get(f"{API_PREFIX}rest/routing").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.list_routes() == {"data": []}

    @respx.mock
    async def test_get_route(self, client):
        respx.get(f"{API_PREFIX}rest/routing/r-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.get_route("r-1") == {"data": []}

    @respx.mock
    async def test_get_settings(self, client):
        respx.get(f"{API_PREFIX}rest/setting").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await client.get_settings() == {"data": []}


class TestCrudMethods:
    @pytest.mark.parametrize(
        ("method_name", "endpoint", "verb"),
        [
            ("create_network", "rest/networkconf", "post"),
            ("create_firewall_rule", "rest/firewallrule", "post"),
            ("create_firewall_group", "rest/firewallgroup", "post"),
            ("create_port_forward", "rest/portforward", "post"),
            ("create_route", "rest/routing", "post"),
        ],
    )
    @respx.mock
    async def test_create_posts(self, client, method_name, endpoint, verb):
        route = getattr(respx, verb)(f"{API_PREFIX}{endpoint}").mock(return_value=httpx.Response(200, json={}))
        await getattr(client, method_name)({"name": "x"})
        assert route.call_count == 1
        assert b"name" in route.calls[0].request.content

    @pytest.mark.parametrize(
        ("method_name", "endpoint"),
        [
            ("update_network", "rest/networkconf"),
            ("update_firewall_rule", "rest/firewallrule"),
            ("update_firewall_group", "rest/firewallgroup"),
            ("update_port_forward", "rest/portforward"),
            ("update_route", "rest/routing"),
        ],
    )
    @respx.mock
    async def test_update_puts_with_id(self, client, method_name, endpoint):
        route = respx.put(f"{API_PREFIX}{endpoint}/abc").mock(return_value=httpx.Response(200, json={}))
        await getattr(client, method_name)("abc", {"enabled": False})
        assert route.call_count == 1

    @pytest.mark.parametrize(
        ("method_name", "endpoint"),
        [
            ("delete_network", "rest/networkconf"),
            ("delete_firewall_rule", "rest/firewallrule"),
            ("delete_firewall_group", "rest/firewallgroup"),
            ("delete_port_forward", "rest/portforward"),
            ("delete_route", "rest/routing"),
        ],
    )
    @respx.mock
    async def test_delete_returns_empty_on_204(self, client, method_name, endpoint):
        route = respx.delete(f"{API_PREFIX}{endpoint}/abc").mock(return_value=httpx.Response(204))
        assert await getattr(client, method_name)("abc") == {}
        assert route.call_count == 1

    @respx.mock
    async def test_update_settings(self, client):
        route = respx.put(f"{API_PREFIX}rest/setting").mock(return_value=httpx.Response(200, json={}))
        await client.update_settings({"enabled": True})
        assert route.call_count == 1


class TestCommandMethods:
    @pytest.mark.parametrize(
        ("method_name", "endpoint", "expected_cmd"),
        [
            ("run_speedtest", "cmd/devmgr", b"speedtest"),
            ("create_backup", "cmd/backup", b"backup"),
            ("archive_events", "cmd/evtmgr", b"archive-all-alarms"),
            ("reset_dpi", "cmd/stat", b"reset-dpi"),
        ],
    )
    @respx.mock
    async def test_no_arg_command(self, client, method_name, endpoint, expected_cmd):
        route = respx.post(f"{API_PREFIX}{endpoint}").mock(return_value=httpx.Response(200, json={}))
        await getattr(client, method_name)()
        assert expected_cmd in route.calls[0].request.content

    @pytest.mark.parametrize(
        ("method_name", "endpoint", "expected_cmd"),
        [
            ("adopt_device", "cmd/devmgr", b"adopt"),
            ("locate_device", "cmd/devmgr", b"set-locate"),
            ("unlocate_device", "cmd/devmgr", b"unset-locate"),
            ("provision_device", "cmd/devmgr", b"force-provision"),
            ("upgrade_device", "cmd/devmgr", b"upgrade"),
            ("unblock_client", "cmd/stamgr", b"unblock-sta"),
            ("kick_client", "cmd/stamgr", b"kick-sta"),
            ("unauthorize_guest", "cmd/stamgr", b"unauthorize-guest"),
        ],
    )
    @respx.mock
    async def test_mac_command(self, client, method_name, endpoint, expected_cmd):
        route = respx.post(f"{API_PREFIX}{endpoint}").mock(return_value=httpx.Response(200, json={}))
        await getattr(client, method_name)("aa:bb:cc:dd:ee:ff")
        body = route.calls[0].request.content
        assert expected_cmd in body
        assert b"aa:bb:cc:dd:ee:ff" in body

    @respx.mock
    async def test_power_cycle_port_sends_port_idx(self, client):
        route = respx.post(f"{API_PREFIX}cmd/devmgr").mock(return_value=httpx.Response(200, json={}))
        await client.power_cycle_port("aa:bb:cc:dd:ee:ff", 3)
        body = route.calls[0].request.content
        assert b"power-cycle" in body
        assert b'"port_idx":3' in body

    @respx.mock
    async def test_authorize_guest_sends_minutes(self, client):
        route = respx.post(f"{API_PREFIX}cmd/stamgr").mock(return_value=httpx.Response(200, json={}))
        await client.authorize_guest("aa:bb:cc:dd:ee:ff", minutes=90)
        body = route.calls[0].request.content
        assert b"authorize-guest" in body
        assert b"90" in body

"""Tests for Network firewall MCP tools (4 read + 6 write)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from unifi_mcp.clients.network import NetworkClient
from unifi_mcp.tools.network.firewall import register_firewall_tools

BASE_URL = "https://10.0.0.1:443"
SITE_PREFIX = f"{BASE_URL}/proxy/network/api/s/default"

READ_TOOL_NAMES = {
    "network_list_firewall_rules",
    "network_get_firewall_rule",
    "network_list_firewall_groups",
    "network_get_firewall_group",
}
WRITE_TOOL_NAMES = {
    "network_create_firewall_rule",
    "network_update_firewall_rule",
    "network_delete_firewall_rule",
    "network_create_firewall_group",
    "network_update_firewall_group",
    "network_delete_firewall_group",
}


@pytest.fixture
def network_client() -> NetworkClient:
    return NetworkClient(base_url=BASE_URL, api_key="test-key", site="default", timeout=5, max_retries=1)


@pytest.fixture
def mcp_with_firewall() -> FastMCP:
    server = FastMCP(name="test-firewall")
    register_firewall_tools(server)
    return server


class TestFirewallRegistration:
    async def test_all_tools_registered(self, mcp_with_firewall):
        tools = await mcp_with_firewall.list_tools()
        assert {t.name for t in tools} == READ_TOOL_NAMES | WRITE_TOOL_NAMES

    @pytest.mark.parametrize(
        "destructive_tool",
        ["network_delete_firewall_rule", "network_delete_firewall_group"],
    )
    async def test_delete_tools_marked_destructive(self, mcp_with_firewall, destructive_tool):
        tools = await mcp_with_firewall.list_tools()
        tool = next(t for t in tools if t.name == destructive_tool)
        assert tool.annotations.destructiveHint is True


class TestFirewallClientEndpoints:
    @respx.mock
    async def test_list_firewall_rules(self, network_client):
        respx.get(f"{SITE_PREFIX}/rest/firewallrule").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await network_client.list_firewall_rules() == {"data": []}

    @respx.mock
    async def test_get_firewall_rule(self, network_client):
        respx.get(f"{SITE_PREFIX}/rest/firewallrule/r-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await network_client.get_firewall_rule("r-1") == {"data": []}

    @respx.mock
    async def test_list_firewall_groups(self, network_client):
        respx.get(f"{SITE_PREFIX}/rest/firewallgroup").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await network_client.list_firewall_groups() == {"data": []}

    @respx.mock
    async def test_get_firewall_group(self, network_client):
        respx.get(f"{SITE_PREFIX}/rest/firewallgroup/g-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await network_client.get_firewall_group("g-1") == {"data": []}

    @respx.mock
    async def test_create_firewall_rule(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/rest/firewallrule").mock(return_value=httpx.Response(200, json={}))
        await network_client.create_firewall_rule({"name": "block-bad-ip", "action": "drop"})
        assert b"block-bad-ip" in route.calls[0].request.content

    @respx.mock
    async def test_update_firewall_rule(self, network_client):
        route = respx.put(f"{SITE_PREFIX}/rest/firewallrule/r-1").mock(return_value=httpx.Response(200, json={}))
        await network_client.update_firewall_rule("r-1", {"enabled": False})
        assert b"enabled" in route.calls[0].request.content

    @respx.mock
    async def test_delete_firewall_rule(self, network_client):
        route = respx.delete(f"{SITE_PREFIX}/rest/firewallrule/r-1").mock(return_value=httpx.Response(204))
        assert await network_client.delete_firewall_rule("r-1") == {}
        assert route.call_count == 1

    @respx.mock
    async def test_create_firewall_group(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/rest/firewallgroup").mock(return_value=httpx.Response(200, json={}))
        await network_client.create_firewall_group({"name": "bad-ips", "group_type": "address-group"})
        assert b"bad-ips" in route.calls[0].request.content

    @respx.mock
    async def test_delete_firewall_group(self, network_client):
        route = respx.delete(f"{SITE_PREFIX}/rest/firewallgroup/g-1").mock(return_value=httpx.Response(204))
        assert await network_client.delete_firewall_group("g-1") == {}
        assert route.call_count == 1

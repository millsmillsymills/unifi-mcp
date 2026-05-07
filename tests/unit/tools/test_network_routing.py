"""Tests for Network static-route MCP tools (2 read + 3 write)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from unifi_mcp.clients.network import NetworkClient
from unifi_mcp.tools.network.routing import register_routing_tools

BASE_URL = "https://10.0.0.1:443"
SITE_PREFIX = f"{BASE_URL}/proxy/network/api/s/default"

ALL_TOOLS = {
    "unifi_network_list_routes",
    "unifi_network_get_route",
    "unifi_network_create_route",
    "unifi_network_update_route",
    "unifi_network_delete_route",
}


@pytest.fixture
def network_client() -> NetworkClient:
    return NetworkClient(base_url=BASE_URL, api_key="test-key", site="default", timeout=5, max_retries=1)


@pytest.fixture
def mcp_with_routing() -> FastMCP:
    server = FastMCP(name="test-routing")
    register_routing_tools(server)
    return server


class TestRoutingRegistration:
    async def test_all_tools_registered(self, mcp_with_routing):
        tools = await mcp_with_routing.list_tools()
        assert {t.name for t in tools} == ALL_TOOLS

    async def test_delete_marked_destructive(self, mcp_with_routing):
        tools = await mcp_with_routing.list_tools()
        tool = next(t for t in tools if t.name == "unifi_network_delete_route")
        assert tool.annotations.destructiveHint is True


class TestRoutingClientEndpoints:
    @respx.mock
    async def test_list_routes(self, network_client):
        respx.get(f"{SITE_PREFIX}/rest/routing").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await network_client.list_routes() == {"data": []}

    @respx.mock
    async def test_get_route(self, network_client):
        respx.get(f"{SITE_PREFIX}/rest/routing/r-1").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await network_client.get_route("r-1") == {"data": []}

    @respx.mock
    async def test_create_route(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/rest/routing").mock(return_value=httpx.Response(200, json={}))
        await network_client.create_route({"name": "to-10", "gateway_ip": "10.0.0.254"})
        assert b"to-10" in route.calls[0].request.content

    @respx.mock
    async def test_update_route(self, network_client):
        route = respx.put(f"{SITE_PREFIX}/rest/routing/r-1").mock(return_value=httpx.Response(200, json={}))
        await network_client.update_route("r-1", {"enabled": False})
        assert b"enabled" in route.calls[0].request.content

    @respx.mock
    async def test_delete_route(self, network_client):
        route = respx.delete(f"{SITE_PREFIX}/rest/routing/r-1").mock(return_value=httpx.Response(204))
        assert await network_client.delete_route("r-1") == {}
        assert route.call_count == 1

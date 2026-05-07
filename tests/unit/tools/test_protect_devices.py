"""Tests for Protect accessory-device MCP tools (4 read-only)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from unifi_mcp.clients.protect import ProtectClient
from unifi_mcp.tools.protect.devices import register_protect_device_tools

BASE_URL = "https://10.0.0.1:443"
PROTECT_PREFIX = f"{BASE_URL}/proxy/protect/integration/v1"

TOOL_NAMES = {
    "unifi_protect_list_chimes",
    "unifi_protect_list_lights",
    "unifi_protect_list_sensors",
    "unifi_protect_list_viewers",
}


@pytest.fixture
def protect_client_local() -> ProtectClient:
    return ProtectClient(base_url=BASE_URL, api_key="test-key", timeout=5, max_retries=1)


@pytest.fixture
def mcp_with_accessories() -> FastMCP:
    server = FastMCP(name="test-accessories")
    register_protect_device_tools(server)
    return server


class TestProtectDeviceRegistration:
    async def test_all_tools_registered(self, mcp_with_accessories):
        tools = await mcp_with_accessories.list_tools()
        assert {t.name for t in tools} == TOOL_NAMES

    async def test_all_tools_are_read_only(self, mcp_with_accessories):
        tools = await mcp_with_accessories.list_tools()
        for tool in tools:
            assert "write" not in tool.tags


class TestProtectDeviceClientEndpoints:
    @pytest.mark.parametrize(
        ("method_name", "endpoint"),
        [
            ("list_chimes", "chimes"),
            ("list_lights", "lights"),
            ("list_sensors", "sensors"),
            ("list_viewers", "viewers"),
        ],
    )
    @respx.mock
    async def test_endpoint(self, protect_client_local, method_name, endpoint):
        payload = [{"id": "dev-1"}]
        respx.get(f"{PROTECT_PREFIX}/{endpoint}").mock(return_value=httpx.Response(200, json=payload))
        result = await getattr(protect_client_local, method_name)()
        assert result == payload

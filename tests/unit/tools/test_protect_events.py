"""Tests for Protect event MCP tools (1 read)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from unifi_mcp.clients.protect import ProtectClient
from unifi_mcp.tools.protect.events import register_event_tools

BASE_URL = "https://10.0.0.1:443"
PROTECT_PREFIX = f"{BASE_URL}/proxy/protect/api"


@pytest.fixture
def protect_client_local() -> ProtectClient:
    return ProtectClient(base_url=BASE_URL, api_key="test-key", timeout=5, max_retries=1)


@pytest.fixture
def mcp_with_events() -> FastMCP:
    server = FastMCP(name="test-events")
    register_event_tools(server)
    return server


class TestEventRegistration:
    async def test_tool_registered(self, mcp_with_events):
        tools = await mcp_with_events.list_tools()
        assert {t.name for t in tools} == {"protect_list_events"}

    async def test_tool_is_read_only(self, mcp_with_events):
        tools = await mcp_with_events.list_tools()
        assert "write" not in tools[0].tags


class TestEventClientEndpoints:
    @respx.mock
    async def test_list_events_with_defaults(self, protect_client_local):
        route = respx.get(f"{PROTECT_PREFIX}/events").mock(return_value=httpx.Response(200, json=[]))
        result = await protect_client_local.list_events()
        assert result == []
        params = route.calls[0].request.url.params
        assert params["limit"] == "30"
        assert params["offset"] == "0"

    @respx.mock
    async def test_list_events_with_filters(self, protect_client_local):
        route = respx.get(f"{PROTECT_PREFIX}/events").mock(return_value=httpx.Response(200, json=[]))
        await protect_client_local.list_events(
            start="2026-01-01T00:00:00Z",
            end="2026-01-02T00:00:00Z",
            camera_ids=["cam-1", "cam-2"],
            types=["motion", "ring"],
            smart_detect_types=["person", "vehicle"],
            limit=50,
            offset=10,
        )
        params = route.calls[0].request.url.params
        assert params["start"] == "2026-01-01T00:00:00Z"
        assert params["end"] == "2026-01-02T00:00:00Z"
        assert params["cameras"] == "cam-1,cam-2"
        assert params["types"] == "motion,ring"
        assert params["smartDetectTypes"] == "person,vehicle"
        assert params["limit"] == "50"
        assert params["offset"] == "10"

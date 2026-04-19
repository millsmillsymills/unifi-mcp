"""Tests for Network system/command MCP tools (1 read + 8 write)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from unifi_mcp.clients.network import NetworkClient
from unifi_mcp.tools.network.system import register_system_tools

BASE_URL = "https://10.0.0.1:443"
SITE_PREFIX = f"{BASE_URL}/proxy/network/api/s/default"

READ_TOOL_NAMES = {"network_get_settings"}
WRITE_TOOL_NAMES = {
    "network_update_settings",
    "network_run_speedtest",
    "network_create_backup",
    "network_upgrade_device",
    "network_power_cycle_port",
    "network_unauthorize_guest",
    "network_archive_events",
    "network_reset_dpi",
}


@pytest.fixture
def network_client() -> NetworkClient:
    return NetworkClient(base_url=BASE_URL, api_key="test-key", site="default", timeout=5, max_retries=1)


@pytest.fixture
def mcp_with_system() -> FastMCP:
    server = FastMCP(name="test-system")
    register_system_tools(server)
    return server


class TestSystemToolRegistration:
    async def test_all_tools_registered(self, mcp_with_system):
        tools = await mcp_with_system.list_tools()
        assert {t.name for t in tools} == READ_TOOL_NAMES | WRITE_TOOL_NAMES

    @pytest.mark.parametrize(
        "tool_name",
        [
            # Destructive per #49/#50.
            "network_upgrade_device",
            "network_power_cycle_port",
            # Archive-events + reset-dpi both discard state.
            "network_archive_events",
            "network_reset_dpi",
        ],
    )
    async def test_destructive_writes_flagged(self, mcp_with_system, tool_name):
        tools = await mcp_with_system.list_tools()
        tool = next(t for t in tools if t.name == tool_name)
        assert tool.annotations.destructiveHint is True


class TestSystemCommandEndpoints:
    @respx.mock
    async def test_get_settings(self, network_client):
        respx.get(f"{SITE_PREFIX}/rest/setting").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await network_client.get_settings() == {"data": []}

    @respx.mock
    async def test_run_speedtest_posts_cmd_devmgr(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/cmd/devmgr").mock(return_value=httpx.Response(200, json={}))
        await network_client.run_speedtest()
        assert b"speedtest" in route.calls[0].request.content

    @respx.mock
    async def test_create_backup_posts_cmd_backup(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/cmd/backup").mock(return_value=httpx.Response(200, json={}))
        await network_client.create_backup()
        assert b"backup" in route.calls[0].request.content

    @respx.mock
    async def test_upgrade_device_posts_cmd_devmgr(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/cmd/devmgr").mock(return_value=httpx.Response(200, json={}))
        await network_client.upgrade_device("aa:bb:cc:dd:ee:ff")
        body = route.calls[0].request.content
        assert b"upgrade" in body
        assert b"aa:bb:cc:dd:ee:ff" in body

    @respx.mock
    async def test_power_cycle_port_posts_port_idx(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/cmd/devmgr").mock(return_value=httpx.Response(200, json={}))
        await network_client.power_cycle_port("aa:bb:cc:dd:ee:ff", 5)
        body = route.calls[0].request.content
        assert b"power-cycle" in body
        assert b'"port_idx":5' in body

    @respx.mock
    async def test_archive_events(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/cmd/evtmgr").mock(return_value=httpx.Response(200, json={}))
        await network_client.archive_events()
        assert b"archive-all-alarms" in route.calls[0].request.content

    @respx.mock
    async def test_reset_dpi(self, network_client):
        route = respx.post(f"{SITE_PREFIX}/cmd/stat").mock(return_value=httpx.Response(200, json={}))
        await network_client.reset_dpi()
        assert b"reset-dpi" in route.calls[0].request.content

    @respx.mock
    async def test_update_settings_puts_rest_setting(self, network_client):
        route = respx.put(f"{SITE_PREFIX}/rest/setting").mock(return_value=httpx.Response(200, json={}))
        await network_client.update_settings({"enabled": True})
        assert route.call_count == 1

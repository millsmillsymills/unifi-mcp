"""Read-mode tools must redact secrets before returning to the agent (#146)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from unifi_mcp._redaction import REDACTED
from unifi_mcp.config import UniFiConfig, UniFiMode
from unifi_mcp.tools.network.clients import register_client_tools
from unifi_mcp.tools.network.system import register_system_tools
from unifi_mcp.tools.network.wlan import register_wlan_tools
from unifi_mcp.tools.protect.nvr import register_nvr_tools


@dataclass
class FakeLifespan:
    config: UniFiConfig
    clients: dict[str, Any] = field(default_factory=dict)


def _readonly_config() -> UniFiConfig:
    return UniFiConfig(
        _env_file=None,
        unifi_mode=UniFiMode.READONLY,
        unifi_network_api="k",
        unifi_protect_api="k",
        unifi_site_manager_api=None,
    )


def _fake_ctx(**clients: Any) -> AsyncMock:
    ctx = AsyncMock()
    ctx.lifespan_context = FakeLifespan(config=_readonly_config(), clients=clients)
    return ctx


async def _call(server: FastMCP, tool_name: str, ctx: AsyncMock, **kwargs: Any) -> Any:
    tool = await server.get_tool(tool_name)
    return await tool.fn(ctx, **kwargs)


class TestNetworkWlanRedaction:
    @pytest.fixture
    def server(self) -> FastMCP:
        s = FastMCP(name="t")
        register_wlan_tools(s)
        return s

    async def test_list_wlans_redacts_psk_in_payload(self, server):
        network_client = AsyncMock()
        network_client.list_wlans = AsyncMock(
            return_value={"data": [{"name": "Home", "x_passphrase": "secret"}]},
        )
        ctx = _fake_ctx(network=network_client)
        result = await _call(server, "unifi_network_list_wlans", ctx)
        assert result["data"][0]["x_passphrase"] == REDACTED
        assert result["data"][0]["name"] == "Home"

    async def test_get_wlan_redacts_radius_secret(self, server):
        network_client = AsyncMock()
        network_client.get_wlan = AsyncMock(
            return_value={"_id": "w-1", "radius_secret": "r-sec", "name": "Corp"},
        )
        ctx = _fake_ctx(network=network_client)
        result = await _call(server, "unifi_network_get_wlan", ctx, wlan_id="w-1")
        assert result["radius_secret"] == REDACTED
        assert result["name"] == "Corp"


class TestNetworkSystemRedaction:
    @pytest.fixture
    def server(self) -> FastMCP:
        s = FastMCP(name="t")
        register_system_tools(s)
        return s

    async def test_get_settings_redacts_smtp_and_super_url(self, server):
        network_client = AsyncMock()
        network_client.get_settings = AsyncMock(
            return_value={
                "data": [
                    {
                        "key": "smtp",
                        "x_password": "smtp-pw",
                        "password": "raw",
                        "super_smtp_password": "super-pw",
                        "super_mgmt_url": "https://attacker.example/cb",
                        "name": "alerts",
                    }
                ]
            },
        )
        ctx = _fake_ctx(network=network_client)
        result = await _call(server, "unifi_network_get_settings", ctx)
        row = result["data"][0]
        assert row["x_password"] == REDACTED
        assert row["password"] == REDACTED
        assert row["super_smtp_password"] == REDACTED
        assert row["super_mgmt_url"] == REDACTED
        assert row["name"] == "alerts"


class TestNetworkClientsRedaction:
    @pytest.fixture
    def server(self) -> FastMCP:
        s = FastMCP(name="t")
        register_client_tools(s)
        return s

    async def test_get_client_redacts_token_in_returned_record(self, server):
        network_client = AsyncMock()
        network_client.list_active_clients = AsyncMock(
            return_value={
                "data": [
                    {"mac": "aa:bb:cc:dd:ee:01", "name": "Other", "token": "shouldnt"},
                    {"mac": "aa:bb:cc:dd:ee:02", "name": "Mine", "token": "secret-tok"},
                ]
            },
        )
        ctx = _fake_ctx(network=network_client)
        result = await _call(server, "unifi_network_get_client", ctx, mac="AA:BB:CC:DD:EE:02")
        assert result["token"] == REDACTED
        assert result["name"] == "Mine"


class TestProtectNvrRedaction:
    @pytest.fixture
    def server(self) -> FastMCP:
        s = FastMCP(name="t")
        register_nvr_tools(s)
        return s

    async def test_get_nvr_redacts_sso_token(self, server):
        protect_client = AsyncMock()
        protect_client.get_nvr = AsyncMock(
            return_value={"id": "nvr-1", "ssoToken": "tok", "name": "CloudKey"},
        )
        ctx = _fake_ctx(protect=protect_client)
        result = await _call(server, "unifi_protect_get_nvr", ctx)
        assert result["ssoToken"] == REDACTED
        assert result["name"] == "CloudKey"

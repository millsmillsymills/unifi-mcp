"""Shared test fixtures for unifi-mcp."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from unifi_mcp.clients.network import NetworkClient
from unifi_mcp.clients.protect import ProtectClient
from unifi_mcp.clients.site_manager import SITE_MANAGER_BASE_URL, SiteManagerClient
from unifi_mcp.config import UniFiConfig, UniFiMode


@dataclass
class FakeLifespanContext:
    """Stand-in for ServerContext when exercising tool handlers outside a real lifespan."""

    clients: dict[str, Any] = field(default_factory=dict)
    config: UniFiConfig | None = None


@pytest.fixture
def readonly_config() -> UniFiConfig:
    """A UniFiConfig with all three APIs configured and UNIFI_MODE=readonly."""
    return UniFiConfig(
        _env_file=None,
        unifi_mode=UniFiMode.READONLY,
        unifi_network_api="test-net-key",
        unifi_protect_api="test-prot-key",
        unifi_site_manager_api="test-sm-key",
    )


@pytest.fixture
def readwrite_config() -> UniFiConfig:
    """A UniFiConfig with all three APIs configured and UNIFI_MODE=readwrite."""
    return UniFiConfig(
        _env_file=None,
        unifi_mode=UniFiMode.READWRITE,
        unifi_network_api="test-net-key",
        unifi_protect_api="test-prot-key",
        unifi_site_manager_api="test-sm-key",
    )


@pytest.fixture
def network_client() -> NetworkClient:
    """A NetworkClient pointed at a synthetic controller URL for respx-based tests."""
    return NetworkClient(
        base_url="https://10.0.0.1:443",
        api_key="test-net-key",
        site="default",
        timeout=5,
        max_retries=1,
    )


@pytest.fixture
def protect_client() -> ProtectClient:
    """A ProtectClient pointed at a synthetic controller URL for respx-based tests."""
    return ProtectClient(
        base_url="https://10.0.0.1:443",
        api_key="test-prot-key",
        timeout=5,
        max_retries=1,
    )


@pytest.fixture
def site_manager_client() -> SiteManagerClient:
    """A SiteManagerClient (base URL is fixed to the UniFi cloud API)."""
    return SiteManagerClient(api_key="test-sm-key", timeout=5, max_retries=1)


SITE_MANAGER_API_PREFIX = f"{SITE_MANAGER_BASE_URL}/v1/"


def build_fake_ctx(config: UniFiConfig, **clients: Any) -> AsyncMock:
    """Build a fake Context with the given config and named clients."""
    ctx = AsyncMock()
    ctx.lifespan_context = FakeLifespanContext(clients=dict(clients), config=config)
    return ctx


@pytest.fixture
def mcp_server() -> FastMCP:
    """A bare FastMCP server for tests that just need a namespace to register tools on."""
    return FastMCP(name="test-server")

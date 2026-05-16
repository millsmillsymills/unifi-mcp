"""Concurrent tool-call coverage for the §4 gap inventoried in #97.

Exercises ``asyncio.gather`` over registered MCP tool handlers (one layer up
from ``test_base.py``'s pool-level concurrency) to prove that:

1. Independent tool invocations against the same client return independent
   payloads (no response interleaving).
2. The same tool invoked N times concurrently returns N coherent results.
3. Mixed-API concurrency (Network + Protect in the same ``gather``) returns
   coherent results when both clients are configured.
4. A failing tool in a ``gather`` propagates its ``ToolError`` without
   corrupting sibling results (``return_exceptions=True``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from unifi_mcp.config import UniFiConfig, UniFiMode
from unifi_mcp.tools.network.devices import register_device_tools
from unifi_mcp.tools.network.stats import register_stats_tools
from unifi_mcp.tools.protect.cameras import register_camera_tools


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


def _fake_ctx(config: UniFiConfig, **clients: Any) -> AsyncMock:
    ctx = AsyncMock()
    ctx.lifespan_context = FakeLifespan(config=config, clients=clients)
    return ctx


async def _call(server: FastMCP, tool_name: str, ctx: AsyncMock, **kwargs: Any) -> Any:
    tool = await server.get_tool(tool_name)
    return await tool.fn(ctx, **kwargs)


@pytest.fixture
def network_server() -> FastMCP:
    server = FastMCP(name="t-net-concurrent")
    register_stats_tools(server)
    register_device_tools(server)
    return server


@pytest.fixture
def mixed_server() -> FastMCP:
    server = FastMCP(name="t-mixed-concurrent")
    register_stats_tools(server)
    register_device_tools(server)
    register_camera_tools(server)
    return server


class TestConcurrentToolCalls:
    """Tool-layer ``asyncio.gather`` coverage — closes #97 §4."""

    async def test_two_distinct_read_tools_return_independent_results(self, network_server):
        """Two different Network read tools invoked concurrently against the
        same mocked client must each receive their own payload — no bleed."""
        network = AsyncMock()
        network.get_health.return_value = {"data": "health-payload"}
        network.list_events.return_value = {"data": ["event-payload"]}
        ctx = _fake_ctx(_readonly_config(), network=network)

        health, events = await asyncio.gather(
            _call(network_server, "unifi_network_get_health", ctx),
            _call(network_server, "unifi_network_list_events", ctx, limit=5),
        )

        assert health == {"data": "health-payload"}
        assert events == {"data": ["event-payload"]}
        network.get_health.assert_awaited_once()
        network.list_events.assert_awaited_once_with(limit=5)

    async def test_same_tool_invoked_ten_times_concurrently(self, network_server):
        """The same read tool dispatched N times concurrently must return N
        coherent results — proving the handler is re-entrant under the
        shared pooled ``AsyncClient``."""
        network = AsyncMock()
        network.get_health.return_value = {"data": "ok"}
        ctx = _fake_ctx(_readonly_config(), network=network)

        results = await asyncio.gather(*[_call(network_server, "unifi_network_get_health", ctx) for _ in range(10)])

        assert len(results) == 10
        assert all(r == {"data": "ok"} for r in results)
        assert network.get_health.await_count == 10

    async def test_mixed_network_and_protect_tools_concurrent(self, mixed_server):
        """A ``gather`` spanning Network + Protect tools must route each call
        to the right client and return both payloads independently."""
        network = AsyncMock()
        network.get_health.return_value = {"data": "net-health"}
        protect = AsyncMock()
        protect.list_cameras.return_value = [{"id": "cam-1"}]
        ctx = _fake_ctx(_readonly_config(), network=network, protect=protect)

        net_result, protect_result = await asyncio.gather(
            _call(mixed_server, "unifi_network_get_health", ctx),
            _call(mixed_server, "unifi_protect_list_cameras", ctx),
        )

        assert net_result == {"data": "net-health"}
        assert protect_result == [{"id": "cam-1"}]
        network.get_health.assert_awaited_once()
        protect.list_cameras.assert_awaited_once()

    async def test_failure_in_gather_does_not_corrupt_siblings(self, network_server):
        """``return_exceptions=True`` over a ``gather`` containing a failing
        tool must surface the ``ToolError`` for the failing call while the
        successful sibling still returns its real payload."""
        network = AsyncMock()
        network.get_health.return_value = {"data": "still-good"}
        network.list_devices.return_value = {"data": []}
        ctx = _fake_ctx(_readonly_config(), network=network)

        good, bad = await asyncio.gather(
            _call(network_server, "unifi_network_get_health", ctx),
            _call(network_server, "unifi_network_get_device", ctx, mac="aa:bb:cc:dd:ee:ff"),
            return_exceptions=True,
        )

        assert good == {"data": "still-good"}
        assert isinstance(bad, ToolError)
        assert "not found" in str(bad).lower()
        network.get_health.assert_awaited_once()
        network.list_devices.assert_awaited_once()

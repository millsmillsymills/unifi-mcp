"""Concurrent tool-call coverage for the §4 gap inventoried in #97.

Exercises ``asyncio.gather`` over registered MCP tool handlers (one layer up
from ``test_base.py``'s pool-level concurrency) to prove that:

1. Independent tool invocations against the same client return independent
   payloads (routing per-call holds).
2. The same tool invoked N times concurrently genuinely interleaves at the
   event loop — a serialising regression (e.g. an accidental global lock
   around the client call) would push max-in-flight to 1 and fail the test.
3. Mixed-API concurrency (Network + Protect in the same ``gather``) returns
   coherent results when both clients are configured.
4. A failing tool in a ``gather`` propagates its ``ToolError`` without
   corrupting sibling results (``return_exceptions=True``).
5. ``redact_secrets`` is safe under concurrent invocation against a shared
   upstream payload — every returned dict is redacted *and* the upstream
   object the mock holds is left untouched (no aliasing / shared mutation).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from unifi_mcp._redaction import REDACTED
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
        """N=10 concurrent invocations must genuinely interleave at the event
        loop. The mocked client yields with ``asyncio.sleep(0)`` so each call
        parks before returning; a shared in-flight counter then proves all 10
        coroutines were simultaneously past the suspension point. A handler
        regression that serialises the client call (e.g. a global lock) would
        cap ``max_in_flight`` at 1 and fail the assertion."""
        in_flight = 0
        max_in_flight = 0

        async def _get_health_yielding() -> dict[str, str]:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1
            return {"data": "ok"}

        network = AsyncMock()
        network.get_health.side_effect = _get_health_yielding
        ctx = _fake_ctx(_readonly_config(), network=network)

        results = await asyncio.gather(*[_call(network_server, "unifi_network_get_health", ctx) for _ in range(10)])

        assert len(results) == 10
        assert all(r == {"data": "ok"} for r in results)
        assert network.get_health.await_count == 10
        assert max_in_flight == 10, f"expected real concurrency; max_in_flight={max_in_flight}"
        assert in_flight == 0

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

    async def test_redaction_under_concurrency_does_not_alias_upstream(self, mixed_server):
        """``redact_secrets`` must produce independent, fully-redacted results
        for every concurrent caller *without* mutating the upstream payload
        the client holds. Each of N concurrent ``list_cameras`` calls receives
        the same in-memory list-of-dicts; the test asserts (a) every returned
        camera has its ``x_passphrase`` replaced with ``REDACTED``, and (b)
        the original list the mock points at still carries the cleartext
        secret — i.e. the redaction path deep-copies and does not alias."""
        upstream_secret = "super-secret-psk"  # noqa: S105 — test fixture, not a real credential
        cameras = [{"id": "cam-1", "x_passphrase": upstream_secret, "name": "front-door"}]
        protect = AsyncMock()
        protect.list_cameras.return_value = cameras
        ctx = _fake_ctx(_readonly_config(), protect=protect)

        results = await asyncio.gather(*[_call(mixed_server, "unifi_protect_list_cameras", ctx) for _ in range(5)])

        assert len(results) == 5
        for batch in results:
            assert len(batch) == 1
            cam = batch[0]
            assert cam["x_passphrase"] == REDACTED
            assert cam["id"] == "cam-1"
            assert cam["name"] == "front-door"
        assert cameras[0]["x_passphrase"] == upstream_secret, (
            "redact_secrets aliased the upstream payload — concurrent callers can leak each other's mutations"
        )
        assert protect.list_cameras.await_count == 5

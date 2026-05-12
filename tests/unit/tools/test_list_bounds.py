"""Tool-layer caps on list-style parameters (#151).

Read tools that accept ``limit`` or ``offset`` must refuse values outside the
configured maximum so a prompt-injected agent cannot request unbounded pages
of data from the controller. The ceiling lives on the config object so an
operator can dial it down without code changes, but the agent surface is
strictly bounded by ``unifi_max_list_items`` / ``unifi_max_list_offset``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from unifi_mcp.config import UniFiConfig, UniFiMode
from unifi_mcp.tools.network.stats import register_stats_tools


@dataclass
class _Lifespan:
    config: UniFiConfig
    clients: dict[str, Any] = field(default_factory=dict)


def _config(max_items: int = 1000) -> UniFiConfig:
    return UniFiConfig(
        _env_file=None,
        unifi_mode=UniFiMode.READONLY,
        unifi_network_api="k",
        unifi_protect_api=None,
        unifi_site_manager_api=None,
        unifi_max_list_items=max_items,
    )


def _ctx(config: UniFiConfig, client: AsyncMock) -> AsyncMock:
    ctx = AsyncMock()
    ctx.lifespan_context = _Lifespan(config=config, clients={"network": client})
    return ctx


@pytest.fixture
def server() -> FastMCP:
    s = FastMCP(name="t")
    register_stats_tools(s)
    return s


async def _call(server: FastMCP, tool_name: str, ctx: AsyncMock, **kwargs: Any) -> Any:
    tool = await server.get_tool(tool_name)
    return await tool.fn(ctx, **kwargs)


class TestListEventsLimitBound:
    """``unifi_network_list_events`` caps ``limit`` at ``unifi_max_list_items``."""

    async def test_within_cap_passes_through(self, server):
        client = AsyncMock()
        client.list_events.return_value = {"data": []}
        ctx = _ctx(_config(), client)
        await _call(server, "unifi_network_list_events", ctx, limit=500)
        client.list_events.assert_awaited_once_with(limit=500)

    async def test_at_cap_passes_through(self, server):
        client = AsyncMock()
        client.list_events.return_value = {"data": []}
        ctx = _ctx(_config(max_items=1000), client)
        await _call(server, "unifi_network_list_events", ctx, limit=1000)
        client.list_events.assert_awaited_once_with(limit=1000)

    async def test_above_cap_raises_bad_request(self, server):
        client = AsyncMock()
        ctx = _ctx(_config(max_items=1000), client)
        with pytest.raises(ToolError, match="limit must be between 1 and 1000"):
            await _call(server, "unifi_network_list_events", ctx, limit=10_000)
        client.list_events.assert_not_called()

    async def test_zero_limit_rejected(self, server):
        client = AsyncMock()
        ctx = _ctx(_config(), client)
        with pytest.raises(ToolError, match="limit must be between 1"):
            await _call(server, "unifi_network_list_events", ctx, limit=0)

    async def test_negative_limit_rejected(self, server):
        client = AsyncMock()
        ctx = _ctx(_config(), client)
        with pytest.raises(ToolError, match="limit must be between 1"):
            await _call(server, "unifi_network_list_events", ctx, limit=-5)

    async def test_operator_lowered_cap_enforced(self, server):
        """An operator who lowers ``unifi_max_list_items`` to 100 must see
        ``limit=500`` rejected — the cap is a configuration knob, not a
        constant tied to the upstream API.
        """
        client = AsyncMock()
        ctx = _ctx(_config(max_items=100), client)
        with pytest.raises(ToolError, match="limit must be between 1 and 100"):
            await _call(server, "unifi_network_list_events", ctx, limit=500)


class TestConfigDefaults:
    """Default ceilings on the config object."""

    def test_default_max_list_items(self) -> None:
        cfg = UniFiConfig(
            _env_file=None,
            unifi_network_api="k",
            unifi_protect_api=None,
            unifi_site_manager_api=None,
        )
        assert cfg.unifi_max_list_items == 1000

    def test_default_max_list_offset(self) -> None:
        cfg = UniFiConfig(
            _env_file=None,
            unifi_network_api="k",
            unifi_protect_api=None,
            unifi_site_manager_api=None,
        )
        assert cfg.unifi_max_list_offset == 100_000

    def test_max_list_items_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="unifi_max_list_items"):
            UniFiConfig(
                _env_file=None,
                unifi_network_api="k",
                unifi_protect_api=None,
                unifi_site_manager_api=None,
                unifi_max_list_items=0,
            )

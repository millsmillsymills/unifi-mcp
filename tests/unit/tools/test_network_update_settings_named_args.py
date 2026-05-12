"""Named-scalar-arg variants for unifi_network_update_settings (#202).

Completes the option-1 rollout from #202 for the Network controller-wide
``rest/setting`` endpoint. Exercises the allowlist API:
- supplying named args builds the correct nested body server-side,
- supplying neither named args nor ``data=`` raises BadRequest,
- mixing named args with ``data=`` raises BadRequest,
- the legacy ``data=`` path still trips the dangerous-key denylist,
- the shared ``build_named_arg_body`` helper rejects path collisions
  (locks in the contract for future allowlist additions).

All HTTP is mocked with ``respx``; nothing reaches real hardware.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from unifi_mcp.clients.network import NetworkClient
from unifi_mcp.config import UniFiConfig, UniFiMode
from unifi_mcp.errors import UniFiBadRequestError
from unifi_mcp.tools._common import build_named_arg_body
from unifi_mcp.tools.network.system import register_system_tools

BASE_URL = "https://10.0.0.1:443"
SITE_PREFIX = f"{BASE_URL}/proxy/network/api/s/default"


# ── Fixtures ───────────────────────────────────────────────────────────────


@dataclass
class FakeLifespan:
    config: UniFiConfig
    clients: dict[str, Any] = field(default_factory=dict)


def _readwrite_config() -> UniFiConfig:
    return UniFiConfig(
        _env_file=None,
        unifi_mode=UniFiMode.READWRITE,
        unifi_network_api="k",
        unifi_protect_api="k",
        unifi_site_manager_api=None,
    )


def _ctx_with_network_client() -> tuple[AsyncMock, NetworkClient]:
    """Build a ctx whose Network client talks to the respx-mocked base URL."""
    client = NetworkClient(
        base_url=BASE_URL,
        api_key="test-key",
        site="default",
        timeout=5,
        max_retries=1,
    )
    ctx = AsyncMock()
    ctx.lifespan_context = FakeLifespan(config=_readwrite_config(), clients={"network": client})
    return ctx, client


async def _call(server: FastMCP, tool_name: str, ctx: AsyncMock, **kwargs: Any) -> Any:
    tool = await server.get_tool(tool_name)
    return await tool.fn(ctx, **kwargs)


# ── update_settings ────────────────────────────────────────────────────────


class TestUpdateSettingsNamedArgs:
    @respx.mock
    async def test_single_named_arg_routes_to_mgmt_timezone(self):
        server = FastMCP(name="t")
        register_system_tools(server)
        ctx, _ = _ctx_with_network_client()
        route = respx.put(f"{SITE_PREFIX}/rest/setting").mock(return_value=httpx.Response(200, json={"ok": True}))

        result = await _call(
            server,
            "unifi_network_update_settings",
            ctx,
            mgmt_timezone="America/Los_Angeles",
        )

        assert result == {"ok": True}
        sent = json.loads(route.calls[0].request.content)
        assert sent == {"mgmt": {"timezone": "America/Los_Angeles"}}

    @respx.mock
    async def test_locale_country_routes_to_locale_section(self):
        server = FastMCP(name="t")
        register_system_tools(server)
        ctx, _ = _ctx_with_network_client()
        route = respx.put(f"{SITE_PREFIX}/rest/setting").mock(return_value=httpx.Response(200, json={}))

        await _call(server, "unifi_network_update_settings", ctx, locale_country="US")

        sent = json.loads(route.calls[0].request.content)
        assert sent == {"locale": {"country": "US"}}

    @respx.mock
    async def test_both_ntp_servers_merge_under_ntp_section(self):
        server = FastMCP(name="t")
        register_system_tools(server)
        ctx, _ = _ctx_with_network_client()
        route = respx.put(f"{SITE_PREFIX}/rest/setting").mock(return_value=httpx.Response(200, json={}))

        await _call(
            server,
            "unifi_network_update_settings",
            ctx,
            ntp_server_1="time.example.com",
            ntp_server_2="time2.example.com",
        )

        sent = json.loads(route.calls[0].request.content)
        assert sent == {
            "ntp": {
                "ntp_server_1": "time.example.com",
                "ntp_server_2": "time2.example.com",
            }
        }

    @respx.mock
    async def test_mixed_sections_combine_into_one_body(self):
        server = FastMCP(name="t")
        register_system_tools(server)
        ctx, _ = _ctx_with_network_client()
        route = respx.put(f"{SITE_PREFIX}/rest/setting").mock(return_value=httpx.Response(200, json={}))

        await _call(
            server,
            "unifi_network_update_settings",
            ctx,
            mgmt_timezone="UTC",
            locale_country="GB",
            ntp_server_1="0.uk.pool.ntp.org",
        )

        sent = json.loads(route.calls[0].request.content)
        assert sent == {
            "mgmt": {"timezone": "UTC"},
            "locale": {"country": "GB"},
            "ntp": {"ntp_server_1": "0.uk.pool.ntp.org"},
        }

    async def test_no_args_raises_bad_request(self):
        server = FastMCP(name="t")
        register_system_tools(server)
        ctx, _ = _ctx_with_network_client()

        with pytest.raises(ToolError) as exc:
            await _call(server, "unifi_network_update_settings", ctx)
        assert "at least one field" in str(exc.value).lower()

    async def test_mixing_named_and_data_raises_bad_request(self):
        server = FastMCP(name="t")
        register_system_tools(server)
        ctx, _ = _ctx_with_network_client()

        with pytest.raises(ToolError) as exc:
            await _call(
                server,
                "unifi_network_update_settings",
                ctx,
                mgmt_timezone="UTC",
                data={"foo": 1},
            )
        assert "cannot mix" in str(exc.value).lower()

    @respx.mock
    async def test_legacy_data_dict_still_passes_through(self):
        server = FastMCP(name="t")
        register_system_tools(server)
        ctx, _ = _ctx_with_network_client()
        route = respx.put(f"{SITE_PREFIX}/rest/setting").mock(return_value=httpx.Response(200, json={}))

        await _call(
            server,
            "unifi_network_update_settings",
            ctx,
            data={"mgmt": {"timezone": "UTC"}},
        )

        sent = json.loads(route.calls[0].request.content)
        assert sent == {"mgmt": {"timezone": "UTC"}}

    async def test_legacy_data_dict_still_hits_denylist(self):
        server = FastMCP(name="t")
        register_system_tools(server)
        ctx, _ = _ctx_with_network_client()

        with pytest.raises(ToolError) as exc:
            await _call(
                server,
                "unifi_network_update_settings",
                ctx,
                data={"radius_secret": "x"},
            )
        assert "radius_secret" in str(exc.value)


# ── build_named_arg_body contract ──────────────────────────────────────────
#
# Lock in the helper's path-collision branch before any future allowlist
# addition can trip it silently. ``_SETTINGS_FIELD_PATHS`` is the first
# allowlist with nested paths long enough to make collisions conceivable
# (a section root + a leaf under the same section). PR #205 review called
# this out as the right home for the test.


class TestBuildNamedArgBodyContract:
    def test_path_collision_between_scalar_and_nested_field_raises(self):
        # Two kwargs target the same section: one as a leaf (mgmt = scalar),
        # one as a nested child (mgmt.timezone). The first write puts a
        # scalar at ``body["mgmt"]``; the second tries to descend into it.
        field_paths: dict[str, tuple[str, ...]] = {
            "mgmt": ("mgmt",),
            "mgmt_timezone": ("mgmt", "timezone"),
        }
        with pytest.raises(UniFiBadRequestError) as exc:
            build_named_arg_body(
                tool_name="test_tool",
                field_paths=field_paths,
                named_values={"mgmt": "scalar", "mgmt_timezone": "UTC"},
                data=None,
            )
        assert "path collision" in str(exc.value)
        assert "mgmt" in str(exc.value)

    def test_no_collision_when_paths_share_only_a_dict_parent(self):
        # Two leaves under the same dict parent must coexist without
        # raising — this is the legitimate ``ntp.ntp_server_1`` +
        # ``ntp.ntp_server_2`` shape exercised by the integration test
        # above; tested here at the helper level to guard against an
        # over-aggressive collision check.
        field_paths: dict[str, tuple[str, ...]] = {
            "a": ("section", "a"),
            "b": ("section", "b"),
        }
        body = build_named_arg_body(
            tool_name="test_tool",
            field_paths=field_paths,
            named_values={"a": 1, "b": 2},
            data=None,
        )
        assert body == {"section": {"a": 1, "b": 2}}

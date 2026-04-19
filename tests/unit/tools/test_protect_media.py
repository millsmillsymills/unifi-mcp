"""Tests for Protect media MCP tools (snapshots + video export)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from unifi_mcp.clients.protect import ProtectClient
from unifi_mcp.errors import UniFiError
from unifi_mcp.tools.protect.media import register_media_tools

BASE_URL = "https://10.0.0.1:443"
PROTECT_PREFIX = f"{BASE_URL}/proxy/protect/api"


@pytest.fixture
def protect_client_local() -> ProtectClient:
    return ProtectClient(base_url=BASE_URL, api_key="test-key", timeout=5, max_retries=1)


@pytest.fixture
def mcp_with_media() -> FastMCP:
    server = FastMCP(name="test-media")
    register_media_tools(server)
    return server


class TestMediaRegistration:
    async def test_all_tools_registered(self, mcp_with_media):
        tools = await mcp_with_media.list_tools()
        assert {t.name for t in tools} == {"protect_get_snapshot", "protect_export_video"}

    async def test_media_tools_are_read_only(self, mcp_with_media):
        # Snapshots and exports are reads of existing recording data — no write tag.
        tools = await mcp_with_media.list_tools()
        for tool in tools:
            assert "write" not in tool.tags


class TestMediaClientEndpoints:
    @respx.mock
    async def test_get_snapshot_without_timestamp(self, protect_client_local):
        route = respx.get(f"{PROTECT_PREFIX}/cameras/cam-1/snapshot").mock(
            return_value=httpx.Response(200, content=b"\xff\xd8\xff\xe0"),
        )
        result = await protect_client_local.get_snapshot("cam-1")
        assert result == b"\xff\xd8\xff\xe0"
        # No ts param by default
        assert "ts" not in route.calls[0].request.url.params

    @respx.mock
    async def test_get_snapshot_with_timestamp(self, protect_client_local):
        route = respx.get(f"{PROTECT_PREFIX}/cameras/cam-1/snapshot").mock(
            return_value=httpx.Response(200, content=b"\xff\xd8"),
        )
        await protect_client_local.get_snapshot("cam-1", timestamp=1700000000000)
        assert route.calls[0].request.url.params["ts"] == "1700000000000"

    @respx.mock
    async def test_export_video_uses_camera_scoped_path(self, protect_client_local):
        # Locks in the fix from #47 / PR #50.
        route = respx.get(f"{PROTECT_PREFIX}/cameras/cam-1/video/export").mock(
            return_value=httpx.Response(200, content=b"mp4-bytes"),
        )
        result = await protect_client_local.export_video("cam-1", start=1000, end=2000)
        assert result == b"mp4-bytes"
        params = route.calls[0].request.url.params
        assert params["start"] == "1000"
        assert params["end"] == "2000"
        assert "camera" not in params  # dropped in #47 fix

    @respx.mock
    async def test_export_video_respects_max_bytes(self, protect_client_local):
        # Streaming path (#32 / PR #64): abort when body exceeds the cap.
        payload = b"x" * 2048
        respx.get(f"{PROTECT_PREFIX}/cameras/cam-1/video/export").mock(
            return_value=httpx.Response(200, content=payload),
        )
        with pytest.raises(UniFiError, match="max_bytes=1024"):
            await protect_client_local.export_video("cam-1", start=1, end=2, max_bytes=1024)

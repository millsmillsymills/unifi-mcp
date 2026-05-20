"""Tests for server creation and mode gating."""

from unifi_mcp.config import UniFiConfig, UniFiMode
from unifi_mcp.server import create_server


def _make_config(**overrides):
    defaults = {
        "_env_file": None,
        "unifi_network_api": "test-net-key",
        "unifi_protect_api": "test-prot-key",
        "unifi_site_manager_api": "test-sm-key",
    }
    defaults.update(overrides)
    return UniFiConfig(**defaults)


class TestCreateServer:
    def test_creates_server_with_all_apis(self):
        config = _make_config()
        server = create_server(config)
        assert server.name == "unifi-mcp"

    def test_creates_server_with_network_only(self):
        config = _make_config(unifi_protect_api=None, unifi_site_manager_api=None)
        server = create_server(config)
        assert server.name == "unifi-mcp"

    def test_creates_server_with_no_apis(self):
        config = _make_config(unifi_network_api=None, unifi_protect_api=None, unifi_site_manager_api=None)
        server = create_server(config)
        assert server.name == "unifi-mcp"


class TestModeGating:
    async def test_write_tools_disabled_in_readonly_mode(self):
        config = _make_config(unifi_mode=UniFiMode.READONLY)
        server = create_server(config)
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        # Write tools should not be visible
        assert "unifi_network_create_wlan" not in tool_names
        assert "unifi_network_delete_wlan" not in tool_names
        assert "unifi_network_restart_device" not in tool_names
        assert "unifi_protect_update_camera" not in tool_names
        # Read tools should be visible
        assert "unifi_network_get_health" in tool_names
        assert "unifi_network_list_devices" in tool_names
        assert "unifi_protect_list_cameras" in tool_names
        assert "unifi_site_manager_list_hosts" in tool_names

    async def test_write_tools_enabled_in_readwrite_mode(self):
        config = _make_config(unifi_mode=UniFiMode.READWRITE)
        server = create_server(config)
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        # Write tools should be visible
        assert "unifi_network_create_wlan" in tool_names
        assert "unifi_network_delete_wlan" in tool_names
        assert "unifi_network_restart_device" in tool_names
        assert "unifi_protect_update_camera" in tool_names
        # Read tools should still be visible
        assert "unifi_network_get_health" in tool_names
        assert "unifi_protect_list_cameras" in tool_names

    async def test_no_protect_tools_when_not_configured(self):
        config = _make_config(unifi_protect_api=None)
        server = create_server(config)
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        assert "unifi_protect_list_cameras" not in tool_names
        assert "unifi_network_get_health" in tool_names

    async def test_no_site_manager_tools_when_not_configured(self):
        config = _make_config(unifi_site_manager_api=None)
        server = create_server(config)
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        assert "unifi_site_manager_list_hosts" not in tool_names
        assert "unifi_network_get_health" in tool_names

    async def test_tool_count_readwrite_all_apis(self):
        config = _make_config(unifi_mode=UniFiMode.READWRITE)
        server = create_server(config)
        tools = await server.list_tools()
        # Should have all tools registered
        assert len(tools) > 50

    async def test_tool_count_readonly_has_fewer_tools(self):
        config = _make_config(unifi_mode=UniFiMode.READONLY)
        server = create_server(config)
        readonly_tools = await server.list_tools()

        config_rw = _make_config(unifi_mode=UniFiMode.READWRITE)
        server_rw = create_server(config_rw)
        readwrite_tools = await server_rw.list_tools()

        assert len(readonly_tools) < len(readwrite_tools)

    async def test_every_write_tagged_tool_is_gated_by_mode(self):
        # Partition by the `write` tag and assert exhaustively that the gate
        # neither leaks a write tool into readonly nor drops a read tool —
        # named spot-checks above miss drift in either direction.
        rw_server = create_server(_make_config(unifi_mode=UniFiMode.READWRITE))
        rw_tools = await rw_server.list_tools()
        write_tools = {t.name for t in rw_tools if "write" in (t.tags or set())}
        read_tools = {t.name for t in rw_tools} - write_tools

        assert write_tools, "Expected at least one write-tagged tool in readwrite mode"

        ro_server = create_server(_make_config(unifi_mode=UniFiMode.READONLY))
        readonly_names = {t.name for t in await ro_server.list_tools()}

        leaked = write_tools & readonly_names
        assert not leaked, f"Write tools visible in readonly mode: {sorted(leaked)}"

        dropped = read_tools - readonly_names
        assert not dropped, f"Read tools missing from readonly mode: {sorted(dropped)}"

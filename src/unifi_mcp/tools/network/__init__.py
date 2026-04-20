"""Network API tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_network_tools(mcp: FastMCP) -> None:
    """Register all Network API tools on the server."""
    from unifi_mcp.tools.network.clients import register_client_tools
    from unifi_mcp.tools.network.devices import register_device_tools
    from unifi_mcp.tools.network.firewall import register_firewall_tools
    from unifi_mcp.tools.network.networks import register_network_config_tools
    from unifi_mcp.tools.network.port_forward import register_port_forward_tools
    from unifi_mcp.tools.network.port_profiles import register_port_profile_tools
    from unifi_mcp.tools.network.routing import register_routing_tools
    from unifi_mcp.tools.network.stats import register_stats_tools
    from unifi_mcp.tools.network.system import register_system_tools
    from unifi_mcp.tools.network.wlan import register_wlan_tools

    register_stats_tools(mcp)
    register_device_tools(mcp)
    register_client_tools(mcp)
    register_wlan_tools(mcp)
    register_network_config_tools(mcp)
    register_firewall_tools(mcp)
    register_port_forward_tools(mcp)
    register_port_profile_tools(mcp)
    register_routing_tools(mcp)
    register_system_tools(mcp)

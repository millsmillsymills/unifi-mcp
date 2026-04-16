"""MCP tool definitions for UniFi APIs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from unifi_mcp.config import UniFiConfig

logger = logging.getLogger(__name__)


def register_all_tools(mcp: FastMCP, config: UniFiConfig) -> None:
    """Register tools for all configured APIs."""
    if config.network_enabled:
        from unifi_mcp.tools.network import register_network_tools

        register_network_tools(mcp)
        logger.info("Registered Network tools")

    if config.protect_enabled:
        from unifi_mcp.tools.protect import register_protect_tools

        register_protect_tools(mcp)
        logger.info("Registered Protect tools")

    if config.site_manager_enabled:
        from unifi_mcp.tools.site_manager import register_site_manager_tools

        register_site_manager_tools(mcp)
        logger.info("Registered Site Manager tools")

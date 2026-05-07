"""MCP tool definitions for UniFi APIs.

Tools are split into a read surface and a write surface. ``register_read_tools``
registers everything and disables write-tagged tools; ``register_write_tools``
re-enables them when ``UNIFI_MODE=readwrite``. ``register_all_tools`` is the
single entry point used by ``server.create_server``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from unifi_mcp.config import UniFiConfig

logger = logging.getLogger(__name__)


def _register_for_each_api(mcp: FastMCP, config: UniFiConfig) -> None:
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


def register_read_tools(mcp: FastMCP, config: UniFiConfig) -> None:
    """Register every tool, then hide write-tagged tools.

    Idempotent: callers that need writes back should follow up with
    :func:`register_write_tools`. Implements the read half of PROTO-005.
    """
    _register_for_each_api(mcp, config)
    mcp.disable(tags={"write"})


def register_write_tools(mcp: FastMCP, config: UniFiConfig) -> None:
    """Re-enable write-tagged tools when ``UNIFI_MODE=readwrite``.

    Implements the write half of PROTO-005 and the explicit env-flag opt-in
    of PROTO-006: writes only come back on after an explicit
    ``config.writes_enabled`` check.
    """
    if config.writes_enabled:
        mcp.enable(tags={"write"})


def register_all_tools(mcp: FastMCP, config: UniFiConfig) -> None:
    """Register the read and write surfaces in mode-appropriate order."""
    register_read_tools(mcp, config)
    register_write_tools(mcp, config)

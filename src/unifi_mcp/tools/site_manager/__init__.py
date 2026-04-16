"""Site Manager API tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_site_manager_tools(mcp: FastMCP) -> None:
    """Register all Site Manager API tools on the server."""
    from unifi_mcp.tools.site_manager.discovery import (
        register_site_manager_tools as _register,
    )

    _register(mcp)

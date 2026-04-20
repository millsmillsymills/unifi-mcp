"""Protect API tools.

KNOWN ISSUE (#103): these tools are deregistered at startup on real Protect
controllers until the client ``_path_prefix`` is corrected. See
``src/unifi_mcp/clients/protect.py`` for status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_protect_tools(mcp: FastMCP) -> None:
    """Register all Protect API tools on the server."""
    from unifi_mcp.tools.protect.cameras import register_camera_tools
    from unifi_mcp.tools.protect.devices import register_protect_device_tools
    from unifi_mcp.tools.protect.events import register_event_tools
    from unifi_mcp.tools.protect.media import register_media_tools
    from unifi_mcp.tools.protect.nvr import register_nvr_tools

    register_camera_tools(mcp)
    register_event_tools(mcp)
    register_media_tools(mcp)
    register_nvr_tools(mcp)
    register_protect_device_tools(mcp)

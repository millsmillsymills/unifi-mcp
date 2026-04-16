"""Network WLAN configuration tools (2 read + 3 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_wlan_tools(mcp: FastMCP) -> None:
    """Register WLAN tools."""

    # ── Read tools ──────────────────────────────────────────────────────

    @mcp.tool(tags={"network"})
    async def network_list_wlans(ctx: Context) -> dict[str, Any]:
        """List all WLAN (Wi-Fi network) configurations."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["network"].list_wlans()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def network_get_wlan(ctx: Context, wlan_id: str) -> dict[str, Any]:
        """Get a specific WLAN configuration by ID.

        Args:
            wlan_id: The WLAN configuration ID.
        """
        try:
            context = _get_ctx(ctx)
            return await context.clients["network"].get_wlan(wlan_id)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    # ── Write tools ─────────────────────────────────────────────────────

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_create_wlan(
        ctx: Context,
        name: str,
        security: str = "wpapsk",
        wpa_mode: str = "wpa2",
        x_passphrase: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new WLAN (Wi-Fi network).

        Args:
            name: SSID name for the wireless network.
            security: Security mode — "wpapsk", "wpaeap", or "open".
            wpa_mode: WPA mode — "wpa2" or "wpa3".
            x_passphrase: Wi-Fi password (required for wpapsk).
            enabled: Whether the WLAN is enabled.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot create WLAN in read-only mode")
            data: dict[str, Any] = {
                "name": name,
                "security": security,
                "wpa_mode": wpa_mode,
                "x_passphrase": x_passphrase,
                "enabled": enabled,
            }
            return await context.clients["network"].create_wlan(data)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_update_wlan(ctx: Context, wlan_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing WLAN configuration. Pass only fields to change.

        Args:
            wlan_id: The WLAN configuration ID to update.
            data: Fields to update (e.g., {"name": "new-name", "enabled": false}).
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update WLAN in read-only mode")
            return await context.clients["network"].update_wlan(wlan_id, data)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_delete_wlan(ctx: Context, wlan_id: str) -> dict[str, Any]:
        """Delete a WLAN configuration.

        Args:
            wlan_id: The WLAN configuration ID to delete.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot delete WLAN in read-only mode")
            return await context.clients["network"].delete_wlan(wlan_id)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

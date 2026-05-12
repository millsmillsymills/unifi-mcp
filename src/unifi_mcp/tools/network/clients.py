"""Network client management tools (3 read + 4 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiNotFoundError, UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import get_server_context, redact_secrets


def register_client_tools(mcp: FastMCP) -> None:
    """Register network client tools."""

    # ── Read tools ──────────────────────────────────────────────────────

    @mcp.tool(tags={"network"})
    async def unifi_network_get_client(ctx: Context, mac: str) -> dict[str, Any]:
        """Get detailed info for a specific client by MAC address.

        Portal credential fields and other secret keys are redacted before
        the response leaves this tool — see ``unifi_mcp._redaction`` (#146).

        Args:
            mac: MAC address of the client.

        Returns:
            The upstream API response with sensitive fields redacted.
        """
        try:
            context = get_server_context(ctx)
            result = await context.clients["network"].list_active_clients()
            clients: list[dict[str, Any]] = result.get("data", [])
            for client in clients:
                if client.get("mac", "").lower() == mac.lower():
                    return redact_secrets(client)
            raise UniFiNotFoundError(f"Client with MAC {mac} not found among active clients")
        except Exception as e:
            handle_client_error(e)

    # ── Write tools ─────────────────────────────────────────────────────

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_block_client(ctx: Context, mac: str) -> dict[str, Any]:
        """Block a client from connecting to the network.

        Args:
            mac: MAC address of the client to block.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot block client in read-only mode")
            return await context.clients["network"].block_client(mac)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_unblock_client(ctx: Context, mac: str) -> dict[str, Any]:
        """Unblock a previously blocked client.

        Args:
            mac: MAC address of the client to unblock.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot unblock client in read-only mode")
            return await context.clients["network"].unblock_client(mac)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_kick_client(ctx: Context, mac: str) -> dict[str, Any]:
        """Disconnect a client from the network (they may reconnect).

        Args:
            mac: MAC address of the client to disconnect.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot kick client in read-only mode")
            return await context.clients["network"].kick_client(mac)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_authorize_guest(ctx: Context, mac: str, minutes: int = 60) -> dict[str, Any]:
        """Authorize a guest client for a specified duration.

        Args:
            mac: MAC address of the guest client.
            minutes: Duration of authorization in minutes (default: 60).

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot authorize guest in read-only mode")
            return await context.clients["network"].authorize_guest(mac, minutes=minutes)
        except Exception as e:
            handle_client_error(e)

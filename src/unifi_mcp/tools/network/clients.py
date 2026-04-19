"""Network client management tools (3 read + 4 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiNotFoundError, UniFiReadOnlyError, handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_client_tools(mcp: FastMCP) -> None:
    """Register network client tools."""

    # ── Read tools ──────────────────────────────────────────────────────

    @mcp.tool(tags={"network"})
    async def network_get_client(ctx: Context, mac: str) -> dict[str, Any]:
        """Get detailed info for a specific client by MAC address.

        Args:
            mac: MAC address of the client.
        """
        try:
            context = _get_ctx(ctx)
            result = await context.clients["network"].list_active_clients()
            clients = result.get("data", [])
            for client in clients:
                if client.get("mac", "").lower() == mac.lower():
                    return client  # type: ignore[no-any-return]
            raise UniFiNotFoundError(f"Client with MAC {mac} not found among active clients")
        except Exception as e:
            handle_client_error(e)

    # ── Write tools ─────────────────────────────────────────────────────

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_block_client(ctx: Context, mac: str) -> dict[str, Any]:
        """Block a client from connecting to the network.

        Args:
            mac: MAC address of the client to block.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot block client in read-only mode")
            return await context.clients["network"].block_client(mac)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_unblock_client(ctx: Context, mac: str) -> dict[str, Any]:
        """Unblock a previously blocked client.

        Args:
            mac: MAC address of the client to unblock.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot unblock client in read-only mode")
            return await context.clients["network"].unblock_client(mac)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_kick_client(ctx: Context, mac: str) -> dict[str, Any]:
        """Disconnect a client from the network (they may reconnect).

        Args:
            mac: MAC address of the client to disconnect.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot kick client in read-only mode")
            return await context.clients["network"].kick_client(mac)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_authorize_guest(ctx: Context, mac: str, minutes: int = 60) -> dict[str, Any]:
        """Authorize a guest client for a specified duration.

        Args:
            mac: MAC address of the guest client.
            minutes: Duration of authorization in minutes (default: 60).
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot authorize guest in read-only mode")
            return await context.clients["network"].authorize_guest(mac, minutes=minutes)
        except Exception as e:
            handle_client_error(e)

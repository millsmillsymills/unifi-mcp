"""Network device management tools (2 read + 5 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_device_tools(mcp: FastMCP) -> None:
    """Register network device tools."""

    # ── Read tools ──────────────────────────────────────────────────────

    @mcp.tool(tags={"network"})
    async def network_get_device(ctx: Context, mac: str) -> dict[str, Any]:
        """Get detailed info for a specific network device by MAC address.

        Args:
            mac: MAC address of the device (e.g., "aa:bb:cc:dd:ee:ff").
        """
        try:
            context = _get_ctx(ctx)
            result = await context.clients["network"].list_devices()
            devices = result.get("data", [])
            for device in devices:
                if device.get("mac", "").lower() == mac.lower():
                    return device  # type: ignore[no-any-return]
            return {"error": f"Device with MAC {mac} not found"}
        except Exception as e:
            handle_client_error(e)

    # ── Write tools ─────────────────────────────────────────────────────

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_restart_device(ctx: Context, mac: str) -> dict[str, Any]:
        """Restart an adopted network device.

        Args:
            mac: MAC address of the device to restart.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot restart device in read-only mode")
            return await context.clients["network"].restart_device(mac)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_adopt_device(ctx: Context, mac: str) -> dict[str, Any]:
        """Adopt a new device into the network.

        Args:
            mac: MAC address of the device to adopt.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot adopt device in read-only mode")
            return await context.clients["network"].adopt_device(mac)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_locate_device(ctx: Context, mac: str) -> dict[str, Any]:
        """Enable the locate LED on a device (makes it blink for identification).

        Args:
            mac: MAC address of the device.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot locate device in read-only mode")
            return await context.clients["network"].locate_device(mac)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_unlocate_device(ctx: Context, mac: str) -> dict[str, Any]:
        """Disable the locate LED on a device (stop blinking).

        Args:
            mac: MAC address of the device.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot unlocate device in read-only mode")
            return await context.clients["network"].unlocate_device(mac)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_provision_device(ctx: Context, mac: str) -> dict[str, Any]:
        """Force re-provision a device (push current configuration).

        Args:
            mac: MAC address of the device.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot provision device in read-only mode")
            return await context.clients["network"].provision_device(mac)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

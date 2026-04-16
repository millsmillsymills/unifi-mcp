"""Network configuration tools (2 read + 3 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_network_config_tools(mcp: FastMCP) -> None:
    """Register network config tools."""

    @mcp.tool(tags={"network"})
    async def network_list_networks(ctx: Context) -> dict[str, Any]:
        """List all network (VLAN/subnet) configurations."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["network"].list_networks()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def network_get_network(ctx: Context, network_id: str) -> dict[str, Any]:
        """Get a specific network configuration by ID.

        Args:
            network_id: The network configuration ID.
        """
        try:
            context = _get_ctx(ctx)
            return await context.clients["network"].get_network(network_id)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_create_network(
        ctx: Context,
        name: str,
        purpose: str = "corporate",
        subnet: str | None = None,
        vlan: int | None = None,
        dhcpd_enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new network (VLAN/subnet).

        Args:
            name: Network name.
            purpose: Purpose — "corporate", "guest", "wan", "vlan-only".
            subnet: Subnet in CIDR notation (e.g., "192.168.2.0/24").
            vlan: VLAN ID (optional).
            dhcpd_enabled: Whether DHCP server is enabled.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot create network in read-only mode")
            data: dict[str, Any] = {"name": name, "purpose": purpose, "dhcpd_enabled": dhcpd_enabled}
            if subnet is not None:
                data["subnet"] = subnet
            if vlan is not None:
                data["vlan"] = vlan
            return await context.clients["network"].create_network(data)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_update_network(ctx: Context, network_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing network configuration. Pass only fields to change.

        Args:
            network_id: The network configuration ID.
            data: Fields to update (e.g., {"name": "new-name", "vlan": 100}).
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update network in read-only mode")
            return await context.clients["network"].update_network(network_id, data)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_delete_network(ctx: Context, network_id: str) -> dict[str, Any]:
        """Delete a network configuration.

        Args:
            network_id: The network configuration ID to delete.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot delete network in read-only mode")
            return await context.clients["network"].delete_network(network_id)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

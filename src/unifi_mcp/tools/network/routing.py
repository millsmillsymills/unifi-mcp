"""Network static routing tools (2 read + 3 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.server import ServerContext


def _get_ctx(ctx: Context) -> ServerContext:
    return ctx.lifespan_context  # type: ignore[return-value]


def register_routing_tools(mcp: FastMCP) -> None:
    """Register routing tools."""

    @mcp.tool(tags={"network"})
    async def network_list_routes(ctx: Context) -> dict[str, Any]:
        """List all static routes."""
        try:
            context = _get_ctx(ctx)
            return await context.clients["network"].list_routes()  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def network_get_route(ctx: Context, route_id: str) -> dict[str, Any]:
        """Get a specific static route by ID.

        Args:
            route_id: The route ID.
        """
        try:
            context = _get_ctx(ctx)
            return await context.clients["network"].get_route(route_id)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_create_route(
        ctx: Context,
        name: str,
        network: str,
        route_type: str = "nexthop-route",
        gateway_ip: str | None = None,
        interface: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new static route.

        Args:
            name: Route name.
            network: Destination network in CIDR notation (e.g., "10.0.0.0/24").
            route_type: Route type — "nexthop-route" or "interface-route".
            gateway_ip: Next-hop gateway IP (for nexthop-route).
            interface: Interface name (for interface-route).
            enabled: Whether the route is enabled.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot create route in read-only mode")
            data: dict[str, Any] = {
                "name": name,
                "type": route_type,
                "network": network,
                "enabled": enabled,
            }
            if gateway_ip is not None:
                data["gateway_ip"] = gateway_ip
            if interface is not None:
                data["interface"] = interface
            return await context.clients["network"].create_route(data)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_update_route(ctx: Context, route_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing static route. Pass only fields to change.

        Args:
            route_id: The route ID.
            data: Fields to update (e.g., {"enabled": false, "gateway_ip": "10.0.0.1"}).
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update route in read-only mode")
            return await context.clients["network"].update_route(route_id, data)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_delete_route(ctx: Context, route_id: str) -> dict[str, Any]:
        """Delete a static route.

        Args:
            route_id: The route ID to delete.
        """
        try:
            context = _get_ctx(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot delete route in read-only mode")
            return await context.clients["network"].delete_route(route_id)  # type: ignore[no-any-return]
        except Exception as e:
            handle_client_error(e)

"""Network static routing tools (2 read + 3 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import JsonObject, get_server_context, redact_secrets, reject_dangerous_keys, validate_id


def register_routing_tools(mcp: FastMCP) -> None:
    """Register routing tools."""

    @mcp.tool(tags={"network"})
    async def unifi_network_list_routes(ctx: Context) -> dict[str, Any]:
        """List all static routes.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response with sensitive fields redacted.
        """
        try:
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["network"].list_routes())
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_get_route(ctx: Context, route_id: str) -> dict[str, Any]:
        """Get a specific static route by ID.

        Args:
            route_id: The route ID.

        Returns:
            The upstream API response with sensitive fields redacted.
        """
        try:
            validate_id(route_id, field="route_id")
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["network"].get_route(route_id))
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_create_route(
        ctx: Context,
        name: str,
        network: str,
        route_type: str = "nexthop-route",
        gateway_ip: str | None = None,
        interface: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new static route.

        Returns:
            The upstream API response.

        Args:
            name: Route name.
            network: Destination CIDR (e.g. "10.0.0.0/24").
            route_type: "nexthop-route" or "interface-route".
            gateway_ip: Next-hop gateway IP (for nexthop-route).
            interface: Interface name (for interface-route).
            enabled: Whether the route is enabled.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot create route in read-only mode")
            data: JsonObject = {
                "name": name,
                "type": "static-route",
                "enabled": enabled,
                "static-route_type": route_type,
                "static-route_network": network,
                "static-route_distance": 1,
            }
            if gateway_ip is not None:
                data["static-route_nexthop"] = gateway_ip
            if interface is not None:
                data["static-route_interface"] = interface
            return await context.clients["network"].create_route(data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_update_route(ctx: Context, route_id: str, data: JsonObject) -> dict[str, Any]:
        """Update an existing static route. Pass only fields to change.

        Args:
            route_id: The route ID.
            data: Fields to update (e.g., {"enabled": false, "gateway_ip": "10.0.0.1"}).

        Returns:
            The upstream API response.
        """
        try:
            validate_id(route_id, field="route_id")
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot update route in read-only mode")
            reject_dangerous_keys(data, tool_name="unifi_network_update_route")
            return await context.clients["network"].update_route(route_id, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_delete_route(ctx: Context, route_id: str) -> dict[str, Any]:
        """Delete a static route.

        Args:
            route_id: The route ID to delete.

        Returns:
            The upstream API response.
        """
        try:
            validate_id(route_id, field="route_id")
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot delete route in read-only mode")
            return await context.clients["network"].delete_route(route_id)
        except Exception as e:
            handle_client_error(e)

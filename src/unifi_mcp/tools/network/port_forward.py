"""Network port forwarding tools (2 read + 3 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import JsonObject, get_server_context, reject_dangerous_keys


def register_port_forward_tools(mcp: FastMCP) -> None:
    """Register port forward tools."""

    @mcp.tool(tags={"network"})
    async def unifi_network_list_port_forwards(ctx: Context) -> dict[str, Any]:
        """List all port forwarding rules.

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_port_forwards()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def unifi_network_get_port_forward(ctx: Context, port_forward_id: str) -> dict[str, Any]:
        """Get a specific port forwarding rule by ID.

        Args:
            port_forward_id: The port forward rule ID.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].get_port_forward(port_forward_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_create_port_forward(
        ctx: Context,
        name: str,
        dst_port: str,
        fwd: str,
        fwd_port: str,
        proto: str = "tcp_udp",
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new port forwarding rule.

        Args:
            name: Rule name.
            dst_port: Destination port (external port).
            fwd: Forward-to IP address (internal host).
            fwd_port: Forward-to port (internal port).
            proto: Protocol — "tcp", "udp", or "tcp_udp".
            enabled: Whether the rule is enabled.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot create port forward in read-only mode")
            data: JsonObject = {
                "name": name,
                "dst_port": dst_port,
                "fwd": fwd,
                "fwd_port": fwd_port,
                "proto": proto,
                "enabled": enabled,
            }
            return await context.clients["network"].create_port_forward(data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_network_update_port_forward(ctx: Context, port_forward_id: str, data: JsonObject) -> dict[str, Any]:
        """Update an existing port forwarding rule. Pass only fields to change.

        Args:
            port_forward_id: The port forward rule ID.
            data: Fields to update (e.g., {"enabled": false, "fwd_port": "8080"}).

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot update port forward in read-only mode")
            reject_dangerous_keys(data, tool_name="unifi_network_update_port_forward")
            return await context.clients["network"].update_port_forward(port_forward_id, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def unifi_network_delete_port_forward(ctx: Context, port_forward_id: str) -> dict[str, Any]:
        """Delete a port forwarding rule.

        Args:
            port_forward_id: The port forward rule ID to delete.

        Returns:
            The upstream API response.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot delete port forward in read-only mode")
            return await context.clients["network"].delete_port_forward(port_forward_id)
        except Exception as e:
            handle_client_error(e)

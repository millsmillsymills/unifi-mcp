"""Network firewall rules and groups tools (4 read + 6 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import get_server_context


def register_firewall_tools(mcp: FastMCP) -> None:
    """Register firewall tools."""

    # ── Read tools ──────────────────────────────────────────────────────

    @mcp.tool(tags={"network"})
    async def network_list_firewall_rules(ctx: Context) -> dict[str, Any]:
        """List all firewall rules."""
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_firewall_rules()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def network_get_firewall_rule(ctx: Context, rule_id: str) -> dict[str, Any]:
        """Get a specific firewall rule by ID.

        Args:
            rule_id: The firewall rule ID.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].get_firewall_rule(rule_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def network_list_firewall_groups(ctx: Context) -> dict[str, Any]:
        """List all firewall groups (address groups, port groups)."""
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_firewall_groups()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def network_get_firewall_group(ctx: Context, group_id: str) -> dict[str, Any]:
        """Get a specific firewall group by ID.

        Args:
            group_id: The firewall group ID.
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].get_firewall_group(group_id)
        except Exception as e:
            handle_client_error(e)

    # ── Write tools ─────────────────────────────────────────────────────

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_create_firewall_rule(
        ctx: Context,
        name: str,
        ruleset: str,
        action: str = "drop",
        enabled: bool = True,
        protocol: str = "all",
        src_address: str | None = None,
        dst_address: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new firewall rule.

        The UniFi legacy `rest/firewallrule` endpoint requires more fields
        than this tool's scalar argument list exposes (rule_index, logging,
        state_new / state_established / state_invalid / state_related,
        icmp_typename, ipsec, src_firewallgroup_ids, dst_firewallgroup_ids,
        etc.). Passing only the scalar args above is rejected with HTTP 400
        `api.err.FirewallRuleFieldsRequired` on current controllers (#90).

        Pass a fully-formed payload via the ``data`` kwarg to reach those
        fields — same shape as ``network_update_firewall_rule``'s data arg.
        When ``data`` is supplied it's used as-is and the scalar args are
        ignored.

        Args:
            name: Rule name. Ignored if ``data`` is supplied.
            ruleset: Ruleset — "WAN_IN", "WAN_OUT", "LAN_IN", "LAN_OUT", etc.
                Ignored if ``data`` is supplied.
            action: Action — "accept", "drop", or "reject".
                Ignored if ``data`` is supplied.
            enabled: Whether the rule is enabled. Ignored if ``data`` is supplied.
            protocol: Protocol — "all", "tcp", "udp", "tcp_udp", "icmp".
                Ignored if ``data`` is supplied.
            src_address: Source IP/CIDR (optional). Ignored if ``data`` is supplied.
            dst_address: Destination IP/CIDR (optional). Ignored if ``data`` is supplied.
            data: Full firewall-rule payload. When supplied, it is passed to
                the controller verbatim and takes precedence over the scalar
                args above. Use this to populate required fields (e.g.
                ``rule_index``) that the scalar args don't expose.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot create firewall rule in read-only mode")
            if data is None:
                data = {
                    "name": name,
                    "ruleset": ruleset,
                    "action": action,
                    "enabled": enabled,
                    "protocol": protocol,
                }
                if src_address is not None:
                    data["src_address"] = src_address
                if dst_address is not None:
                    data["dst_address"] = dst_address
            return await context.clients["network"].create_firewall_rule(data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_update_firewall_rule(ctx: Context, rule_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing firewall rule. Pass only fields to change.

        Args:
            rule_id: The firewall rule ID.
            data: Fields to update (e.g., {"enabled": false, "action": "accept"}).
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update firewall rule in read-only mode")
            return await context.clients["network"].update_firewall_rule(rule_id, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_delete_firewall_rule(ctx: Context, rule_id: str) -> dict[str, Any]:
        """Delete a firewall rule.

        Args:
            rule_id: The firewall rule ID to delete.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot delete firewall rule in read-only mode")
            return await context.clients["network"].delete_firewall_rule(rule_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_create_firewall_group(
        ctx: Context,
        name: str,
        group_type: str,
        group_members: list[str],
    ) -> dict[str, Any]:
        """Create a new firewall group.

        Args:
            name: Group name.
            group_type: Type — "address-group", "port-group", "ipv6-address-group".
            group_members: List of members (IPs/CIDRs for address groups, ports for port groups).
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot create firewall group in read-only mode")
            data: dict[str, Any] = {
                "name": name,
                "group_type": group_type,
                "group_members": group_members,
            }
            return await context.clients["network"].create_firewall_group(data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_update_firewall_group(ctx: Context, group_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing firewall group. Pass only fields to change.

        Args:
            group_id: The firewall group ID.
            data: Fields to update (e.g., {"group_members": ["10.0.0.0/24"]}).
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update firewall group in read-only mode")
            return await context.clients["network"].update_firewall_group(group_id, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_delete_firewall_group(ctx: Context, group_id: str) -> dict[str, Any]:
        """Delete a firewall group.

        Args:
            group_id: The firewall group ID to delete.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot delete firewall group in read-only mode")
            return await context.clients["network"].delete_firewall_group(group_id)
        except Exception as e:
            handle_client_error(e)

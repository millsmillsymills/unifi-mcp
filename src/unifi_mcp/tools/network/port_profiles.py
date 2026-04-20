"""Switch port-profile management tools (2 read + 4 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import get_server_context


def register_port_profile_tools(mcp: FastMCP) -> None:
    """Register port-profile tools (see #93)."""

    # ── Read tools ──────────────────────────────────────────────────────

    @mcp.tool(tags={"network"})
    async def network_list_port_profiles(ctx: Context) -> dict[str, Any]:
        """List all switch port profiles (VLAN, PoE, storm-control configs)."""
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].list_port_profiles()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"network"})
    async def network_get_port_profile(ctx: Context, profile_id: str) -> dict[str, Any]:
        """Get a specific switch port profile by id.

        Args:
            profile_id: The port-profile ID (``_id`` from ``list_port_profiles``).
        """
        try:
            context = get_server_context(ctx)
            return await context.clients["network"].get_port_profile(profile_id)
        except Exception as e:
            handle_client_error(e)

    # ── Write tools ─────────────────────────────────────────────────────

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_create_port_profile(ctx: Context, data: dict[str, Any]) -> dict[str, Any]:
        """Create a switch port profile.

        The controller requires at least ``name``, ``poe_mode`` (e.g. ``auto``),
        and ``forward`` (e.g. ``all`` / ``native`` / ``customize``). Pass a
        full payload via ``data`` — it's forwarded verbatim.

        Args:
            data: Full port-profile payload.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot create port profile in read-only mode")
            return await context.clients["network"].create_port_profile(data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def network_update_port_profile(ctx: Context, profile_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update a switch port profile. Pass only fields to change.

        Args:
            profile_id: The port-profile ID to update.
            data: Fields to update (e.g. ``{"poe_mode": "off"}``).
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot update port profile in read-only mode")
            return await context.clients["network"].update_port_profile(profile_id, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_delete_port_profile(ctx: Context, profile_id: str) -> dict[str, Any]:
        """Delete a switch port profile.

        Every switch port currently bound to this profile falls back to the
        default profile, which may reset VLAN tagging and PoE mode — treat
        this as destructive on any production site.

        Args:
            profile_id: The port-profile ID to delete.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot delete port profile in read-only mode")
            return await context.clients["network"].delete_port_profile(profile_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "network"}, annotations={"readOnlyHint": False, "destructiveHint": True})
    async def network_assign_port_profile(ctx: Context, mac: str, port_idx: int, profile_id: str) -> dict[str, Any]:
        """Assign a port profile to a specific switch port.

        Splices a ``port_overrides`` entry onto the device so the named port
        adopts the profile's VLAN tagging / PoE mode / storm-control config.
        Marked destructive because it can immediately drop clients on that
        port if the new profile changes their link config.

        Args:
            mac: MAC address of the switch.
            port_idx: 1-based port number on the switch.
            profile_id: The port-profile ID to apply.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.is_readwrite:
                raise UniFiReadOnlyError("Cannot assign port profile in read-only mode")
            return await context.clients["network"].assign_port_profile(mac, port_idx, profile_id)
        except Exception as e:
            handle_client_error(e)

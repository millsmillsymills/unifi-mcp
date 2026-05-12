"""Site Manager discovery tools — read-only host, site, and device listing."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import handle_client_error
from unifi_mcp.tools._common import get_server_context, redact_secrets


def register_site_manager_tools(mcp: FastMCP) -> None:
    """Register all Site Manager tools on the given FastMCP server."""

    @mcp.tool(tags={"site_manager"})
    async def unifi_site_manager_list_hosts(ctx: Context) -> dict[str, Any]:
        """List all hosts (controllers) registered in UniFi Site Manager.

        Bearer tokens and other secret keys are redacted before the response
        leaves this tool — see ``unifi_mcp._redaction`` (#146, #203).

        Args:
            ctx: FastMCP request context — supplied by the framework.

        Returns:
            The Site Manager API response with sensitive fields redacted,
            shaped as ``{"data": [...], "httpStatusCode": 200}``. Each entry
            in ``data`` is a host record with at least ``id``, ``hostName``,
            ``isBlocked``, ``reportedState``, and ``hardwareId``.
        """
        try:
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["site_manager"].list_hosts())
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"site_manager"})
    async def unifi_site_manager_list_sites(ctx: Context) -> dict[str, Any]:
        """List all sites across all hosts in UniFi Site Manager.

        Bearer tokens and other secret keys are redacted before the response
        leaves this tool — see ``unifi_mcp._redaction`` (#146, #203).

        Args:
            ctx: FastMCP request context — supplied by the framework.

        Returns:
            The Site Manager API response with sensitive fields redacted,
            shaped as ``{"data": [...], "httpStatusCode": 200}``. Each entry
            in ``data`` is a site record with ``id``, ``hostId``, ``meta``
            (display name, description, timezone), and ``statistics``.
        """
        try:
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["site_manager"].list_sites())
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"site_manager"})
    async def unifi_site_manager_list_devices(ctx: Context, host_id: str | None = None) -> dict[str, Any]:
        """List all devices in UniFi Site Manager, optionally filtered by host ID.

        Bearer tokens and other secret keys are redacted before the response
        leaves this tool — see ``unifi_mcp._redaction`` (#146, #203).

        Args:
            ctx: FastMCP request context — supplied by the framework.
            host_id: Optional host ID. When set, the response is filtered to devices
                belonging to that host; when ``None``, devices across every host are
                returned.

        Returns:
            The Site Manager API response with sensitive fields redacted,
            shaped as ``{"data": [...], "httpStatusCode": 200}``. Each entry
            in ``data`` is a device record with ``id``, ``hostId``, ``mac``,
            ``model``, ``firmwareVersion``, and ``state``.
        """
        try:
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["site_manager"].list_devices(host_id=host_id))
        except Exception as e:
            handle_client_error(e)

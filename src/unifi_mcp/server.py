"""FastMCP server creation, lifespan, and mode gating."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from unifi_mcp.clients.base import BaseUniFiClient
    from unifi_mcp.clients.network import NetworkClient
    from unifi_mcp.clients.protect import ProtectClient
    from unifi_mcp.clients.site_manager import SiteManagerClient

import httpx
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from unifi_mcp.config import UniFiConfig
from unifi_mcp.errors import UniFiError

logger = logging.getLogger(__name__)


class APIClients(TypedDict, total=False):
    """Per-API clients keyed by short name. Keys may be absent when the API is disabled or failed validation."""

    network: NetworkClient
    protect: ProtectClient
    site_manager: SiteManagerClient


@dataclass
class ServerContext:
    """Lifespan context passed to all tools via ``ctx.lifespan_context``."""

    config: UniFiConfig
    clients: APIClients = field(default_factory=APIClients)


async def _register_client(context: ServerContext, name: str, client: Any) -> None:
    """Validate and register a client, closing it if validation fails."""
    try:
        valid = await client.validate_connection()
    except (UniFiError, httpx.HTTPError):
        logger.exception("Failed to connect to %s API — skipping", name)
        await client.close()
        return
    if valid:
        context.clients[name] = client  # type: ignore[literal-required]
        logger.info("%s API client initialized", name)
    else:
        logger.warning("%s API validation returned False — skipping", name)
        await client.close()


@lifespan  # type: ignore[arg-type]
async def server_lifespan(_server: FastMCP) -> AsyncIterator[ServerContext]:
    """Initialize clients for configured APIs, validate, and yield context."""
    config = UniFiConfig()
    context = ServerContext(config=config)

    # Lazily import clients to avoid circular deps
    from unifi_mcp.clients.network import NetworkClient
    from unifi_mcp.clients.protect import ProtectClient
    from unifi_mcp.clients.site_manager import SiteManagerClient

    if config.network_enabled:
        await _register_client(
            context,
            "network",
            NetworkClient(
                base_url=config.network_base_url,
                api_key=config.unifi_network_api.get_secret_value(),  # type: ignore[union-attr]
                site=config.unifi_network_site,
                verify_ssl=config.unifi_network_verify_ssl,
                timeout=config.unifi_request_timeout,
                max_retries=config.unifi_max_retries,
            ),
        )

    if config.protect_enabled:
        await _register_client(
            context,
            "protect",
            ProtectClient(
                base_url=config.protect_base_url,
                api_key=config.unifi_protect_api.get_secret_value(),  # type: ignore[union-attr]
                verify_ssl=config.unifi_protect_verify_ssl,
                timeout=config.unifi_request_timeout,
                max_retries=config.unifi_max_retries,
            ),
        )

    if config.site_manager_enabled:
        await _register_client(
            context,
            "site_manager",
            SiteManagerClient(
                api_key=config.unifi_site_manager_api.get_secret_value(),  # type: ignore[union-attr]
                timeout=config.unifi_request_timeout,
                max_retries=config.unifi_max_retries,
            ),
        )

    if not context.clients:
        logger.warning("No API clients initialized — server will have no tools")

    try:
        yield context
    finally:
        clients_to_close: list[tuple[str, BaseUniFiClient]] = list(context.clients.items())  # type: ignore[arg-type]
        for name, c in clients_to_close:
            try:
                await c.close()
                logger.info("Closed %s client", name)
            except (OSError, httpx.HTTPError):
                logger.exception("Error closing %s client", name)


def create_server(config: UniFiConfig | None = None) -> FastMCP:
    """Create and configure the FastMCP server."""
    if config is None:
        config = UniFiConfig()

    server = FastMCP(
        name="unifi-mcp",
        instructions=(
            "UniFi MCP server providing tools for UniFi Site Manager, "
            "Network, and Protect APIs. Use these tools to query and manage "
            "your UniFi network infrastructure."
        ),
        lifespan=server_lifespan,
    )

    # Register tools for configured APIs
    from unifi_mcp.tools import register_all_tools

    register_all_tools(server, config)

    # Apply mode gating — hide write tools in readonly mode
    if not config.is_readwrite:
        server.disable(tags={"write"})
        logger.info("Read-only mode: write tools disabled")
    else:
        logger.info("Read-write mode: all tools enabled")

    return server

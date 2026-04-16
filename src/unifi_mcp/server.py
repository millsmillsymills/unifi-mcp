"""FastMCP server creation, lifespan, and mode gating."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from unifi_mcp.config import UniFiConfig

logger = logging.getLogger(__name__)


@dataclass
class ServerContext:
    """Lifespan context passed to all tools via ``ctx.lifespan_context``."""

    config: UniFiConfig
    clients: dict[str, Any] = field(default_factory=dict)


@lifespan  # type: ignore[arg-type]
async def server_lifespan(_server: FastMCP) -> AsyncIterator[ServerContext]:
    """Initialize clients for configured APIs, validate, and yield context."""
    config = UniFiConfig()
    context = ServerContext(config=config)

    # Lazily import clients to avoid circular deps
    from unifi_mcp.clients.network import NetworkClient
    from unifi_mcp.clients.protect import ProtectClient
    from unifi_mcp.clients.site_manager import SiteManagerClient

    # Initialize clients for configured APIs
    if config.network_enabled:
        try:
            net_client = NetworkClient(
                base_url=config.network_base_url,
                api_key=config.unifi_network_api,  # type: ignore[arg-type]
                site=config.unifi_network_site,
                verify_ssl=config.unifi_network_verify_ssl,
                timeout=config.unifi_request_timeout,
                max_retries=config.unifi_max_retries,
            )
            await net_client.validate_connection()
            context.clients["network"] = net_client
            logger.info("Network API client initialized")
        except Exception:
            logger.exception("Failed to connect to Network API — skipping")

    if config.protect_enabled:
        try:
            prot_client = ProtectClient(
                base_url=config.protect_base_url,
                api_key=config.unifi_protect_api,  # type: ignore[arg-type]
                verify_ssl=config.unifi_protect_verify_ssl,
                timeout=config.unifi_request_timeout,
                max_retries=config.unifi_max_retries,
            )
            await prot_client.validate_connection()
            context.clients["protect"] = prot_client
            logger.info("Protect API client initialized")
        except Exception:
            logger.exception("Failed to connect to Protect API — skipping")

    if config.site_manager_enabled:
        try:
            sm_client = SiteManagerClient(
                api_key=config.unifi_site_manager_api,  # type: ignore[arg-type]
                timeout=config.unifi_request_timeout,
                max_retries=config.unifi_max_retries,
            )
            await sm_client.validate_connection()
            context.clients["site_manager"] = sm_client
            logger.info("Site Manager API client initialized")
        except Exception:
            logger.exception("Failed to connect to Site Manager API — skipping")

    if not context.clients:
        logger.warning("No API clients initialized — server will have no tools")

    try:
        yield context
    finally:
        for name, c in context.clients.items():
            try:
                await c.close()
                logger.info("Closed %s client", name)
            except Exception:
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

"""Shared helpers and type aliases for tool modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from unifi_mcp._redaction import redact_secrets

if TYPE_CHECKING:
    from fastmcp import Context

    from unifi_mcp.server import ServerContext

type JsonObject = dict[str, Any]

__all__ = ["JsonObject", "get_server_context", "redact_secrets"]


def get_server_context(ctx: Context) -> ServerContext:
    """Return the typed lifespan context for a tool call."""
    return cast("ServerContext", ctx.lifespan_context)

"""Shared helpers and type aliases for tool modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from fastmcp import Context

    from unifi_mcp.server import ServerContext

JsonObject: TypeAlias = dict[str, Any]


def get_server_context(ctx: Context) -> ServerContext:
    """Return the typed lifespan context for a tool call."""
    return ctx.lifespan_context  # type: ignore[return-value]

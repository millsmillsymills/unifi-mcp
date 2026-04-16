"""Exception hierarchy and error mapping for UniFi MCP server."""

from __future__ import annotations

import logging
from typing import NoReturn

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


class UniFiError(Exception):
    """Base exception for all UniFi API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class UniFiAuthError(UniFiError):
    """Authentication or authorization failure (401/403)."""


class UniFiNotFoundError(UniFiError):
    """Resource not found (404)."""


class UniFiRateLimitError(UniFiError):
    """Rate limit exceeded (429)."""


class UniFiConnectionError(UniFiError):
    """Connection failure (timeout, DNS, network)."""


class UniFiReadOnlyError(UniFiError):
    """Write operation attempted in read-only mode."""


def handle_client_error(error: Exception) -> NoReturn:
    """Map UniFi exceptions to FastMCP ToolError with agent-readable messages.

    Raises:
        ToolError: Always raised with a descriptive message.
    """
    if isinstance(error, UniFiAuthError):
        raise ToolError(f"Authentication failed: {error}. Check your API key.") from error
    if isinstance(error, UniFiNotFoundError):
        raise ToolError(f"Resource not found: {error}") from error
    if isinstance(error, UniFiRateLimitError):
        raise ToolError(f"Rate limit exceeded: {error}. Try again later.") from error
    if isinstance(error, UniFiConnectionError):
        raise ToolError(f"Connection failed: {error}. Check host and network.") from error
    if isinstance(error, UniFiReadOnlyError):
        raise ToolError(f"Write operation blocked: {error}. Server is in read-only mode.") from error
    if isinstance(error, UniFiError):
        raise ToolError(f"UniFi API error: {error}") from error
    # Unexpected errors
    logger.exception("Unexpected error in tool execution")
    raise ToolError(f"Unexpected error: {error}") from error

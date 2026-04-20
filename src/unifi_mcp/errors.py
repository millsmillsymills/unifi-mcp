"""Exception hierarchy and error mapping for UniFi MCP server."""

from __future__ import annotations

import asyncio
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


class UniFiBadRequestError(UniFiError):
    """Malformed or invalid request payload (400)."""


class UniFiNotFoundError(UniFiError):
    """Resource not found (404)."""


class UniFiRateLimitError(UniFiError):
    """Rate limit exceeded (429)."""


class UniFiServerError(UniFiError):
    """Upstream server failure (5xx)."""


class UniFiConnectionError(UniFiError):
    """Connection failure (DNS, network, TCP reset)."""


class UniFiTimeoutError(UniFiConnectionError):
    """Request exceeded the configured timeout."""


class UniFiReadOnlyError(UniFiError):
    """Write operation attempted in read-only mode."""


class UniFiDeviceAlreadyAdoptedError(UniFiError):
    """Adopt invoked on a device that's already adopted by this controller.

    The controller returns a generic ``api.err.InvalidTarget`` for this case,
    which is indistinguishable from "MAC unknown to controller" at the raw API
    level. ``NetworkClient.adopt_device`` pre-checks against ``list_devices``
    and raises this to give agents a specific, actionable error to branch on.
    """


def handle_client_error(error: BaseException) -> NoReturn:
    """Map UniFi exceptions to FastMCP ToolError with agent-readable messages.

    ``asyncio.CancelledError`` is re-raised untouched — wrapping it as a
    ``ToolError`` would break FastMCP's cancellation propagation (a shutdown
    or client-side cancel would look like a tool error instead of a cancel).

    Raises:
        asyncio.CancelledError: Propagated without wrapping.
        ToolError: For any other exception, with a descriptive message.
    """
    if isinstance(error, asyncio.CancelledError):
        raise error
    if isinstance(error, UniFiAuthError):
        raise ToolError(f"Authentication failed: {error}. Check your API key.") from error
    if isinstance(error, UniFiBadRequestError):
        raise ToolError(f"Invalid request: {error}.") from error
    if isinstance(error, UniFiNotFoundError):
        raise ToolError(f"Resource not found: {error}") from error
    if isinstance(error, UniFiRateLimitError):
        raise ToolError(f"Rate limit exceeded: {error}. Try again later.") from error
    if isinstance(error, UniFiServerError):
        raise ToolError(f"UniFi server error: {error}. The controller may be unhealthy.") from error
    if isinstance(error, UniFiTimeoutError):
        raise ToolError(f"Request timed out: {error}. The controller did not respond in time.") from error
    if isinstance(error, UniFiConnectionError):
        raise ToolError(f"Connection failed: {error}. Check host and network.") from error
    if isinstance(error, UniFiReadOnlyError):
        raise ToolError(f"Write operation blocked: {error}. Server is in read-only mode.") from error
    if isinstance(error, UniFiDeviceAlreadyAdoptedError):
        raise ToolError(f"Device already adopted: {error}") from error
    if isinstance(error, UniFiError):
        raise ToolError(f"UniFi API error: {error}") from error
    # Unexpected errors
    logger.exception("Unexpected error in tool execution")
    raise ToolError(f"Unexpected error: {error}") from error

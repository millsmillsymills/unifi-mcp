"""Logging configuration for the MCP server.

stdio transport reserves stdout for protocol traffic, so all logs must go to
stderr (MCP-021). The default formatter emits one JSON object per record so
operators can pipe logs into structured collectors (MCP-022).

The module name is ``_logging`` (not ``logging``) so it does not shadow the
stdlib module on imports inside the package.
"""

from __future__ import annotations

import json
import logging
import os
import sys

_LEVEL_ENV = "UNIFI_LOG_LEVEL"
_DEFAULT_LEVEL = "INFO"
_VALID_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"})


class JSONFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    _RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}

    def format(self, record: logging.LogRecord) -> str:
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self._RESERVED and not key.startswith("_")
        }
        payload: dict[str, object] = {
            **extras,
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _resolve_level(level: str | None) -> str:
    raw = (level or os.environ.get(_LEVEL_ENV) or _DEFAULT_LEVEL).strip().upper()
    if raw in _VALID_LEVELS:
        return raw
    print(  # noqa: T201
        f"unifi-mcp: ignoring invalid log level {raw!r}; falling back to {_DEFAULT_LEVEL}",
        file=sys.stderr,
    )
    return _DEFAULT_LEVEL


def configure_logging(level: str | None = None) -> None:
    """Install a stderr JSON handler on the root and FastMCP loggers.

    Resolution order for the level: explicit ``level`` arg > ``UNIFI_LOG_LEVEL``
    env var > ``"INFO"``. Invalid values fall back to ``INFO`` with a warning
    on stderr rather than aborting startup.

    Idempotent: replaces any handlers previously attached to the root logger so
    repeated calls (e.g. in tests) don't accumulate duplicates. The FastMCP
    logger is also redirected through the JSON handler so its records share
    the same stderr-JSON shape as the rest of the package's output.
    """
    resolved = _resolve_level(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=resolved, handlers=[handler], force=True)

    fastmcp_logger = logging.getLogger("fastmcp")
    for existing in list(fastmcp_logger.handlers):
        fastmcp_logger.removeHandler(existing)
    fastmcp_logger.propagate = True

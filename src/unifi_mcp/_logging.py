"""Logging configuration for the MCP server.

stdio transport reserves stdout for protocol traffic, so all logs must go to
stderr (MCP-021). The default formatter emits one JSON object per record so
operators can pipe logs into structured collectors (MCP-022).
"""

from __future__ import annotations

import json
import logging
import os
import sys

_LEVEL_ENV = "UNIFI_LOG_LEVEL"
_DEFAULT_LEVEL = "INFO"


class JSONFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    _RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in self._RESERVED and not key.startswith("_")
            }
        )
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None) -> None:
    """Install a stderr JSON handler at module load.

    Idempotent: replaces any handlers previously attached to the root logger so
    repeated calls (e.g. in tests) don't accumulate duplicates.
    """
    resolved = (level or os.environ.get(_LEVEL_ENV) or _DEFAULT_LEVEL).upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=resolved, handlers=[handler], force=True)

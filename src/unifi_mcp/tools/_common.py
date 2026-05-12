"""Shared helpers and type aliases for tool modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from unifi_mcp.errors import UniFiBadRequestError

if TYPE_CHECKING:
    from fastmcp import Context

    from unifi_mcp.server import ServerContext

type JsonObject = dict[str, Any]

__all__ = ["JsonObject", "get_server_context", "reject_dangerous_keys"]


def get_server_context(ctx: Context) -> ServerContext:
    """Return the typed lifespan context for a tool call."""
    return cast("ServerContext", ctx.lifespan_context)


# ── Settings-smuggling denylist (#147) ─────────────────────────────────────
#
# `dict[str, Any]` write tools forward the body verbatim to the controller.
# A write-mode agent receiving a prompt-injected instruction can smuggle
# config changes the tool name does NOT advertise: RADIUS hijack via
# `radius_servers`, callback exfil via `super_mgmt_url`, lockout via
# `mac_filter_list`, evidence suppression via Protect recording fields.
#
# This denylist is a stopgap (option 2 from the issue). The honest answer
# (option 1) is per-endpoint named scalar args + an explicit allowlist —
# tracked as a follow-up.

_DENYLIST_EXACT_KEYS: frozenset[str] = frozenset(
    {
        "cmd",
        "x_cmd",
        "is_admin",
        "role",
        "roles",
        "permissions",
        "mac_filter_list",
        "mac_filter_enabled",
    }
)
_DENYLIST_KEY_PREFIXES: tuple[str, ...] = ("super_", "radius_")
_DENYLIST_KEY_SUFFIXES: tuple[str, ...] = ("_url", "_command")


def _normalize_key(key: str) -> str:
    """Lowercase + strip underscores so the denylist catches both snake_case
    (``super_mgmt_url``) and camelCase (``superMgmtUrl``, ``webhookUrl``)
    variants of the same key. UniFi Network APIs use snake_case but Protect
    APIs use camelCase, so a single denylist pattern must cover both.
    """
    return key.lower().replace("_", "")


# Normalized forms of the patterns above — built once at import time.
_NORM_EXACT_KEYS: frozenset[str] = frozenset(_normalize_key(k) for k in _DENYLIST_EXACT_KEYS)
_NORM_PREFIXES: tuple[str, ...] = tuple(_normalize_key(p) for p in _DENYLIST_KEY_PREFIXES)
_NORM_SUFFIXES: tuple[str, ...] = tuple(_normalize_key(s) for s in _DENYLIST_KEY_SUFFIXES)


def _is_dangerous_key(key: str) -> bool:
    normalized = _normalize_key(key)
    if normalized in _NORM_EXACT_KEYS:
        return True
    if any(normalized.startswith(p) for p in _NORM_PREFIXES):
        return True
    return any(normalized.endswith(s) for s in _NORM_SUFFIXES)


def _walk(value: Any, path: str, *, tool_name: str) -> None:
    if isinstance(value, dict):
        for raw_key, sub in value.items():
            key = str(raw_key)
            sub_path = f"{path}.{key}" if path else key
            if _is_dangerous_key(key):
                raise UniFiBadRequestError(
                    f"{tool_name}: dangerous key '{sub_path}' is not allowed; "
                    f"use the dedicated tool or split your update."
                )
            _walk(sub, sub_path, tool_name=tool_name)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _walk(item, f"{path}[{idx}]", tool_name=tool_name)


def reject_dangerous_keys(data: Any, *, tool_name: str) -> None:
    """Raise ``UniFiBadRequestError`` if ``data`` contains a smuggling key.

    Walks dicts and lists recursively. Keys are matched after a normalize
    step (lowercase + strip underscores) so the same rule catches both
    snake_case (Network APIs) and camelCase (Protect APIs) variants.
    Designed to be called at the top of every ``dict[str, Any]`` write
    tool, after the ``writes_enabled`` mode gate, before the client call.

    Args:
        data: Request body to inspect — typically a top-level ``dict``.
        tool_name: Tool identifier for the error message.

    Raises:
        UniFiBadRequestError: If a dangerous key is found, with a dotted
            path locating it in the payload.
    """
    _walk(data, "", tool_name=tool_name)

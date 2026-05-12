"""Protect NVR tools (1 read + 1 write)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp.errors import UniFiReadOnlyError, handle_client_error
from unifi_mcp.tools._common import (
    JsonObject,
    build_named_arg_body,
    get_server_context,
    redact_secrets,
    reject_dangerous_keys,
)

# ── Option-1 allowlist for unifi_protect_update_nvr (#202) ─────────────────
_NVR_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "timezone": ("timezone",),
}


def register_nvr_tools(mcp: FastMCP) -> None:
    """Register NVR tools."""

    @mcp.tool(tags={"protect"})
    async def unifi_protect_get_nvr(ctx: Context) -> dict[str, Any]:
        """Get NVR (Network Video Recorder) status and configuration.

        ``ssoToken`` and other credential fields are redacted before the
        response leaves this tool — see ``unifi_mcp._redaction`` (#146).

        Args:
            ctx: FastMCP request context.

        Returns:
            The upstream API response with sensitive fields redacted.
        """
        try:
            context = get_server_context(ctx)
            return redact_secrets(await context.clients["protect"].get_nvr())
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"write", "protect"}, annotations={"readOnlyHint": False, "destructiveHint": False})
    async def unifi_protect_update_nvr(
        ctx: Context,
        *,
        name: str | None = None,
        timezone: str | None = None,
        data: JsonObject | None = None,
    ) -> dict[str, Any]:
        """Update NVR settings using named scalar args.

        Pass only the fields to change.

        Args:
            name: NVR display name.
            timezone: IANA timezone string (e.g. ``"America/Los_Angeles"``).
            data: DEPRECATED — raw NVR settings dict. Kept for back-compat
                with existing agents; prefer the named scalar args above.
                Still passes through the dangerous-key denylist. Cannot be
                combined with any named arg.

        Returns:
            The upstream API response.

        Note:
            The underlying endpoint is missing from Protect integration v1
            on UCK-G2-Plus (Protect 7.0.107). Calls return ``HTTP 404 Entity
            'endpoint' not found``. Tracked in #139; the tool stays
            registered so it works automatically once Ubiquiti exposes the
            endpoint on a future firmware.
        """
        try:
            context = get_server_context(ctx)
            if not context.config.writes_enabled:
                raise UniFiReadOnlyError("Cannot update NVR in read-only mode")
            body = build_named_arg_body(
                tool_name="unifi_protect_update_nvr",
                field_paths=_NVR_FIELD_PATHS,
                named_values={"name": name, "timezone": timezone},
                data=data,
            )
            reject_dangerous_keys(body, tool_name="unifi_protect_update_nvr")
            return await context.clients["protect"].update_nvr(body)
        except Exception as e:
            handle_client_error(e)

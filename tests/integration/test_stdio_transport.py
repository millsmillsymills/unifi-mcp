"""Subprocess MCP stdio transport coverage.

The rest of the integration suite (and every unit test) drives the server with
``fastmcp.Client(server)`` — an *in-process* transport that bypasses the JSON-RPC
framing, line buffering, and process boundary that real MCP clients use. This
module spawns the installed ``unifi-mcp`` console script as a real subprocess
and drives it through the MCP **stdio** transport, covering §4 of #97.

The test does not require live UniFi hardware. The server is started with no
``UNIFI_*_API`` env vars, so all three API clients stay unconfigured, no tools
register, and the lifespan emits its "no API clients initialized" warning —
but the protocol handshake still completes, ``serverInfo`` is reported, and
``tools/list`` returns an empty list. That's exactly what we want here: the
contract under test is the *transport*, not the tools.

The subprocess is launched in a temp ``cwd`` so pydantic-settings doesn't pick
up the repo's ``.env`` and silently re-enable APIs (which would then fail
``validate_connection`` against unreachable hardware in CI).

Run manually with::

    uv run pytest tests/integration/test_stdio_transport.py -v -m integration
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Env vars that must be scrubbed from the subprocess environment so the server
# starts with zero APIs configured. Leaving any of these set would (a) try to
# validate against real hardware that may not be reachable in CI, and (b)
# defeat the purpose of a transport-only test by changing the served tool set.
_API_ENV_VARS = (
    "UNIFI_NETWORK_API",
    "UNIFI_PROTECT_API",
    "UNIFI_SITE_MANAGER_API",
)


def _server_env() -> dict[str, str]:
    """Build a minimal env for the subprocess with no UniFi APIs configured.

    Inherits ``PATH`` (so the ``unifi-mcp`` console script and its interpreter
    are discoverable) and ``HOME`` (some libs read it at import time), then
    forces ``UNIFI_MODE=readonly`` and explicitly excludes every API key. We
    do *not* copy the rest of the parent env because a developer running this
    locally is very likely to have ``UNIFI_*`` set in their shell.
    """
    env = {
        "UNIFI_MODE": "readonly",
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    for key in _API_ENV_VARS:
        env.pop(key, None)
    return env


async def test_stdio_handshake_no_apis_configured() -> None:
    """Spawn ``unifi-mcp`` over stdio, complete the handshake, list tools.

    With no API keys configured the server registers no tools and the lifespan
    logs "No API clients initialized — server will have no tools". The MCP
    handshake itself must still succeed: ``initialize`` returns ``serverInfo``,
    ``tools/list`` returns an empty list, and tearing down the client shuts
    the subprocess down cleanly.
    """
    command = shutil.which("unifi-mcp")
    if command is None:
        pytest.skip("unifi-mcp console script not on PATH; run `uv sync` first")

    with tempfile.TemporaryDirectory(prefix="unifi-mcp-stdio-test-") as cwd:
        transport = StdioTransport(
            command=command,
            args=[],
            env=_server_env(),
            cwd=cwd,
        )
        async with Client(transport) as client:
            assert client.is_connected(), "client failed to connect over stdio"

            init = client.initialize_result
            assert init is not None, "no InitializeResult captured after handshake"
            assert init.serverInfo is not None, "serverInfo missing from initialize result"
            assert init.serverInfo.name == "unifi-mcp", f"unexpected serverInfo.name: {init.serverInfo.name!r}"
            assert init.serverInfo.version, "serverInfo.version should be a non-empty string"

            tools = await client.list_tools()
            assert isinstance(tools, list), f"tools/list returned non-list: {type(tools)!r}"
            assert tools == [], (
                "expected zero tools with no APIs configured; "
                f"got {[t.name for t in tools]!r} — is the .env leaking through?"
            )

        # Leaving the ``async with`` closes the transport, which signals EOF on
        # the subprocess stdin and waits for it to exit. If shutdown were
        # broken the context manager would hang or raise; reaching this line
        # is itself the assertion that the server tore down cleanly.
        assert not client.is_connected(), "client still connected after context exit"

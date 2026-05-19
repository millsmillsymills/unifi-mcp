"""Subprocess MCP stdio transport coverage.

The rest of the integration suite (and every unit test) drives the server with
``fastmcp.Client(server)`` — an *in-process* transport that bypasses the JSON-RPC
framing, line buffering, and process boundary that real MCP clients use. This
module spawns the installed ``unifi-mcp`` console script as a real subprocess
and drives it through the MCP **stdio** transport, covering §4 of #97.

Two layers of coverage live here:

* ``test_stdio_handshake_no_apis_configured`` exercises the bare transport
  contract — handshake, ``serverInfo``, empty ``tools/list``, clean shutdown —
  with zero APIs configured.
* ``TestStdioModeFlip`` boots the subprocess against an in-test HTTPS mock that
  satisfies ``NetworkClient.validate_connection`` so Network tools actually
  register. The same subprocess shape is then driven once with
  ``UNIFI_MODE=readonly`` and once with ``UNIFI_MODE=readwrite`` to verify the
  write-tool tag gate over the real stdio boundary. This closes the most
  agent-doable slice of #43 acceptance criterion 3.

The subprocess is launched in a temp ``cwd`` so pydantic-settings doesn't pick
up the repo's ``.env`` and silently re-enable APIs (which would then fail
``validate_connection`` against unreachable hardware in CI).

Run manually with::

    uv run pytest tests/integration/test_stdio_transport.py -v -m integration
"""

from __future__ import annotations

import datetime
import http.server
import json
import os
import shutil
import ssl
import tempfile
import threading
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

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

# Canned Network-API-shaped JSON returned for any GET against the mock host.
# ``validate_connection`` calls ``stat/sysinfo`` and only checks for a 2xx; the
# body shape just needs to deserialise as a dict so the client's response
# parser doesn't raise.
_CANNED_BODY = {"data": [{"version": "8.0.0"}], "meta": {"rc": "ok"}}

# A pair of known write-tool names that exist in the Network API surface (see
# ``tests/unit/test_server.py::test_write_tools_disabled_in_readonly_mode``).
# Used to assert visibility flips with ``UNIFI_MODE``. ``unifi_network_block_client``
# is single-target; ``unifi_network_create_wlan`` is the canonical creation
# tool — covering both reduces the chance of a single rename masking the gate.
_KNOWN_WRITE_TOOLS = frozenset(
    {
        "unifi_network_block_client",
        "unifi_network_create_wlan",
        "unifi_network_restart_device",
    }
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


# ── Mode-flip subprocess coverage ──────────────────────────────────────────


def _generate_self_signed_cert(host_ip: str) -> tuple[bytes, bytes]:
    """Return ``(cert_pem, key_pem)`` for a self-signed leaf bound to ``host_ip``.

    Only the leaf is needed because the subprocess client runs with
    ``UNIFI_NETWORK_VERIFY_SSL=false`` — httpx skips chain validation
    entirely. The cert still needs a SAN that matches the dialled host
    in case future regressions tighten that branch.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host_ip)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(IPv4Address(host_ip))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


class _CannedNetworkHandler(http.server.BaseHTTPRequestHandler):
    """Returns a canned Network-API-shaped JSON body for any GET; suppresses logs.

    ``NetworkClient.validate_connection`` only requires a 2xx with a parseable
    JSON object on ``stat/sysinfo``. We answer every path the same way so the
    mock doesn't have to track the Network API's URL grammar.
    """

    def do_GET(self) -> None:
        body = json.dumps(_CANNED_BODY).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002 — http.server API
        return


class _NetworkMockHTTPSServer:
    """Background thread running an ``http.server`` with TLS wrapping on 127.0.0.1.

    Mirrors the fixture in ``tests/unit/clients/test_ssl_verification.py`` but
    is intentionally duplicated here: the integration package shouldn't reach
    into ``tests/unit`` internals, and the mock's only job is to make
    ``validate_connection`` return True so the subprocess registers Network
    tools.
    """

    def __init__(self, cert_path: Path, key_path: Path) -> None:
        self._server = http.server.HTTPServer(("127.0.0.1", 0), _CannedNetworkHandler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self._server.socket = ctx.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        port: int = self._server.server_address[1]
        return port

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def network_mock_server(tmp_path: Path) -> Iterator[_NetworkMockHTTPSServer]:
    """Stand up a self-signed HTTPS server that answers any Network-API GET with 200.

    Yields the running server bound to an ephemeral port on 127.0.0.1. The
    cert is regenerated per test (cheap with 2048-bit RSA) so a stale fixture
    can't carry stale material between runs.
    """
    cert_pem, key_pem = _generate_self_signed_cert("127.0.0.1")
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server.key"
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)

    server = _NetworkMockHTTPSServer(cert_path=cert_path, key_path=key_path)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def _mode_flip_env(*, mode: str, network_port: int) -> dict[str, str]:
    """Build a subprocess env with Network configured against ``network_port``.

    All Protect/Site-Manager keys are scrubbed so only Network tools register,
    keeping the served tool set deterministic. ``UNIFI_NETWORK_VERIFY_SSL`` is
    forced false so httpx accepts the in-test self-signed cert.
    """
    env = {
        "UNIFI_MODE": mode,
        "UNIFI_NETWORK_HOST": "127.0.0.1",
        "UNIFI_NETWORK_PORT": str(network_port),
        "UNIFI_NETWORK_API": "test-network-key",
        "UNIFI_NETWORK_VERIFY_SSL": "false",
        "UNIFI_NETWORK_SITE": "default",
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    # Belt-and-braces: scrubbed even though they were never added.
    for key in ("UNIFI_PROTECT_API", "UNIFI_SITE_MANAGER_API"):
        env.pop(key, None)
    return env


class TestStdioModeFlip:
    """Verify ``UNIFI_MODE`` gates write-tool visibility over real stdio.

    Two subprocess spawns: one in readonly mode (no write tools must appear),
    one in readwrite mode (known write tools must appear). The same mock HTTPS
    backend is used for both so the only varying axis is the env var under
    test. Progresses #43 acceptance criterion 3.
    """

    async def test_readonly_mode_hides_write_tools(
        self,
        network_mock_server: _NetworkMockHTTPSServer,
    ) -> None:
        command = shutil.which("unifi-mcp")
        if command is None:
            pytest.skip("unifi-mcp console script not on PATH; run `uv sync` first")

        with tempfile.TemporaryDirectory(prefix="unifi-mcp-stdio-readonly-") as cwd:
            transport = StdioTransport(
                command=command,
                args=[],
                env=_mode_flip_env(mode="readonly", network_port=network_mock_server.port),
                cwd=cwd,
            )
            async with Client(transport) as client:
                assert client.is_connected(), "client failed to connect over stdio"
                tools = await client.list_tools()

        tool_names = {t.name for t in tools}
        # If Network tools didn't register, the test is meaningless — the mock
        # backend or env wiring is broken, not the mode gate. Catch that here
        # so the failure message points at the right cause.
        assert any(name.startswith("unifi_network_") for name in tool_names), (
            f"no Network tools registered; mock backend or env wiring is broken — got tools: {sorted(tool_names)!r}"
        )
        leaked = tool_names & _KNOWN_WRITE_TOOLS
        assert not leaked, (
            f"write tools visible in readonly mode: {sorted(leaked)!r}; "
            "UNIFI_MODE gate is not being enforced over the stdio boundary"
        )

    async def test_readwrite_mode_exposes_write_tools(
        self,
        network_mock_server: _NetworkMockHTTPSServer,
    ) -> None:
        command = shutil.which("unifi-mcp")
        if command is None:
            pytest.skip("unifi-mcp console script not on PATH; run `uv sync` first")

        with tempfile.TemporaryDirectory(prefix="unifi-mcp-stdio-readwrite-") as cwd:
            transport = StdioTransport(
                command=command,
                args=[],
                env=_mode_flip_env(mode="readwrite", network_port=network_mock_server.port),
                cwd=cwd,
            )
            async with Client(transport) as client:
                assert client.is_connected(), "client failed to connect over stdio"
                tools = await client.list_tools()

        tool_names = {t.name for t in tools}
        present = tool_names & _KNOWN_WRITE_TOOLS
        assert present, (
            f"no known write tools visible in readwrite mode; expected at least one of "
            f"{sorted(_KNOWN_WRITE_TOOLS)!r}, got {sorted(tool_names)!r}"
        )

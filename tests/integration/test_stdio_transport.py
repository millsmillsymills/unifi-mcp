"""Subprocess MCP stdio transport coverage.

The rest of the integration suite (and every unit test) drives the server with
``fastmcp.Client(server)`` — an *in-process* transport that bypasses the JSON-RPC
framing, line buffering, and process boundary that real MCP clients use. This
module spawns the installed ``unifi-mcp`` console script as a real subprocess
and drives it through the MCP **stdio** transport, covering §4 of #97.

Four layers of coverage live here:

* ``test_stdio_handshake_no_apis_configured`` exercises the bare transport
  contract — handshake, ``serverInfo``, empty ``tools/list``, clean shutdown —
  with zero APIs configured.
* ``TestStdioModeFlip`` boots the subprocess against an in-test HTTPS mock that
  satisfies ``NetworkClient.validate_connection`` so Network tools actually
  register. The same subprocess shape is then driven once with
  ``UNIFI_MODE=readonly`` and once with ``UNIFI_MODE=readwrite`` to verify the
  write-tool tag gate over the real stdio boundary. This closes the most
  agent-doable slice of #43 acceptance criterion 3.
* ``TestStdioToolCallCancellation`` drives a tool call that hangs in the
  upstream HTTP request, then cancels the client task. It verifies that a
  cancellation crossing the real JSON-RPC stdio boundary surfaces as
  ``CancelledError`` and — critically — that the session stays usable
  afterwards. ``tests/unit/clients/test_cancellation.py`` only pins the
  ``BaseUniFiClient`` contract in-process; this is the missing transport-level
  slice of §4 in #97.
* ``TestStdioConcurrentToolCalls`` fires many tool calls simultaneously over the
  same session. The Network client re-uses one ``httpx.AsyncClient``, so every
  concurrent call shares its connection pool; a rendezvous mock that answers a
  request only once all of them have arrived proves the pool serves them
  simultaneously instead of serialising, and equal payloads prove no cross-talk
  between in-flight calls. This is the "concurrent tool calls — no stress test"
  slice of §4 in #97.

The subprocess is launched in a temp ``cwd`` so pydantic-settings doesn't pick
up the repo's ``.env`` and silently re-enable APIs (which would then fail
``validate_connection`` against unreachable hardware in CI).

Run manually with::

    uv run pytest tests/integration/test_stdio_transport.py -v -m integration
"""

from __future__ import annotations

import asyncio
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


# ── Tool-call cancellation over stdio ───────────────────────────────────────

# The read tool whose call we cancel. It maps to ``NetworkClient.get_health``
# (``GET stat/health``), which the mock below hangs on. It registers in
# readonly mode, so no write gate is involved.
_HANGING_TOOL = "unifi_network_get_health"


class _CancellableNetworkHandler(http.server.BaseHTTPRequestHandler):
    """Canned 200 for any GET except ``stat/health``, which blocks until released.

    ``validate_connection`` hits ``stat/sysinfo`` at startup and must succeed
    fast, so only the health path hangs. The handler signals ``health_requested``
    the instant the hang begins (proving the tool call reached the upstream
    request server-side) and then waits on ``release`` — set during teardown so
    a hung handler thread can never outlive the test. The events live on the
    server instance so this stateless handler can reach them.
    """

    def do_GET(self) -> None:
        server: Any = self.server
        if "health" in self.path:
            server.health_requested.set()
            # Bounded wait: teardown sets ``release``; the timeout is a
            # backstop so a test bug can't wedge the handler thread forever.
            server.release.wait(timeout=30)
        body = json.dumps(_CANNED_BODY).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # The subprocess closes the connection when the cancelled tool
            # task tears down its httpx request; writing the late response
            # then fails. That's expected, not a test failure.
            pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002 — http.server API
        return


class _CancellableMockHTTPSServer:
    """Threaded HTTPS mock so a hung ``stat/health`` handler can't block startup.

    A single-threaded ``HTTPServer`` would serialise requests: the hanging
    health handler would also stall the ``stat/sysinfo`` validation probe and
    the teardown ``shutdown()``. ``ThreadingHTTPServer`` gives each request its
    own (daemon) thread so only the health request blocks.
    """

    def __init__(self, cert_path: Path, key_path: Path) -> None:
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CancellableNetworkHandler)
        self._server.daemon_threads = True
        self._server.health_requested = threading.Event()  # type: ignore[attr-defined]
        self._server.release = threading.Event()  # type: ignore[attr-defined]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self._server.socket = ctx.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        port: int = self._server.server_address[1]
        return port

    @property
    def health_requested(self) -> threading.Event:
        return self._server.health_requested  # type: ignore[attr-defined,no-any-return]

    @property
    def release(self) -> threading.Event:
        return self._server.release  # type: ignore[attr-defined,no-any-return]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        # Release any in-flight health handler before shutting down so its
        # thread can exit instead of sitting on the 30s backstop.
        self._server.release.set()  # type: ignore[attr-defined]
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def cancellation_mock_server(tmp_path: Path) -> Iterator[_CancellableMockHTTPSServer]:
    """HTTPS mock that hangs on ``stat/health`` until ``release`` is set."""
    cert_pem, key_pem = _generate_self_signed_cert("127.0.0.1")
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server.key"
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)

    server = _CancellableMockHTTPSServer(cert_path=cert_path, key_path=key_path)
    server.start()
    try:
        yield server
    finally:
        server.stop()


class TestStdioToolCallCancellation:
    """Cancel an in-flight ``tools/call`` over the real stdio JSON-RPC boundary.

    Closes the transport-level slice of §4 in #97 that the in-process
    ``test_cancellation.py`` suite cannot reach.
    """

    async def test_cancel_in_flight_tool_call_keeps_session_usable(
        self,
        cancellation_mock_server: _CancellableMockHTTPSServer,
    ) -> None:
        """A cancelled tool call must surface ``CancelledError`` and leave the
        session healthy enough to serve a follow-up request.

        Sequence: call ``unifi_network_get_health`` (the mock hangs on
        ``stat/health``); once the mock confirms the upstream request arrived,
        cancel the awaiting client task; assert ``CancelledError`` propagates;
        then issue a fresh ``tools/list`` on the same session and assert it
        still answers — i.e. one cancelled call doesn't wedge the transport.
        """
        command = shutil.which("unifi-mcp")
        if command is None:
            pytest.skip("unifi-mcp console script not on PATH; run `uv sync` first")

        with tempfile.TemporaryDirectory(prefix="unifi-mcp-stdio-cancel-") as cwd:
            transport = StdioTransport(
                command=command,
                args=[],
                env=_mode_flip_env(mode="readonly", network_port=cancellation_mock_server.port),
                cwd=cwd,
            )
            async with Client(transport) as client:
                assert client.is_connected(), "client failed to connect over stdio"

                tool_names = {t.name for t in await client.list_tools()}
                assert _HANGING_TOOL in tool_names, (
                    f"{_HANGING_TOOL!r} did not register; mock backend or env wiring is broken — "
                    f"got tools: {sorted(tool_names)!r}"
                )

                call_task = asyncio.create_task(client.call_tool(_HANGING_TOOL, {}))

                # Wait until the upstream request is genuinely in-flight
                # server-side before cancelling. Polling the threading.Event
                # from the loop is a cheap flag read.
                for _ in range(200):
                    if cancellation_mock_server.health_requested.is_set():
                        break
                    await asyncio.sleep(0.05)
                else:  # pragma: no cover — only hit if the call never dispatched
                    call_task.cancel()
                    pytest.fail("tool call never reached the upstream stat/health request")

                call_task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await call_task

                # The session must still be alive: a fresh request over the
                # same stdio connection has to succeed. If cancellation had
                # wedged the transport this would hang (caught by the suite
                # timeout) or raise a connection error.
                tools_after = await client.list_tools()
                assert _HANGING_TOOL in {t.name for t in tools_after}, (
                    "session unusable after cancelling an in-flight tool call"
                )

            assert not client.is_connected(), "client still connected after context exit"


# ── Concurrent tool calls over stdio ────────────────────────────────────────

# Each concurrent call invokes this read tool (``NetworkClient.get_health`` →
# ``GET stat/health``). Firing many at once drives many simultaneous GETs through
# the one ``httpx.AsyncClient`` the Network client re-uses, exercising the shared
# connection pool §4 of #97 flags as never stress-tested. It registers in
# readonly mode, so no write gate is involved.
_CONCURRENT_TOOL = "unifi_network_get_health"

# Number of tool calls to fire at once. Above httpx's one-live-connection default
# so genuine parallelism is exercised, yet far below its max_connections cap
# (100, unset here) so the pool itself is not the bottleneck.
_CONCURRENCY = 8

# Client-side bound on the rendezvous. With a healthy pool all calls arrive
# within milliseconds and the gather resolves at once; if the pool (or the
# server) serialised calls the rendezvous could never fill and the first handler
# would sit on its 30s backstop, so this shorter bound trips first — turning a
# silent slowdown into an explicit failure.
_RENDEZVOUS_TIMEOUT = 10.0


def _result_payload(result: Any) -> Any:
    """Return a tool result's structured payload (``structured_content`` then ``data``).

    ``Client.call_tool`` raises on a tool error, so any result reaching here is a
    success; ``is not None`` precedence (not ``or``) keeps legitimately empty
    payloads from being skipped.
    """
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    return getattr(result, "data", None)


class _RendezvousNetworkHandler(http.server.BaseHTTPRequestHandler):
    """Canned 200 for any GET, but ``stat/health`` requests rendezvous first.

    Each health request bumps a shared counter and then blocks on a release
    Event; only once ``_CONCURRENCY`` of them have arrived does the last set the
    Event, freeing them all to answer together. Progress is therefore possible
    *only* if the requests are genuinely in flight at the same time — serialised
    calls would never reach the target count and would each sit on the backstop.
    The ``stat/sysinfo`` startup probe takes neither branch, so the server boots
    without touching the rendezvous.
    """

    def do_GET(self) -> None:
        server: Any = self.server
        if "health" in self.path:
            with server.arrival_lock:
                server.arrivals += 1
                if server.arrivals >= _CONCURRENCY:
                    server.all_arrived.set()
            # Backstop so a never-completing rendezvous can't wedge the handler
            # thread forever. Longer than the client-side ``_RENDEZVOUS_TIMEOUT``
            # so that bound is what fails the test on a serialising pool.
            server.all_arrived.wait(timeout=30)
        body = json.dumps(_CANNED_BODY).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # On the failure path the client tears down before a backstop-
            # released handler writes its late response, closing the socket;
            # the write then fails. Expected during teardown, not a test failure.
            pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002 — http.server API
        return


class _RendezvousMockHTTPSServer:
    """Threaded HTTPS mock that holds ``stat/health`` GETs until ``_CONCURRENCY`` arrive.

    Threaded for the same reason as the mode-flip mock cannot be: a
    single-threaded server serialises requests, so the rendezvous could never
    fill and the mock itself would defeat the property under test.
    ``ThreadingHTTPServer`` gives each request its own daemon thread.
    """

    def __init__(self, cert_path: Path, key_path: Path) -> None:
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RendezvousNetworkHandler)
        self._server.daemon_threads = True
        self._server.arrival_lock = threading.Lock()  # type: ignore[attr-defined]
        self._server.arrivals = 0  # type: ignore[attr-defined]
        self._server.all_arrived = threading.Event()  # type: ignore[attr-defined]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self._server.socket = ctx.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        port: int = self._server.server_address[1]
        return port

    @property
    def arrivals(self) -> int:
        count: int = self._server.arrivals  # type: ignore[attr-defined]
        return count

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        # Release any handler still waiting on the rendezvous so its thread can
        # exit instead of sitting on the 30s backstop.
        self._server.all_arrived.set()  # type: ignore[attr-defined]
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def rendezvous_mock_server(tmp_path: Path) -> Iterator[_RendezvousMockHTTPSServer]:
    """HTTPS mock that holds ``stat/health`` GETs until ``_CONCURRENCY`` arrive."""
    cert_pem, key_pem = _generate_self_signed_cert("127.0.0.1")
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server.key"
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)

    server = _RendezvousMockHTTPSServer(cert_path=cert_path, key_path=key_path)
    server.start()
    try:
        yield server
    finally:
        server.stop()


class TestStdioConcurrentToolCalls:
    """Fire many ``tools/call`` simultaneously over the real stdio boundary.

    Closes the "concurrent tool calls — no stress test" slice of §4 in #97. The
    Network client re-uses one ``httpx.AsyncClient`` across calls, so every
    concurrent tool call shares its connection pool; this proves the pool serves
    simultaneous in-flight requests without serialising or corrupting them.
    """

    async def test_concurrent_calls_share_pool_without_corruption(
        self,
        rendezvous_mock_server: _RendezvousMockHTTPSServer,
    ) -> None:
        """``_CONCURRENCY`` simultaneous calls must all complete with identical,
        well-formed results, then leave the session usable.

        The mock answers a health request only once all ``_CONCURRENCY`` have
        arrived, so the gather can resolve *only* if the calls are genuinely
        concurrent through the shared pool — a serialising pool (or a server that
        handles ``tools/call`` one at a time) stalls the rendezvous and trips
        ``_RENDEZVOUS_TIMEOUT``. Equal payloads across all results guard against
        responses crossing between in-flight calls.
        """
        command = shutil.which("unifi-mcp")
        if command is None:
            pytest.skip("unifi-mcp console script not on PATH; run `uv sync` first")

        with tempfile.TemporaryDirectory(prefix="unifi-mcp-stdio-concurrent-") as cwd:
            transport = StdioTransport(
                command=command,
                args=[],
                env=_mode_flip_env(mode="readonly", network_port=rendezvous_mock_server.port),
                cwd=cwd,
            )
            async with Client(transport) as client:
                assert client.is_connected(), "client failed to connect over stdio"

                tool_names = {t.name for t in await client.list_tools()}
                assert _CONCURRENT_TOOL in tool_names, (
                    f"{_CONCURRENT_TOOL!r} did not register; mock backend or env wiring is broken — "
                    f"got tools: {sorted(tool_names)!r}"
                )

                tasks = [asyncio.create_task(client.call_tool(_CONCURRENT_TOOL, {})) for _ in range(_CONCURRENCY)]
                try:
                    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=_RENDEZVOUS_TIMEOUT)
                except TimeoutError:
                    for task in tasks:
                        task.cancel()
                    pytest.fail(
                        f"{_CONCURRENCY} concurrent calls failed to rendezvous within "
                        f"{_RENDEZVOUS_TIMEOUT}s — only {rendezvous_mock_server.arrivals} of "
                        f"{_CONCURRENCY} requests reached the upstream; tool calls are being "
                        "serialised rather than sharing the connection pool"
                    )

                payloads = [_result_payload(r) for r in results]
                assert all(p is not None for p in payloads), (
                    f"a concurrent call returned an empty payload: {payloads!r}"
                )
                first = payloads[0]
                assert all(p == first for p in payloads), (
                    "concurrent calls returned differing payloads — a response crossed between "
                    f"in-flight requests: {payloads!r}"
                )
                assert "8.0.0" in json.dumps(first), (
                    f"payload is not the canned health body — wrong response routed back: {first!r}"
                )

                # The session must still be alive after the burst: a fresh
                # request over the same stdio connection has to succeed.
                tools_after = await client.list_tools()
                assert _CONCURRENT_TOOL in {t.name for t in tools_after}, (
                    "session unusable after a burst of concurrent tool calls"
                )

            assert not client.is_connected(), "client still connected after context exit"

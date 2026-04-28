"""Shared fixtures for live-hardware integration tests.

All tests in this directory are tagged ``@pytest.mark.integration`` and
excluded from CI. Run them manually against a configured controller:

    uv run pytest tests/integration/ -v -m integration

Fixtures skip gracefully if the matching ``UNIFI_*_API`` env var is not set,
so a contributor with only Network credentials won't be forced to stub out
Protect / Site Manager.
"""

from __future__ import annotations

import inspect
import logging
import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from unifi_mcp.clients.network import NetworkClient
from unifi_mcp.clients.protect import ProtectClient
from unifi_mcp.clients.site_manager import SiteManagerClient

LOG = logging.getLogger(__name__)


def _csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _network_host() -> str:
    return os.environ.get("UNIFI_NETWORK_HOST", "192.168.1.1")


def _network_port() -> int:
    return int(os.environ.get("UNIFI_NETWORK_PORT", "443"))


def _protect_host() -> str:
    return os.environ.get("UNIFI_PROTECT_HOST", _network_host())


def _protect_port() -> int:
    return int(os.environ.get("UNIFI_PROTECT_PORT", "443"))


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture
async def network_live_client():
    """Live NetworkClient. Skips if UNIFI_NETWORK_API is unset."""
    api_key = os.environ.get("UNIFI_NETWORK_API")
    if not api_key:
        pytest.skip("UNIFI_NETWORK_API not set; skipping live Network test")
    site = os.environ.get("UNIFI_NETWORK_SITE", "default")
    client = NetworkClient(
        base_url=f"https://{_network_host()}:{_network_port()}",
        api_key=api_key,
        site=site,
        verify_ssl=_bool_env("UNIFI_NETWORK_VERIFY_SSL"),
        timeout=int(os.environ.get("UNIFI_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.environ.get("UNIFI_MAX_RETRIES", "3")),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def protect_live_client():
    """Live ProtectClient. Skips if UNIFI_PROTECT_API is unset."""
    api_key = os.environ.get("UNIFI_PROTECT_API")
    if not api_key:
        pytest.skip("UNIFI_PROTECT_API not set; skipping live Protect test")
    client = ProtectClient(
        base_url=f"https://{_protect_host()}:{_protect_port()}",
        api_key=api_key,
        verify_ssl=_bool_env("UNIFI_PROTECT_VERIFY_SSL"),
        timeout=int(os.environ.get("UNIFI_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.environ.get("UNIFI_MAX_RETRIES", "3")),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def site_manager_live_client():
    """Live SiteManagerClient. Skips if UNIFI_SITE_MANAGER_API is unset."""
    api_key = os.environ.get("UNIFI_SITE_MANAGER_API")
    if not api_key:
        pytest.skip("UNIFI_SITE_MANAGER_API not set; skipping live Site Manager test")
    client = SiteManagerClient(
        api_key=api_key,
        timeout=int(os.environ.get("UNIFI_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.environ.get("UNIFI_MAX_RETRIES", "3")),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture(scope="session")
async def network_live_client_session():
    """Session-scoped Network client for fixtures that outlive a single test
    (test_vlan_id, default_lan_id, etc.). Tests should keep using the
    function-scoped network_live_client; this fixture exists only for
    other session-scoped fixtures."""
    api_key = os.environ.get("UNIFI_NETWORK_API")
    if not api_key:
        pytest.skip("UNIFI_NETWORK_API not set; skipping live Network test")
    site = os.environ.get("UNIFI_NETWORK_SITE", "default")
    client = NetworkClient(
        base_url=f"https://{_network_host()}:{_network_port()}",
        api_key=api_key,
        site=site,
        verify_ssl=_bool_env("UNIFI_NETWORK_VERIFY_SSL"),
        timeout=int(os.environ.get("UNIFI_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.environ.get("UNIFI_MAX_RETRIES", "3")),
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture(scope="session")
async def protected_macs(network_live_client_session: NetworkClient) -> frozenset[str]:
    """MACs that must NEVER be modified. Set via UNIFI_MCP_TEST_PROTECTED_MACS.

    Fail-fast (with a printed device list) if unset.
    """
    raw = _csv_env("UNIFI_MCP_TEST_PROTECTED_MACS")
    if not raw:
        devices = await network_live_client_session.list_devices()
        rows = [
            f"  {d.get('mac', '?')}  {d.get('name', '?')}  ({d.get('model', '?')})"
            for d in devices.get("data", [])
        ]
        msg = (
            "UNIFI_MCP_TEST_PROTECTED_MACS is unset. The integration suite refuses\n"
            "to run write tools without an explicit protected-device allowlist.\n\n"
            "Available devices on this controller:\n"
            + "\n".join(rows)
            + "\n\nSet UNIFI_MCP_TEST_PROTECTED_MACS to the comma-separated MACs of\n"
            "your gateway, uplinked switch, and uplinked AP, then rerun."
        )
        pytest.fail(msg)
    LOG.warning("Protected MACs (will not be touched): %s", ", ".join(raw))
    return frozenset(raw)


@pytest.fixture(scope="session")
def test_target_mac(protected_macs: frozenset[str]) -> str:
    """MAC of the designated downstream device for disruptive device-action tests.

    Skips dependent tests if UNIFI_MCP_TEST_TARGET_MAC unset.
    Asserts target not in protected_macs.
    """
    target = os.environ.get("UNIFI_MCP_TEST_TARGET_MAC", "").strip().lower()
    if not target:
        pytest.skip("UNIFI_MCP_TEST_TARGET_MAC unset; skipping device-action tests")
    if target in protected_macs:
        pytest.fail(
            f"UNIFI_MCP_TEST_TARGET_MAC={target} overlaps protected_macs. Refusing to run."
        )
    return target


@pytest.fixture(scope="session")
def test_client_mac() -> str:
    """MAC of the test client for kick/block/unblock flows.

    Skips dependent tests if UNIFI_MCP_TEST_CLIENT_MAC unset.
    """
    mac = os.environ.get("UNIFI_MCP_TEST_CLIENT_MAC", "").strip().lower()
    if not mac:
        pytest.skip("UNIFI_MCP_TEST_CLIENT_MAC unset; skipping client-action tests")
    return mac


@pytest.fixture(scope="session")
async def default_lan_id(network_live_client_session: NetworkClient) -> str:
    """_id of the default corporate network. Networks-domain tests must
    never target this. Fails the suite if no default LAN is found.
    """
    networks = await network_live_client_session.list_networks()
    for net in networks.get("data", []):
        if net.get("purpose") == "corporate" and net.get("is_default") is True:
            lan_id = net.get("_id")
            assert isinstance(lan_id, str), "default LAN _id missing or wrong type"
            LOG.warning("Default LAN _id (off-limits to write tests): %s", lan_id)
            return lan_id
    pytest.fail("No corporate is_default network found; refusing to run write tests.")


@pytest.fixture(scope="session")
def mcptest_prefix() -> str:
    """All test artifacts named {prefix}{domain}-{uuid4-hex[:8]}.
    Default: 'mcptest-'. Override via UNIFI_MCP_TEST_PREFIX.
    Session-scoped because session fixtures depend on it.
    """
    return os.environ.get("UNIFI_MCP_TEST_PREFIX", "mcptest-").strip()


@pytest.fixture
async def cleanup_register():
    """Per-test stack-based cleanup. register(callable, *args, **kwargs)
    pushes a deferred call; finally pops in LIFO order, best-effort runs,
    logs WARNING on failure. Never raises (would mask the test's real failure).
    """
    stack: list[tuple[Callable[..., object], tuple[object, ...], dict[str, object]]] = []

    def register(fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        stack.append((fn, args, kwargs))

    try:
        yield register
    finally:
        while stack:
            fn, args, kwargs = stack.pop()
            try:
                result = fn(*args, **kwargs)
                if inspect.iscoroutine(result):
                    await result
            except Exception as exc:
                LOG.warning("cleanup_register: %s(%s) failed: %s", fn.__name__, args, exc)


@pytest.fixture(scope="session")
async def test_vlan_id(
    network_live_client_session,
    mcptest_prefix: str,
):
    """Session-scoped sandbox VLAN for dependent tests (wlan, port-profiles,
    firewall rules, port-forwards). Created in 90-99 range using lowest
    unused ID. Skipped (not failed) if creation fails.
    """
    existing = await network_live_client_session.list_networks()
    used_vlans = {n.get("vlan") for n in existing.get("data", []) if n.get("vlan")}
    chosen = next((v for v in range(90, 100) if v not in used_vlans), None)
    if chosen is None:
        pytest.skip("VLAN IDs 90-99 are all in use; cannot create sandbox VLAN.")

    name = f"{mcptest_prefix}vlan-{chosen}"
    try:
        created = await network_live_client_session.create_network(
            name=name,
            purpose="corporate",
            vlan=chosen,
            ip_subnet=f"10.99.{chosen}.1/24",
            dhcp_enabled=False,
        )
    except Exception as exc:
        pytest.skip(f"Failed to create sandbox VLAN: {exc}")

    vlan_doc = (created.get("data") or [{}])[0]
    network_id = vlan_doc.get("_id")
    if not isinstance(network_id, str):
        pytest.skip(f"Sandbox VLAN response missing _id: {created}")

    LOG.warning("Sandbox VLAN created: id=%s vlan=%d name=%s", network_id, chosen, name)
    try:
        yield network_id
    finally:
        try:
            await network_live_client_session.delete_network(network_id)
            LOG.warning("Sandbox VLAN deleted: %s", network_id)
        except Exception as exc:
            LOG.warning("Sandbox VLAN cleanup failed (id=%s): %s", network_id, exc)

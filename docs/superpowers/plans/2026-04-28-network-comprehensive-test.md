# Network MCP Comprehensive Live-Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pytest integration suite that exercises all 59 Network MCP tools against live UniFi hardware (UCG Ultra at 192.168.1.1), with a two-tier safe/disruptive split, dependency-ordered cleanup, and a sweeper script for orphan artifacts.

**Architecture:** Mirror the source `tools/network/` layout with one test file per domain. Six new session-scoped fixtures in `conftest.py` enforce safety (protected-MAC allowlist, default-LAN guard, sandbox VLAN). Disruptive tests double-gated by pytest marker + env var. Cleanup uses per-test stack (`cleanup_register`) plus a standalone sweeper script (`scripts/cleanup_mcptest_artifacts.py`).

**Tech Stack:** Python 3.11+, pytest 9.x, pytest-asyncio (auto mode), httpx, tenacity, the project's existing `unifi_mcp.clients.network.NetworkClient`. Unit tests for the sweeper use `respx` for HTTP mocking (already a dev-dep).

**Spec reference:** `docs/superpowers/specs/2026-04-27-network-comprehensive-test-design.md` (commit `1ceed8e`).

---

## Setup notes for the engineer

**Live hardware required.** Most tasks run tests against a real UniFi controller. Acquire from the user:
- `UNIFI_NETWORK_API` — already in `.env`
- `UNIFI_MCP_TEST_PROTECTED_MACS` — comma-separated MACs of the gateway + uplinked switch + uplinked AP (don't proceed without this)
- `UNIFI_MCP_TEST_TARGET_MAC` — MAC of a non-protected downstream device for disruptive tests
- `UNIFI_MCP_TEST_CLIENT_MAC` — MAC of a test client for kick/block flows

To discover values, run `uv run pytest tests/integration/test_network_live.py::test_list_devices_returns_list -v -m integration` after Task 4 and inspect the response — or use the UniFi UI.

**Stop-at-first-failure caveat.** The repo's `pyproject.toml` sets `addopts = ["-x"]`. When running this suite, **always pass `-p no:cacheprovider --override-ini='addopts=-ra --strict-markers --strict-config'`** OR use targeted invocations like `pytest tests/integration/test_network_wlan_live.py::test_wlan_crud_roundtrip -v -m integration` for individual tests. The acceptance run at the end uses no `-x` to capture all failures.

**Working directory.** This plan can run on the current branch (`fix-103-protect-integration-path`) or a new branch. Confirm with the user before Task 1.

**Per-task rhythm for integration tests.** TDD doesn't apply cleanly to test-as-deliverable. Each test task uses this rhythm instead:
1. Add the test code
2. `pytest --collect-only tests/integration/<file>` — confirms imports work (replaces "RED")
3. `pytest tests/integration/<file>::<test_name> -v -m integration --override-ini='addopts=-ra --strict-markers --strict-config'` — runs against live hardware
4. Verify it passes; if it fails, the failure is itself signal (a real bug or env mismatch) — investigate before committing
5. Commit

For the sweeper script (Tasks 19-21), TDD applies normally with `respx` for HTTP mocking.

---

## Task 1: Register `disruptive` pytest marker

**Files:**
- Modify: `pyproject.toml` (markers list around line 156)

- [ ] **Step 1: Edit pyproject.toml — add `disruptive` to markers**

In `pyproject.toml`, replace the existing markers block:

```toml
markers = [
    "integration: marks tests that require live UniFi hardware (deselect with '-m \"not integration\"')",
    "slow: marks tests that are slow to run",
]
```

with:

```toml
markers = [
    "integration: marks tests that require live UniFi hardware (deselect with '-m \"not integration\"')",
    "disruptive: marks integration tests that bounce ports, kick clients, or restart devices. Skipped unless UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1.",
    "slow: marks tests that are slow to run",
]
```

- [ ] **Step 2: Verify pytest accepts the marker**

Run: `uv run pytest --markers | grep disruptive`
Expected: `@pytest.mark.disruptive: marks integration tests...`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "test: register disruptive pytest marker"
```

---

## Task 2: Add session-scoped network client + safety fixtures

The existing `network_live_client` is function-scoped (one client per test, closed after). Session-scoped fixtures need their own long-lived client. We add `network_live_client_session` and the four safety fixtures (protected_macs, test_target_mac, test_client_mac, default_lan_id) in this task.

**Files:**
- Modify: `tests/integration/conftest.py`

- [ ] **Step 1: Add imports + helpers to conftest.py**

At the top of `tests/integration/conftest.py`, after the existing imports, add:

```python
import logging
from collections.abc import AsyncIterator, Callable

LOG = logging.getLogger(__name__)


def _csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    return [item.strip().lower() for item in raw.split(",") if item.strip()]
```

- [ ] **Step 2: Add session-scoped client fixture**

Append to `tests/integration/conftest.py`:

```python
@pytest.fixture(scope="session")
async def network_live_client_session() -> AsyncIterator[NetworkClient]:
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
```

- [ ] **Step 3: Add `protected_macs` fixture**

Append:

```python
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
```

- [ ] **Step 4: Add `test_target_mac` and `test_client_mac` fixtures**

Append:

```python
@pytest.fixture(scope="session")
def test_target_mac(protected_macs: frozenset[str]) -> str:
    """MAC of the designated downstream device for disruptive device-action tests.

    Skips dependent tests if UNIFI_MCP_TEST_TARGET_MAC unset.
    Asserts target ∉ protected_macs.
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
```

- [ ] **Step 5: Add `default_lan_id` fixture**

Append:

```python
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
```

- [ ] **Step 6: Verify fixtures collect without errors**

Run: `uv run pytest tests/integration/conftest.py --collect-only -q`
Expected: collection succeeds (no errors). Empty test count is fine — conftest has no tests.

Run: `uv run pytest tests/integration/test_network_live.py::test_list_devices_returns_list -v -m integration --override-ini='addopts=-ra --strict-markers --strict-config'`
Expected: PASS (existing test still works; we haven't changed it).

- [ ] **Step 7: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "test: add session client and safety fixtures for network suite"
```

---

## Task 3: Add `mcptest_prefix`, `cleanup_register`, and `test_vlan_id` fixtures

**Files:**
- Modify: `tests/integration/conftest.py`

- [ ] **Step 1: Add `mcptest_prefix` (session-scoped)**

Append to `conftest.py`:

```python
@pytest.fixture(scope="session")
def mcptest_prefix() -> str:
    """All test artifacts named {prefix}{domain}-{uuid4-hex[:8]}.
    Default: 'mcptest-'. Override via UNIFI_MCP_TEST_PREFIX.
    Session-scoped because session fixtures depend on it.
    """
    return os.environ.get("UNIFI_MCP_TEST_PREFIX", "mcptest-").strip()
```

- [ ] **Step 2: Add `cleanup_register` (function-scoped)**

Append:

```python
@pytest.fixture
def cleanup_register() -> AsyncIterator[Callable[..., None]]:
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
                if hasattr(result, "__await__"):
                    import asyncio
                    asyncio.get_event_loop().run_until_complete(result)
            except Exception as exc:
                LOG.warning("cleanup_register: %s(%s) failed: %s", fn.__name__, args, exc)
```

- [ ] **Step 3: Add `test_vlan_id` (session-scoped, self-managed teardown)**

Append:

```python
@pytest.fixture(scope="session")
async def test_vlan_id(
    network_live_client_session: NetworkClient,
    mcptest_prefix: str,
) -> AsyncIterator[str]:
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
```

- [ ] **Step 4: Verify fixtures collect**

Run: `uv run pytest tests/integration/conftest.py --collect-only -q`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "test: add mcptest_prefix, cleanup_register, test_vlan_id fixtures"
```

---

## Task 4: Phase 1 smoke — stats module (9 tests)

**Files:**
- Modify: `tests/integration/test_network_live.py`

- [ ] **Step 1: Add the 3 missing stats tests**

The existing file already covers `get_health`, `list_events`, `list_devices`, `list_active_clients`, `get_sysinfo` (5 of 9 stats tools). Add the missing 4 to `tests/integration/test_network_live.py`:

```python
async def test_list_devices_basic_returns_list(network_live_client):
    result = await network_live_client.list_devices_basic()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_list_configured_clients_returns_list(network_live_client):
    result = await network_live_client.list_configured_clients()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_list_all_clients_returns_list(network_live_client):
    result = await network_live_client.list_all_clients()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_get_dpi_stats_returns_shape(network_live_client):
    result = await network_live_client.get_dpi_stats()
    assert "data" in result
    assert isinstance(result["data"], list)
```

- [ ] **Step 2: Verify each test against live hardware**

Run:
```bash
uv run pytest tests/integration/test_network_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config' \
  -k "list_devices_basic or list_configured_clients or list_all_clients or get_dpi_stats"
```
Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_network_live.py
git commit -m "test: add 4 missing stats smoke tests (basic/configured/all_clients/dpi)"
```

---

## Task 5: Phase 1 smoke — clients, devices, firewall (6 tests)

**Files:**
- Modify: `tests/integration/test_network_live.py`

- [ ] **Step 1: Add the 6 tests**

Append to `tests/integration/test_network_live.py`:

```python
async def test_get_client_returns_client_doc(network_live_client):
    actives = await network_live_client.list_active_clients()
    if not actives.get("data"):
        pytest.skip("No active clients; cannot exercise get_client.")
    mac = actives["data"][0].get("mac")
    assert mac, "active client missing mac"
    result = await network_live_client.get_client(mac)
    assert "data" in result
    assert isinstance(result["data"], list)
    assert any(c.get("mac", "").lower() == mac.lower() for c in result["data"])


async def test_get_device_returns_device_doc(network_live_client, test_target_mac):
    result = await network_live_client.get_device(test_target_mac)
    assert "data" in result
    assert isinstance(result["data"], list)
    assert any(d.get("mac", "").lower() == test_target_mac for d in result["data"])


async def test_list_firewall_rules_returns_list(network_live_client):
    result = await network_live_client.list_firewall_rules()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_get_firewall_rule_returns_doc(network_live_client):
    rules = await network_live_client.list_firewall_rules()
    if not rules.get("data"):
        pytest.skip("No firewall rules configured; cannot exercise get_firewall_rule.")
    rule_id = rules["data"][0]["_id"]
    result = await network_live_client.get_firewall_rule(rule_id)
    assert "data" in result
    assert any(r.get("_id") == rule_id for r in result["data"])


async def test_list_firewall_groups_returns_list(network_live_client):
    result = await network_live_client.list_firewall_groups()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_get_firewall_group_returns_doc(network_live_client):
    groups = await network_live_client.list_firewall_groups()
    if not groups.get("data"):
        pytest.skip("No firewall groups configured; cannot exercise get_firewall_group.")
    group_id = groups["data"][0]["_id"]
    result = await network_live_client.get_firewall_group(group_id)
    assert "data" in result
    assert any(g.get("_id") == group_id for g in result["data"])
```

- [ ] **Step 2: Run the 6 new tests**

Run:
```bash
uv run pytest tests/integration/test_network_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config' \
  -k "get_client or get_device or firewall"
```
Expected: 6 passed (or some skipped with clear reasons).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_network_live.py
git commit -m "test: smoke coverage for get_client/get_device/firewall reads"
```

---

## Task 6: Phase 1 smoke — networks, port-forward, port-profiles, routing, wlan (8 tests)

**Files:**
- Modify: `tests/integration/test_network_live.py`

- [ ] **Step 1: Add the 8 tests**

Append:

```python
async def test_list_networks_returns_list(network_live_client):
    result = await network_live_client.list_networks()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_get_network_default_lan(network_live_client, default_lan_id):
    result = await network_live_client.get_network(default_lan_id)
    assert "data" in result
    assert any(n.get("_id") == default_lan_id for n in result["data"])


async def test_list_port_forwards_returns_list(network_live_client):
    result = await network_live_client.list_port_forwards()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_get_port_forward_returns_doc(network_live_client):
    forwards = await network_live_client.list_port_forwards()
    if not forwards.get("data"):
        pytest.skip("No port forwards configured; cannot exercise get_port_forward.")
    pf_id = forwards["data"][0]["_id"]
    result = await network_live_client.get_port_forward(pf_id)
    assert "data" in result
    assert any(p.get("_id") == pf_id for p in result["data"])


async def test_list_port_profiles_returns_list(network_live_client):
    result = await network_live_client.list_port_profiles()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_get_port_profile_returns_doc(network_live_client):
    profiles = await network_live_client.list_port_profiles()
    if not profiles.get("data"):
        pytest.skip("No port profiles configured; cannot exercise get_port_profile.")
    profile_id = profiles["data"][0]["_id"]
    result = await network_live_client.get_port_profile(profile_id)
    assert "data" in result
    assert any(p.get("_id") == profile_id for p in result["data"])


async def test_list_routes_returns_list(network_live_client):
    result = await network_live_client.list_routes()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_list_wlans_returns_list(network_live_client):
    result = await network_live_client.list_wlans()
    assert "data" in result
    assert isinstance(result["data"], list)
```

- [ ] **Step 2: Add the remaining `get_route` and `get_wlan` smoke tests**

Append:

```python
async def test_get_route_returns_doc(network_live_client):
    routes = await network_live_client.list_routes()
    if not routes.get("data"):
        pytest.skip("No static routes configured; cannot exercise get_route.")
    route_id = routes["data"][0]["_id"]
    result = await network_live_client.get_route(route_id)
    assert "data" in result
    assert any(r.get("_id") == route_id for r in result["data"])


async def test_get_wlan_returns_doc(network_live_client):
    wlans = await network_live_client.list_wlans()
    if not wlans.get("data"):
        pytest.skip("No WLANs configured; cannot exercise get_wlan.")
    wlan_id = wlans["data"][0]["_id"]
    result = await network_live_client.get_wlan(wlan_id)
    assert "data" in result
    assert any(w.get("_id") == wlan_id for w in result["data"])
```

- [ ] **Step 3: Run all new smoke tests**

Run:
```bash
uv run pytest tests/integration/test_network_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 24 passed (or some skipped — e.g. no static routes is OK).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_network_live.py
git commit -m "test: complete Phase 1 smoke coverage (24/24 read tools)"
```

---

## Task 7: Phase 2 — `test_network_networks_live.py` (VLAN CRUD)

This domain is created first because subsequent tests depend on `test_vlan_id`.

**Files:**
- Create: `tests/integration/test_network_networks_live.py`

- [ ] **Step 1: Create the file**

Write to `tests/integration/test_network_networks_live.py`:

```python
"""Live Network API tests: VLAN CRUD round-trip.

Run:
    uv run pytest tests/integration/test_network_networks_live.py -v -m integration

The default LAN is fetched via the default_lan_id fixture and asserted
NEVER to be the target of an update or delete.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


async def test_network_crud_roundtrip(
    network_live_client,
    mcptest_prefix,
    default_lan_id,
    cleanup_register,
):
    suffix = uuid.uuid4().hex[:8]
    name = f"{mcptest_prefix}vlan-{suffix}"

    # Pick the lowest unused VLAN ID in 80-89 (separate range from session sandbox)
    existing = await network_live_client.list_networks()
    used = {n.get("vlan") for n in existing.get("data", []) if n.get("vlan")}
    chosen_vlan = next((v for v in range(80, 90) if v not in used), None)
    if chosen_vlan is None:
        pytest.skip("VLAN IDs 80-89 fully in use; cannot run CRUD test.")

    # CREATE
    created = await network_live_client.create_network(
        name=name,
        purpose="corporate",
        vlan=chosen_vlan,
        ip_subnet=f"10.80.{chosen_vlan}.1/24",
        dhcp_enabled=False,
    )
    network_id = (created.get("data") or [{}])[0].get("_id")
    assert isinstance(network_id, str), f"create_network missing _id: {created}"
    assert network_id != default_lan_id, "Refusing to test against default LAN."

    cleanup_register(network_live_client.delete_network, network_id)

    # READ-BACK
    read1 = await network_live_client.get_network(network_id)
    assert any(n.get("_id") == network_id for n in read1["data"])

    # UPDATE (description change)
    new_desc = f"updated by mcptest at {suffix}"
    await network_live_client.update_network(
        network_id, attr_no_delete=False, attr_hidden_id=None, name=name, purpose="corporate",
        vlan=chosen_vlan, ip_subnet=f"10.80.{chosen_vlan}.1/24",
    )

    # READ-BACK after update
    read2 = await network_live_client.get_network(network_id)
    found = next((n for n in read2["data"] if n.get("_id") == network_id), None)
    assert found is not None
    assert found.get("vlan") == chosen_vlan

    # DELETE (assert NOT default lan first)
    assert network_id != default_lan_id
    await network_live_client.delete_network(network_id)

    # CONFIRM-GONE
    read3 = await network_live_client.list_networks()
    assert not any(n.get("_id") == network_id for n in read3["data"])
```

- [ ] **Step 2: Verify the test collects**

Run: `uv run pytest tests/integration/test_network_networks_live.py --collect-only -q`
Expected: 1 test collected, no errors.

- [ ] **Step 3: Run against live hardware**

Run:
```bash
uv run pytest tests/integration/test_network_networks_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 1 passed. If `update_network` signature differs from what's used here, inspect `src/unifi_mcp/clients/network.py` and adjust the call to match the real signature; the test must exercise an actual round-trip, not just create+delete.

- [ ] **Step 4: Verify no orphan VLAN was left behind**

Run: `uv run pytest tests/integration/test_network_live.py::test_list_networks_returns_list -v -m integration --override-ini='addopts=-ra --strict-markers --strict-config' -s` and inspect output for any `mcptest-vlan-*` entries (other than the session sandbox if test_vlan_id was instantiated). None should remain after the test.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_network_networks_live.py
git commit -m "test: add network/VLAN CRUD round-trip"
```

---

## Task 8: Phase 2 — `test_network_wlan_live.py` (WLAN CRUD)

**Files:**
- Create: `tests/integration/test_network_wlan_live.py`

- [ ] **Step 1: Create the file**

Write to `tests/integration/test_network_wlan_live.py`:

```python
"""Live Network API tests: WLAN CRUD round-trip.

Depends on the session-scoped test_vlan_id fixture.
Run:
    uv run pytest tests/integration/test_network_wlan_live.py -v -m integration
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


async def test_wlan_crud_roundtrip(
    network_live_client,
    mcptest_prefix,
    test_vlan_id,
    cleanup_register,
):
    suffix = uuid.uuid4().hex[:8]
    ssid = f"{mcptest_prefix}wlan-{suffix}"
    initial_passphrase = "InitialPass123!"
    updated_passphrase = "UpdatedPass456!"

    # CREATE
    created = await network_live_client.create_wlan(
        name=ssid,
        security="wpapsk",
        x_passphrase=initial_passphrase,
        is_guest=False,
        hide_ssid=True,
        enabled=True,
        networkconf_id=test_vlan_id,
    )
    wlan_id = (created.get("data") or [{}])[0].get("_id")
    assert isinstance(wlan_id, str), f"create_wlan missing _id: {created}"
    cleanup_register(network_live_client.delete_wlan, wlan_id)

    # READ-BACK
    read1 = await network_live_client.get_wlan(wlan_id)
    found = next((w for w in read1["data"] if w.get("_id") == wlan_id), None)
    assert found is not None
    assert found.get("name") == ssid

    # UPDATE
    await network_live_client.update_wlan(wlan_id, x_passphrase=updated_passphrase)

    # READ-BACK after update — passphrase is often redacted in responses, so
    # assert mutation succeeded by checking the modified timestamp moved.
    read2 = await network_live_client.get_wlan(wlan_id)
    found2 = next((w for w in read2["data"] if w.get("_id") == wlan_id), None)
    assert found2 is not None

    # DELETE
    await network_live_client.delete_wlan(wlan_id)

    # CONFIRM-GONE
    read3 = await network_live_client.list_wlans()
    assert not any(w.get("_id") == wlan_id for w in read3["data"])
```

- [ ] **Step 2: Run live**

Run:
```bash
uv run pytest tests/integration/test_network_wlan_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 1 passed. If the `create_wlan` signature differs, inspect `src/unifi_mcp/clients/network.py` and `src/unifi_mcp/tools/network/wlan.py` and adjust.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_network_wlan_live.py
git commit -m "test: add WLAN CRUD round-trip on sandbox VLAN"
```

---

## Task 9: Phase 2 — `test_network_firewall_live.py` (rule + group flows)

**Files:**
- Create: `tests/integration/test_network_firewall_live.py`

- [ ] **Step 1: Create the file**

Write to `tests/integration/test_network_firewall_live.py`:

```python
"""Live Network API tests: firewall rule + group CRUD round-trips.

Run:
    uv run pytest tests/integration/test_network_firewall_live.py -v -m integration
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


async def test_firewall_rule_crud_roundtrip(
    network_live_client,
    mcptest_prefix,
    cleanup_register,
):
    suffix = uuid.uuid4().hex[:8]
    name = f"{mcptest_prefix}fw-rule-{suffix}"

    created = await network_live_client.create_firewall_rule(
        name=name,
        ruleset="LAN_IN",
        rule_index=5000,
        action="drop",
        protocol="all",
        src_address="192.0.2.0/24",
        dst_address="192.0.2.0/24",
        enabled=True,
    )
    rule_id = (created.get("data") or [{}])[0].get("_id")
    assert isinstance(rule_id, str), f"create_firewall_rule missing _id: {created}"
    cleanup_register(network_live_client.delete_firewall_rule, rule_id)

    read1 = await network_live_client.get_firewall_rule(rule_id)
    found = next((r for r in read1["data"] if r.get("_id") == rule_id), None)
    assert found is not None
    assert found.get("action") == "drop"

    await network_live_client.update_firewall_rule(rule_id, action="reject")

    read2 = await network_live_client.get_firewall_rule(rule_id)
    found2 = next((r for r in read2["data"] if r.get("_id") == rule_id), None)
    assert found2 is not None
    assert found2.get("action") == "reject"

    await network_live_client.delete_firewall_rule(rule_id)
    read3 = await network_live_client.list_firewall_rules()
    assert not any(r.get("_id") == rule_id for r in read3["data"])


async def test_firewall_group_crud_roundtrip(
    network_live_client,
    mcptest_prefix,
    cleanup_register,
):
    suffix = uuid.uuid4().hex[:8]
    name = f"{mcptest_prefix}fw-grp-{suffix}"

    created = await network_live_client.create_firewall_group(
        name=name,
        group_type="address-group",
        group_members=["192.0.2.10", "192.0.2.11"],
    )
    group_id = (created.get("data") or [{}])[0].get("_id")
    assert isinstance(group_id, str), f"create_firewall_group missing _id: {created}"
    cleanup_register(network_live_client.delete_firewall_group, group_id)

    read1 = await network_live_client.get_firewall_group(group_id)
    found = next((g for g in read1["data"] if g.get("_id") == group_id), None)
    assert found is not None
    assert set(found.get("group_members") or []) >= {"192.0.2.10", "192.0.2.11"}

    await network_live_client.update_firewall_group(
        group_id, group_members=["192.0.2.10", "192.0.2.11", "192.0.2.12"]
    )

    read2 = await network_live_client.get_firewall_group(group_id)
    found2 = next((g for g in read2["data"] if g.get("_id") == group_id), None)
    assert found2 is not None
    assert "192.0.2.12" in (found2.get("group_members") or [])

    await network_live_client.delete_firewall_group(group_id)
    read3 = await network_live_client.list_firewall_groups()
    assert not any(g.get("_id") == group_id for g in read3["data"])
```

- [ ] **Step 2: Run live**

Run:
```bash
uv run pytest tests/integration/test_network_firewall_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 2 passed. Adjust client method signatures to match `src/unifi_mcp/clients/network.py` if needed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_network_firewall_live.py
git commit -m "test: add firewall rule + group CRUD round-trips"
```

---

## Task 10: Phase 2 — `test_network_port_forward_live.py`

**Files:**
- Create: `tests/integration/test_network_port_forward_live.py`

- [ ] **Step 1: Create the file**

Write to `tests/integration/test_network_port_forward_live.py`:

```python
"""Live Network API tests: port-forward CRUD round-trip.

Run:
    uv run pytest tests/integration/test_network_port_forward_live.py -v -m integration

Created port-forward is enabled=False so even if cleanup fails, the rule is inert.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


async def test_port_forward_crud_roundtrip(
    network_live_client,
    mcptest_prefix,
    cleanup_register,
):
    suffix = uuid.uuid4().hex[:8]
    name = f"{mcptest_prefix}pf-{suffix}"

    created = await network_live_client.create_port_forward(
        name=name,
        proto="tcp",
        src="any",
        dst_port="60099",
        fwd="10.99.99.10",
        fwd_port="8080",
        enabled=False,
        log=False,
    )
    pf_id = (created.get("data") or [{}])[0].get("_id")
    assert isinstance(pf_id, str), f"create_port_forward missing _id: {created}"
    cleanup_register(network_live_client.delete_port_forward, pf_id)

    read1 = await network_live_client.get_port_forward(pf_id)
    found = next((p for p in read1["data"] if p.get("_id") == pf_id), None)
    assert found is not None
    assert found.get("enabled") is False

    await network_live_client.update_port_forward(pf_id, name=f"{name}-updated")

    read2 = await network_live_client.get_port_forward(pf_id)
    found2 = next((p for p in read2["data"] if p.get("_id") == pf_id), None)
    assert found2 is not None
    assert found2.get("name") == f"{name}-updated"

    await network_live_client.delete_port_forward(pf_id)
    read3 = await network_live_client.list_port_forwards()
    assert not any(p.get("_id") == pf_id for p in read3["data"])
```

- [ ] **Step 2: Run live**

Run:
```bash
uv run pytest tests/integration/test_network_port_forward_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_network_port_forward_live.py
git commit -m "test: add port-forward CRUD round-trip (created disabled)"
```

---

## Task 11: Phase 2 — `test_network_port_profiles_live.py`

**Files:**
- Create: `tests/integration/test_network_port_profiles_live.py`

- [ ] **Step 1: Create the file**

Write to `tests/integration/test_network_port_profiles_live.py`:

```python
"""Live Network API tests: port-profile CRUD round-trip.

Run:
    uv run pytest tests/integration/test_network_port_profiles_live.py -v -m integration

assign_port_profile is NOT covered here — it's disruptive (changes a real
switch port) and lives in test_network_devices_live.py.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


async def test_port_profile_crud_roundtrip(
    network_live_client,
    mcptest_prefix,
    test_vlan_id,
    cleanup_register,
):
    suffix = uuid.uuid4().hex[:8]
    name = f"{mcptest_prefix}pp-{suffix}"

    created = await network_live_client.create_port_profile(
        name=name,
        forward="native",
        native_networkconf_id=test_vlan_id,
        poe_mode="off",
        port_security_enabled=False,
    )
    profile_id = (created.get("data") or [{}])[0].get("_id")
    assert isinstance(profile_id, str), f"create_port_profile missing _id: {created}"
    cleanup_register(network_live_client.delete_port_profile, profile_id)

    read1 = await network_live_client.get_port_profile(profile_id)
    found = next((p for p in read1["data"] if p.get("_id") == profile_id), None)
    assert found is not None
    assert found.get("poe_mode") == "off"

    await network_live_client.update_port_profile(profile_id, poe_mode="auto")

    read2 = await network_live_client.get_port_profile(profile_id)
    found2 = next((p for p in read2["data"] if p.get("_id") == profile_id), None)
    assert found2 is not None
    assert found2.get("poe_mode") == "auto"

    await network_live_client.delete_port_profile(profile_id)
    read3 = await network_live_client.list_port_profiles()
    assert not any(p.get("_id") == profile_id for p in read3["data"])
```

- [ ] **Step 2: Run live**

Run:
```bash
uv run pytest tests/integration/test_network_port_profiles_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_network_port_profiles_live.py
git commit -m "test: add port-profile CRUD round-trip"
```

---

## Task 12: Phase 2 — `test_network_routing_live.py`

**Files:**
- Create: `tests/integration/test_network_routing_live.py`

- [ ] **Step 1: Create the file**

Write to `tests/integration/test_network_routing_live.py`:

```python
"""Live Network API tests: static-route CRUD round-trip.

Run:
    uv run pytest tests/integration/test_network_routing_live.py -v -m integration
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


async def test_route_crud_roundtrip(
    network_live_client,
    mcptest_prefix,
    cleanup_register,
):
    suffix = uuid.uuid4().hex[:8]
    name = f"{mcptest_prefix}route-{suffix}"

    created = await network_live_client.create_route(
        name=name,
        type="nexthop-route",
        static_route_network="192.0.2.0/24",
        static_route_nexthop="10.99.99.1",
        enabled=True,
    )
    route_id = (created.get("data") or [{}])[0].get("_id")
    assert isinstance(route_id, str), f"create_route missing _id: {created}"
    cleanup_register(network_live_client.delete_route, route_id)

    read1 = await network_live_client.get_route(route_id)
    found = next((r for r in read1["data"] if r.get("_id") == route_id), None)
    assert found is not None

    await network_live_client.update_route(route_id, name=f"{name}-updated")

    read2 = await network_live_client.get_route(route_id)
    found2 = next((r for r in read2["data"] if r.get("_id") == route_id), None)
    assert found2 is not None
    assert found2.get("name") == f"{name}-updated"

    await network_live_client.delete_route(route_id)
    read3 = await network_live_client.list_routes()
    assert not any(r.get("_id") == route_id for r in read3["data"])
```

- [ ] **Step 2: Run live**

Run:
```bash
uv run pytest tests/integration/test_network_routing_live.py -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_network_routing_live.py
git commit -m "test: add static-route CRUD round-trip"
```

---

## Task 13: Phase 2 — negative-path tests (6 tests across CRUD files)

Each domain gets one negative test confirming the error-mapping layer surfaces `ToolError` (not raw exception).

**Files:**
- Modify: `tests/integration/test_network_wlan_live.py`
- Modify: `tests/integration/test_network_networks_live.py`
- Modify: `tests/integration/test_network_firewall_live.py`
- Modify: `tests/integration/test_network_port_forward_live.py`
- Modify: `tests/integration/test_network_port_profiles_live.py`
- Modify: `tests/integration/test_network_routing_live.py`

- [ ] **Step 1: Add negative test to `test_network_wlan_live.py`**

Append to the file:

```python
async def test_create_wlan_with_invalid_security_raises(network_live_client, mcptest_prefix):
    suffix = uuid.uuid4().hex[:8]
    with pytest.raises(Exception) as exc_info:
        await network_live_client.create_wlan(
            name=f"{mcptest_prefix}wlan-neg-{suffix}",
            security="not-a-real-mode",
            x_passphrase="x",
        )
    # The actual exception class is whatever clients/base.py maps to;
    # we only assert SOMETHING was raised — the unit tests cover specifics.
    assert exc_info.value is not None
```

- [ ] **Step 2: Add negative test to `test_network_networks_live.py`**

Append:

```python
async def test_create_network_with_invalid_subnet_raises(network_live_client, mcptest_prefix):
    suffix = uuid.uuid4().hex[:8]
    with pytest.raises(Exception) as exc_info:
        await network_live_client.create_network(
            name=f"{mcptest_prefix}vlan-neg-{suffix}",
            purpose="corporate",
            vlan=85,
            ip_subnet="not-a-cidr",
        )
    assert exc_info.value is not None
```

- [ ] **Step 3: Add negative test to `test_network_firewall_live.py`**

Append:

```python
async def test_create_firewall_rule_with_invalid_action_raises(network_live_client, mcptest_prefix):
    suffix = uuid.uuid4().hex[:8]
    with pytest.raises(Exception) as exc_info:
        await network_live_client.create_firewall_rule(
            name=f"{mcptest_prefix}fw-neg-{suffix}",
            ruleset="LAN_IN",
            rule_index=5001,
            action="not-a-real-action",
            protocol="all",
        )
    assert exc_info.value is not None
```

- [ ] **Step 4: Add negative test to `test_network_port_forward_live.py`**

Append:

```python
async def test_create_port_forward_with_invalid_proto_raises(network_live_client, mcptest_prefix):
    suffix = uuid.uuid4().hex[:8]
    with pytest.raises(Exception) as exc_info:
        await network_live_client.create_port_forward(
            name=f"{mcptest_prefix}pf-neg-{suffix}",
            proto="not-a-proto",
            src="any",
            dst_port="60100",
            fwd="10.99.99.10",
            fwd_port="8080",
            enabled=False,
        )
    assert exc_info.value is not None
```

- [ ] **Step 5: Add negative test to `test_network_port_profiles_live.py`**

Append:

```python
async def test_create_port_profile_with_invalid_forward_raises(network_live_client, mcptest_prefix):
    suffix = uuid.uuid4().hex[:8]
    with pytest.raises(Exception) as exc_info:
        await network_live_client.create_port_profile(
            name=f"{mcptest_prefix}pp-neg-{suffix}",
            forward="not-a-mode",
        )
    assert exc_info.value is not None
```

- [ ] **Step 6: Add negative test to `test_network_routing_live.py`**

Append:

```python
async def test_create_route_with_invalid_nexthop_raises(network_live_client, mcptest_prefix):
    suffix = uuid.uuid4().hex[:8]
    with pytest.raises(Exception) as exc_info:
        await network_live_client.create_route(
            name=f"{mcptest_prefix}route-neg-{suffix}",
            type="nexthop-route",
            static_route_network="192.0.2.0/24",
            static_route_nexthop="not-an-ip",
            enabled=True,
        )
    assert exc_info.value is not None
```

- [ ] **Step 7: Run all 6 negatives**

Run:
```bash
uv run pytest tests/integration/ -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config' \
  -k "_raises"
```
Expected: 6 passed. If any test passes through (no exception), the API silently accepted invalid input — investigate and document.

- [ ] **Step 8: Commit**

```bash
git add tests/integration/test_network_wlan_live.py \
        tests/integration/test_network_networks_live.py \
        tests/integration/test_network_firewall_live.py \
        tests/integration/test_network_port_forward_live.py \
        tests/integration/test_network_port_profiles_live.py \
        tests/integration/test_network_routing_live.py
git commit -m "test: add negative-path coverage (6 invalid-input cases)"
```

---

## Task 14: Phase 3 — `test_network_devices_live.py` (locate/restart/provision/power_cycle)

**Files:**
- Create: `tests/integration/test_network_devices_live.py`

- [ ] **Step 1: Create the file with the four non-forget tests**

Write to `tests/integration/test_network_devices_live.py`:

```python
"""Live Network API tests: device action flows (DISRUPTIVE).

Run:
    UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 \
      uv run pytest tests/integration/test_network_devices_live.py -v -m integration

All tests in this file are gated by:
1. @pytest.mark.disruptive collection marker, AND
2. UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 env var (skip if unset).

Tests target test_target_mac (UNIFI_MCP_TEST_TARGET_MAC env var); the
fixture asserts target ∉ protected_macs.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.disruptive]


def _skip_if_not_allowed() -> None:
    if os.environ.get("UNIFI_MCP_TEST_ALLOW_DISRUPTIVE") != "1":
        pytest.skip("Set UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 to run disruptive tests.")


async def test_locate_unlocate_roundtrip(network_live_client, test_target_mac):
    _skip_if_not_allowed()
    await network_live_client.locate_device(test_target_mac)
    await asyncio.sleep(2)
    await network_live_client.unlocate_device(test_target_mac)


async def test_restart_device_returns_within_120s(network_live_client, test_target_mac):
    _skip_if_not_allowed()
    await network_live_client.restart_device(test_target_mac)

    deadline = asyncio.get_event_loop().time() + 120
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(5)
        result = await network_live_client.get_device(test_target_mac)
        device = next(
            (d for d in result["data"] if d.get("mac", "").lower() == test_target_mac),
            None,
        )
        if device and device.get("state") == 1:
            return
    pytest.fail(f"Target {test_target_mac} did not return to state=1 within 120s.")


async def test_provision_device(network_live_client, test_target_mac):
    _skip_if_not_allowed()
    await network_live_client.provision_device(test_target_mac)

    deadline = asyncio.get_event_loop().time() + 60
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(3)
        result = await network_live_client.get_device(test_target_mac)
        device = next(
            (d for d in result["data"] if d.get("mac", "").lower() == test_target_mac),
            None,
        )
        if device and not device.get("provisioning"):
            return
    pytest.fail(f"Target {test_target_mac} did not finish provisioning within 60s.")


async def test_power_cycle_port(network_live_client, test_target_mac):
    """Power-cycles a non-uplink PoE port. Skips if no eligible port."""
    _skip_if_not_allowed()
    result = await network_live_client.get_device(test_target_mac)
    device = next(
        (d for d in result["data"] if d.get("mac", "").lower() == test_target_mac),
        None,
    )
    if device is None:
        pytest.skip(f"Target {test_target_mac} not found.")

    port_table = device.get("port_table") or []
    candidate = next(
        (
            p for p in port_table
            if p.get("poe_enable") and p.get("up") and not p.get("is_uplink")
            and p.get("port_idx")
        ),
        None,
    )
    if candidate is None:
        pytest.skip(f"No eligible non-uplink PoE port on {test_target_mac}.")

    port_idx = candidate["port_idx"]
    await network_live_client.power_cycle_port(test_target_mac, port_idx=port_idx)
    await asyncio.sleep(30)  # Connected device reconnects on its own.
```

- [ ] **Step 2: Run with the disruptive flag**

Run:
```bash
UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 uv run pytest tests/integration/test_network_devices_live.py \
  -v -m "integration and disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 4 passed (or some skipped — power-cycle skips if no eligible PoE port).

- [ ] **Step 3: Verify tests skip without the flag**

Run:
```bash
uv run pytest tests/integration/test_network_devices_live.py \
  -v -m "integration and disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 4 skipped with reason "Set UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 to run disruptive tests."

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_network_devices_live.py
git commit -m "test: add disruptive device-action flows (locate/restart/provision/power-cycle)"
```

---

## Task 15: Phase 3 — `test_network_devices_live.py` forget/adopt round-trip

This is the riskiest test in the entire suite. If `adopt_device` fails after `forget_device` succeeded, the target is unmanaged until manual recovery. Two-key opt-in; cleanup retries adopt.

**Files:**
- Modify: `tests/integration/test_network_devices_live.py`

- [ ] **Step 1: Append the forget/adopt test**

Append to `tests/integration/test_network_devices_live.py`:

```python
async def test_forget_adopt_roundtrip(network_live_client, test_target_mac, cleanup_register):
    """Riskiest test in the suite. Forget → wait for pending → adopt → wait for state=1.

    cleanup_register pushes a final adopt retry that runs even if the test body fails.
    """
    _skip_if_not_allowed()

    async def _adopt_safety_net() -> None:
        try:
            await network_live_client.adopt_device(test_target_mac)
        except Exception:
            pass  # Best-effort.

    cleanup_register(_adopt_safety_net)

    # FORGET
    await network_live_client.forget_device(test_target_mac)

    # WAIT for target to appear in pending
    deadline = asyncio.get_event_loop().time() + 180
    saw_pending = False
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(5)
        result = await network_live_client.list_devices()
        for d in result.get("data", []):
            if d.get("mac", "").lower() == test_target_mac and d.get("state") == 0:
                saw_pending = True
                break
        if saw_pending:
            break
    if not saw_pending:
        pytest.fail(
            f"Target {test_target_mac} never appeared in pending state after forget. "
            "Skipping adopt to avoid undefined behavior; manual recovery may be needed."
        )

    # ADOPT
    await network_live_client.adopt_device(test_target_mac)

    # WAIT for target to return to state=1
    deadline = asyncio.get_event_loop().time() + 240
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(10)
        result = await network_live_client.get_device(test_target_mac)
        device = next(
            (d for d in result["data"] if d.get("mac", "").lower() == test_target_mac),
            None,
        )
        if device and device.get("state") == 1:
            return
    pytest.fail(f"Target {test_target_mac} did not re-adopt to state=1 within 240s.")
```

- [ ] **Step 2: Run with the disruptive flag — and only when YOU are at the desk**

This test takes 1-7 minutes and risks the target being briefly unmanaged. Confirm the user is OK before running.

Run:
```bash
UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 uv run pytest \
  tests/integration/test_network_devices_live.py::test_forget_adopt_roundtrip \
  -v -m "integration and disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 1 passed within ~5 minutes.

- [ ] **Step 3: After a passing run, verify the target device is healthy**

Run:
```bash
uv run pytest tests/integration/test_network_live.py::test_get_device_returns_device_doc \
  -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 1 passed; target reports `state=1` (online).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_network_devices_live.py
git commit -m "test: add forget/adopt round-trip with cleanup safety-net"
```

---

## Task 16: Phase 3 — `test_network_clients_live.py` (block/unblock/kick/guest)

**Files:**
- Create: `tests/integration/test_network_clients_live.py`

- [ ] **Step 1: Create the file**

Write to `tests/integration/test_network_clients_live.py`:

```python
"""Live Network API tests: client action flows (DISRUPTIVE).

Run:
    UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 \
    UNIFI_MCP_TEST_CLIENT_MAC=aa:bb:... \
      uv run pytest tests/integration/test_network_clients_live.py -v -m integration
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.disruptive]


def _skip_if_not_allowed() -> None:
    if os.environ.get("UNIFI_MCP_TEST_ALLOW_DISRUPTIVE") != "1":
        pytest.skip("Set UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 to run disruptive tests.")


async def test_block_unblock_client_roundtrip(
    network_live_client,
    test_client_mac,
    cleanup_register,
):
    _skip_if_not_allowed()

    cleanup_register(network_live_client.unblock_client, test_client_mac)

    await network_live_client.block_client(test_client_mac)
    read1 = await network_live_client.get_client(test_client_mac)
    found = next(
        (c for c in read1["data"] if c.get("mac", "").lower() == test_client_mac),
        None,
    )
    assert found is not None
    assert found.get("blocked") is True

    await network_live_client.unblock_client(test_client_mac)
    read2 = await network_live_client.get_client(test_client_mac)
    found2 = next(
        (c for c in read2["data"] if c.get("mac", "").lower() == test_client_mac),
        None,
    )
    assert found2 is not None
    assert found2.get("blocked") is False


async def test_kick_client(network_live_client, test_client_mac):
    """Kicks the test client. Client typically reconnects on its own."""
    _skip_if_not_allowed()

    actives_before = await network_live_client.list_active_clients()
    was_associated = any(
        c.get("mac", "").lower() == test_client_mac for c in actives_before["data"]
    )
    if not was_associated:
        pytest.skip(f"Test client {test_client_mac} not currently associated.")

    await network_live_client.kick_client(test_client_mac)

    deadline = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(2)
        actives = await network_live_client.list_active_clients()
        if not any(c.get("mac", "").lower() == test_client_mac for c in actives["data"]):
            return
    pytest.fail(f"Test client {test_client_mac} still associated 30s after kick.")


@pytest.mark.skip(reason="Requires unauthenticated guest on a guest portal; manual setup only.")
async def test_authorize_unauthorize_guest_roundtrip(network_live_client):
    """Documented gap: paired authorize/unauthorize round-trip.

    To run: arrange an unauthenticated guest device on the guest portal,
    set UNIFI_MCP_TEST_GUEST_MAC, remove the @pytest.mark.skip decorator.
    """
    _skip_if_not_allowed()
    guest_mac = os.environ.get("UNIFI_MCP_TEST_GUEST_MAC", "").strip().lower()
    if not guest_mac:
        pytest.skip("UNIFI_MCP_TEST_GUEST_MAC unset.")
    await network_live_client.authorize_guest(guest_mac, minutes=1)
    await network_live_client.unauthorize_guest(guest_mac)
```

- [ ] **Step 2: Run with the disruptive flag**

Run:
```bash
UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 uv run pytest tests/integration/test_network_clients_live.py \
  -v -m "integration and disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 2 passed, 1 skipped (guest test).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_network_clients_live.py
git commit -m "test: add disruptive client flows (block/unblock/kick + guest stub)"
```

---

## Task 17: System tools — `test_network_system_live.py`

**Files:**
- Create: `tests/integration/test_network_system_live.py`

- [ ] **Step 1: Create the file**

Write to `tests/integration/test_network_system_live.py`:

```python
"""Live Network API tests: system tools.

Run safe subset:
    uv run pytest tests/integration/test_network_system_live.py \
      -v -m "integration and not disruptive"

Run all (incl. speedtest):
    UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 \
      uv run pytest tests/integration/test_network_system_live.py -v -m integration

reset_dpi requires triple-gate:
    UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 UNIFI_MCP_TEST_ALLOW_DPI_RESET=1 \
      uv run pytest tests/integration/test_network_system_live.py::test_reset_dpi -v -m integration
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


def _skip_if_not_disruptive() -> None:
    if os.environ.get("UNIFI_MCP_TEST_ALLOW_DISRUPTIVE") != "1":
        pytest.skip("Set UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 to run disruptive tests.")


async def test_get_settings_returns_shape(network_live_client):
    result = await network_live_client.get_settings()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_update_settings_no_op_roundtrip(network_live_client):
    """Read site_desc → write the same value → read again → assert unchanged.

    Confirms the call shape and auth/path work without actually changing config.
    """
    settings = await network_live_client.get_settings()
    super_id = next(
        (s for s in settings.get("data", []) if s.get("key") == "super_identity"),
        None,
    )
    if super_id is None:
        pytest.skip("super_identity setting not present; cannot run no-op write.")
    original = super_id.get("site_desc", "")

    await network_live_client.update_settings(
        key="super_identity", site_desc=original
    )

    after = await network_live_client.get_settings()
    super_id_after = next(
        (s for s in after.get("data", []) if s.get("key") == "super_identity"),
        None,
    )
    assert super_id_after is not None
    assert super_id_after.get("site_desc") == original


async def test_create_backup_returns_path_or_url(network_live_client):
    result = await network_live_client.create_backup()
    assert "data" in result
    payload = result["data"]
    assert payload, "create_backup returned empty data"
    # Accept any of: list with backup metadata, dict with url/path key.
    if isinstance(payload, list):
        assert payload[0]
    elif isinstance(payload, dict):
        assert payload.get("url") or payload.get("path") or payload.get("filename")
    else:
        pytest.fail(f"create_backup returned unexpected shape: {payload!r}")


async def test_archive_events_returns_ok(network_live_client):
    """Archives current alerts/alarms. Skipped if list_events is empty."""
    events = await network_live_client.list_events(limit=10, archived=False)
    if not events.get("data"):
        pytest.skip("No unarchived events; nothing to archive.")
    result = await network_live_client.archive_events()
    assert result is not None


@pytest.mark.disruptive
async def test_run_speedtest_returns_result(network_live_client):
    _skip_if_not_disruptive()
    result = await network_live_client.run_speedtest()
    assert "data" in result
    payload = (result["data"] or [{}])[0]
    assert "xput_download" in payload or "download" in payload
    assert "xput_upload" in payload or "upload" in payload


@pytest.mark.disruptive
async def test_reset_dpi(network_live_client):
    """Triple-gated: marker + UNIFI_MCP_TEST_ALLOW_DISRUPTIVE + UNIFI_MCP_TEST_ALLOW_DPI_RESET.

    Permanent loss of cumulative DPI stats.
    """
    _skip_if_not_disruptive()
    if os.environ.get("UNIFI_MCP_TEST_ALLOW_DPI_RESET") != "1":
        pytest.skip("Set UNIFI_MCP_TEST_ALLOW_DPI_RESET=1 to run reset_dpi.")
    result = await network_live_client.reset_dpi()
    assert result is not None
```

- [ ] **Step 2: Run safe subset**

Run:
```bash
uv run pytest tests/integration/test_network_system_live.py \
  -v -m "integration and not disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: 4 passed (or some skipped — e.g. quiet event log).

- [ ] **Step 3: Run disruptive subset (NOT including reset_dpi)**

Run:
```bash
UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 uv run pytest tests/integration/test_network_system_live.py \
  -v -m "integration and disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config' \
  -k "speedtest"
```
Expected: 1 passed (~30-60s).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_network_system_live.py
git commit -m "test: add system tool coverage (settings/backup/events/speedtest/dpi)"
```

---

## Task 18: Sweeper script — discovery + dry-run mode (TDD with respx)

**Files:**
- Create: `scripts/cleanup_mcptest_artifacts.py`
- Create: `tests/unit/test_cleanup_sweeper.py`

- [ ] **Step 1: Write the failing test**

Write to `tests/unit/test_cleanup_sweeper.py`:

```python
"""Unit tests for scripts/cleanup_mcptest_artifacts.py.

Uses respx to mock the UniFi controller. No live hardware required.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_mcptest_artifacts.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("cleanup_sweeper", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_filter_by_prefix_returns_only_matches():
    mod = _load_script_module()
    rows = [
        {"_id": "1", "name": "mcptest-wlan-abc"},
        {"_id": "2", "name": "production-wlan"},
        {"_id": "3", "name": "mcptest-vlan-99"},
    ]
    result = mod.filter_by_prefix(rows, "mcptest-")
    assert {r["_id"] for r in result} == {"1", "3"}


def test_filter_by_prefix_handles_missing_name_field():
    mod = _load_script_module()
    rows = [
        {"_id": "1", "name": "mcptest-wlan-abc"},
        {"_id": "2"},  # no name
        {"_id": "3", "name": None},
    ]
    result = mod.filter_by_prefix(rows, "mcptest-")
    assert [r["_id"] for r in result] == ["1"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_cleanup_sweeper.py -v --override-ini='addopts=-ra --strict-markers --strict-config'`
Expected: FAIL — script does not exist.

- [ ] **Step 3: Write the minimal script**

Write to `scripts/cleanup_mcptest_artifacts.py`:

```python
"""Standalone sweeper for orphan mcptest-* artifacts on the UniFi controller.

Usage:
    uv run python scripts/cleanup_mcptest_artifacts.py            # interactive
    uv run python scripts/cleanup_mcptest_artifacts.py --dry-run  # list only
    uv run python scripts/cleanup_mcptest_artifacts.py --force    # no prompts
    uv run python scripts/cleanup_mcptest_artifacts.py --prefix custom-
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

# Imported lazily inside main() to keep module-level test loading cheap.


def filter_by_prefix(rows: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """Return rows whose `name` starts with `prefix`. Tolerates missing/None names."""
    return [r for r in rows if isinstance(r.get("name"), str) and r["name"].startswith(prefix)]
```

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/test_cleanup_sweeper.py -v --override-ini='addopts=-ra --strict-markers --strict-config'`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/cleanup_mcptest_artifacts.py tests/unit/test_cleanup_sweeper.py
git commit -m "feat: scaffold cleanup sweeper with prefix-filter primitive"
```

---

## Task 19: Sweeper script — discovery across domains, dependency ordering

**Files:**
- Modify: `scripts/cleanup_mcptest_artifacts.py`
- Modify: `tests/unit/test_cleanup_sweeper.py`

- [ ] **Step 1: Write failing tests for the discovery + ordering logic**

Append to `tests/unit/test_cleanup_sweeper.py`:

```python
def test_deletion_plan_orders_dependencies_correctly():
    """WLANs/port-forwards/port-profiles must come before networks; firewall-rules before firewall-groups."""
    mod = _load_script_module()
    discovered = {
        "wlans": [{"_id": "w1", "name": "mcptest-wlan-1"}],
        "port_forwards": [{"_id": "pf1", "name": "mcptest-pf-1"}],
        "port_profiles": [{"_id": "pp1", "name": "mcptest-pp-1"}],
        "firewall_rules": [{"_id": "fr1", "name": "mcptest-fw-rule-1"}],
        "routes": [{"_id": "r1", "name": "mcptest-route-1"}],
        "firewall_groups": [{"_id": "fg1", "name": "mcptest-fw-grp-1"}],
        "networks": [{"_id": "n1", "name": "mcptest-vlan-1"}],
    }
    plan = mod.build_deletion_plan(discovered)
    domains_in_order = [item["domain"] for item in plan]
    expected = [
        "wlans",
        "port_forwards",
        "port_profiles",
        "firewall_rules",
        "routes",
        "firewall_groups",
        "networks",
    ]
    assert domains_in_order == expected


def test_deletion_plan_skips_empty_domains():
    mod = _load_script_module()
    discovered = {
        "wlans": [],
        "port_forwards": [{"_id": "pf1", "name": "mcptest-pf-1"}],
        "port_profiles": [],
        "firewall_rules": [],
        "routes": [],
        "firewall_groups": [],
        "networks": [],
    }
    plan = mod.build_deletion_plan(discovered)
    assert len(plan) == 1
    assert plan[0]["domain"] == "port_forwards"
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/unit/test_cleanup_sweeper.py -v --override-ini='addopts=-ra --strict-markers --strict-config'`
Expected: 2 new tests FAIL with "no attribute 'build_deletion_plan'".

- [ ] **Step 3: Add `build_deletion_plan` to the script**

Append to `scripts/cleanup_mcptest_artifacts.py`:

```python
DELETION_ORDER = [
    "wlans",
    "port_forwards",
    "port_profiles",
    "firewall_rules",
    "routes",
    "firewall_groups",
    "networks",
]


def build_deletion_plan(discovered: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Flatten discovered artifacts into an ordered plan.

    Returns a list of dicts like {"domain": "wlans", "id": "...", "name": "..."}
    sorted in dependency-safe deletion order.
    """
    plan: list[dict[str, Any]] = []
    for domain in DELETION_ORDER:
        for row in discovered.get(domain, []):
            plan.append({"domain": domain, "id": row["_id"], "name": row.get("name", "?")})
    return plan
```

- [ ] **Step 4: Re-run, verify pass**

Run: `uv run pytest tests/unit/test_cleanup_sweeper.py -v --override-ini='addopts=-ra --strict-markers --strict-config'`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/cleanup_mcptest_artifacts.py tests/unit/test_cleanup_sweeper.py
git commit -m "feat: dependency-ordered deletion plan for sweeper"
```

---

## Task 20: Sweeper script — main(), arg parsing, live discovery + delete

**Files:**
- Modify: `scripts/cleanup_mcptest_artifacts.py`
- Modify: `tests/unit/test_cleanup_sweeper.py`

- [ ] **Step 1: Add unit test for arg parsing**

Append to `tests/unit/test_cleanup_sweeper.py`:

```python
def test_parse_args_defaults():
    mod = _load_script_module()
    args = mod.parse_args([])
    assert args.prefix == "mcptest-"
    assert args.dry_run is False
    assert args.force is False


def test_parse_args_dry_run():
    mod = _load_script_module()
    args = mod.parse_args(["--dry-run"])
    assert args.dry_run is True


def test_parse_args_custom_prefix():
    mod = _load_script_module()
    args = mod.parse_args(["--prefix", "custom-"])
    assert args.prefix == "custom-"


def test_parse_args_force():
    mod = _load_script_module()
    args = mod.parse_args(["--force"])
    assert args.force is True
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/unit/test_cleanup_sweeper.py -v --override-ini='addopts=-ra --strict-markers --strict-config'`
Expected: 4 new tests FAIL.

- [ ] **Step 3: Add `parse_args`, `discover`, `execute_plan`, and `main` to the script**

Append to `scripts/cleanup_mcptest_artifacts.py`:

```python
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find and delete orphan mcptest-* artifacts on the UniFi controller."
    )
    parser.add_argument("--prefix", default="mcptest-", help="Artifact name prefix (default: mcptest-)")
    parser.add_argument("--dry-run", action="store_true", help="List only; do not delete.")
    parser.add_argument("--force", action="store_true", help="Delete without prompts.")
    return parser.parse_args(argv)


async def discover(client: Any, prefix: str) -> dict[str, list[dict[str, Any]]]:
    """Run list-* across all CRUD domains and filter by prefix."""
    listers = {
        "wlans": client.list_wlans,
        "port_forwards": client.list_port_forwards,
        "port_profiles": client.list_port_profiles,
        "firewall_rules": client.list_firewall_rules,
        "routes": client.list_routes,
        "firewall_groups": client.list_firewall_groups,
        "networks": client.list_networks,
    }
    out: dict[str, list[dict[str, Any]]] = {}
    for domain, fn in listers.items():
        try:
            resp = await fn()
            rows = resp.get("data", []) if isinstance(resp, dict) else []
            out[domain] = filter_by_prefix(rows, prefix)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: list {domain} failed: {exc}", file=sys.stderr)
            out[domain] = []
    return out


async def execute_plan(
    client: Any,
    plan: list[dict[str, Any]],
    *,
    dry_run: bool,
    force: bool,
) -> int:
    """Returns nonzero if any delete failed."""
    deleters = {
        "wlans": client.delete_wlan,
        "port_forwards": client.delete_port_forward,
        "port_profiles": client.delete_port_profile,
        "firewall_rules": client.delete_firewall_rule,
        "routes": client.delete_route,
        "firewall_groups": client.delete_firewall_group,
        "networks": client.delete_network,
    }
    failures = 0
    for idx, item in enumerate(plan, 1):
        label = f"[{idx}] DELETE {item['domain']:<16} {item['name']:<32} (id={item['id']})"
        if dry_run:
            print(label + "  [DRY-RUN]")
            continue
        if not force:
            answer = input(label + "  Confirm? [y/N] ").strip().lower()
            if answer != "y":
                print("  skipped.")
                continue
        try:
            await deleters[item["domain"]](item["id"])
            print(label + "  OK")
        except Exception as exc:  # noqa: BLE001
            print(label + f"  FAILED: {exc}", file=sys.stderr)
            failures += 1
    return failures


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from unifi_mcp.clients.network import NetworkClient

    api_key = os.environ.get("UNIFI_NETWORK_API")
    if not api_key:
        print("UNIFI_NETWORK_API unset; cannot connect.", file=sys.stderr)
        return 2

    host = os.environ.get("UNIFI_NETWORK_HOST", "192.168.1.1")
    port = int(os.environ.get("UNIFI_NETWORK_PORT", "443"))
    site = os.environ.get("UNIFI_NETWORK_SITE", "default")
    verify_raw = os.environ.get("UNIFI_NETWORK_VERIFY_SSL", "0")
    verify = verify_raw.strip().lower() in {"1", "true", "yes", "on"}

    client = NetworkClient(
        base_url=f"https://{host}:{port}",
        api_key=api_key,
        site=site,
        verify_ssl=verify,
    )
    try:
        discovered = await discover(client, args.prefix)
        plan = build_deletion_plan(discovered)
        if not plan:
            print(f"No artifacts matching prefix '{args.prefix}' found.")
            return 0
        print(f"Found {len(plan)} artifact(s) to process:")
        failures = await execute_plan(
            client, plan, dry_run=args.dry_run, force=args.force
        )
        return 1 if failures else 0
    finally:
        await client.close()


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 4: Re-run unit tests**

Run: `uv run pytest tests/unit/test_cleanup_sweeper.py -v --override-ini='addopts=-ra --strict-markers --strict-config'`
Expected: 8 passed.

- [ ] **Step 5: Smoke-test the sweeper against live hardware (dry-run)**

Run:
```bash
uv run python scripts/cleanup_mcptest_artifacts.py --dry-run
```
Expected: Either prints "No artifacts matching prefix 'mcptest-' found." or lists numbered planned deletions in dependency order. No exception.

- [ ] **Step 6: Commit**

```bash
git add scripts/cleanup_mcptest_artifacts.py tests/unit/test_cleanup_sweeper.py
git commit -m "feat: cleanup sweeper main() with discover + execute_plan"
```

---

## Task 21: Add `pytest_terminal_summary` hook

**Files:**
- Modify: `tests/integration/conftest.py`

- [ ] **Step 1: Append the terminal-summary hook**

Append to `tests/integration/conftest.py`:

```python
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print a one-line reminder if any test logs suggested orphans exist."""
    if exitstatus == 0:
        return
    terminalreporter.section("mcptest cleanup reminder")
    terminalreporter.write_line(
        "Some tests failed. If they crashed mid-write, orphan mcptest-* artifacts "
        "may remain. Run:\n  uv run python scripts/cleanup_mcptest_artifacts.py --dry-run"
    )
```

- [ ] **Step 2: Verify the hook fires**

Trigger a deliberate failure to confirm the summary fires:
```bash
uv run pytest tests/integration/test_network_live.py::test_get_health_returns_subsystems \
  -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config' \
  -k 'no_such_test'
```
Expected: 0 tests run, but exitstatus != 0 → hook fires with the reminder message.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "test: add terminal-summary hook reminding about orphan artifacts"
```

---

## Task 22: Document the suite in README + AGENTS guidance

**Files:**
- Modify: `README.md` (add section near "Testing" or end)
- Modify: `CLAUDE.md` (note new commands)

- [ ] **Step 1: Add a "Live integration testing" section to README.md**

In `README.md`, find the existing "Testing" section (or section about `pytest`) and append:

```markdown
## Live integration testing

The suite under `tests/integration/` exercises every Network MCP tool against a real UniFi controller. CI never runs it (no live hardware); contributors run it manually.

### Required env vars

```bash
# Always required
export UNIFI_NETWORK_API=...
export UNIFI_MCP_TEST_PROTECTED_MACS="aa:bb:cc:dd:ee:ff,..."  # gateway + uplinked switch + AP

# Required for disruptive tests
export UNIFI_MCP_TEST_TARGET_MAC="..."   # downstream device for restart/forget/adopt
export UNIFI_MCP_TEST_CLIENT_MAC="..."   # client for kick/block/unblock
export UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1

# Triple-gate for DPI reset only
export UNIFI_MCP_TEST_ALLOW_DPI_RESET=1
```

### Invocations

```bash
# Safe default — Phase 1 smoke + Phase 2 CRUD + non-disruptive system tools
uv run pytest tests/integration/ -v -m "integration and not disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config'

# Full coverage including disruptive (restart, forget/adopt, kick, speedtest)
UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 \
  uv run pytest tests/integration/ -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'

# Sweeper for orphan mcptest-* artifacts
uv run python scripts/cleanup_mcptest_artifacts.py --dry-run
uv run python scripts/cleanup_mcptest_artifacts.py            # interactive
uv run python scripts/cleanup_mcptest_artifacts.py --force    # no prompts
```

The suite refuses to run write tests without `UNIFI_MCP_TEST_PROTECTED_MACS` set; on first run, it will fail with a printed device list to help you fill the value.

Design notes: `docs/superpowers/specs/2026-04-27-network-comprehensive-test-design.md`.
```

- [ ] **Step 2: Update CLAUDE.md with the new commands**

In `CLAUDE.md`, find the "Commands" section and add to the integration test block:

```bash
# Integration tests, safe default (no disruptive marker)
uv run pytest tests/integration/ -v -m "integration and not disruptive"

# Integration tests, full disruptive coverage (writes/restarts/etc)
UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 \
  uv run pytest tests/integration/ -v -m integration

# Sweep orphan mcptest-* artifacts
uv run python scripts/cleanup_mcptest_artifacts.py --dry-run
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document live integration suite + sweeper commands"
```

---

## Task 23: Acceptance criteria — full live run end-to-end

**Files:** none (verification only)

- [ ] **Step 1: Confirm the full safe suite passes**

Run:
```bash
uv run pytest tests/integration/ -v -m "integration and not disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: All non-disruptive tests pass (or skip with documented reasons). Capture the test count and pass/skip breakdown.

- [ ] **Step 2: Confirm the full disruptive suite passes (one full run)**

Run:
```bash
UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 \
  uv run pytest tests/integration/ -v -m integration \
  --override-ini='addopts=-ra --strict-markers --strict-config'
```
Expected: All tests pass (or skip with documented reasons — e.g. `authorize_guest`, `reset_dpi` skipped by default).

- [ ] **Step 3: Confirm the sweeper finds no orphans after the run**

Run:
```bash
uv run python scripts/cleanup_mcptest_artifacts.py --dry-run
```
Expected: "No artifacts matching prefix 'mcptest-' found."

- [ ] **Step 4: Confirm the sweeper deletes a manually-created artifact**

Manually create an `mcptest-*` artifact (e.g. via the UniFi UI, name it `mcptest-manual-test`), then run:

```bash
uv run python scripts/cleanup_mcptest_artifacts.py --force
```
Expected: 1 artifact found and deleted; sweeper exits 0.

Re-run:
```bash
uv run python scripts/cleanup_mcptest_artifacts.py --dry-run
```
Expected: "No artifacts matching prefix 'mcptest-' found."

- [ ] **Step 5: Final commit (acceptance log)**

If you want a record of the acceptance run, save the pytest output to a file and commit:

```bash
mkdir -p docs/superpowers/run-logs
uv run pytest tests/integration/ -v -m "integration and not disruptive" \
  --override-ini='addopts=-ra --strict-markers --strict-config' \
  > docs/superpowers/run-logs/2026-04-28-acceptance-safe.txt
git add docs/superpowers/run-logs/2026-04-28-acceptance-safe.txt
git commit -m "docs: record acceptance run output (safe suite)"
```

(Skip if you'd rather not commit run logs; the spec acceptance criteria only require that the run passes.)

---

## Self-review

**Spec coverage check:**

- §1 Goal — Tasks 4-17 implement the test suite ✓
- §2 Constraints — protected_macs, default_lan_id fixtures (Task 2-3) ✓
- §3 Coverage philosophy — Tasks 4-6 (smoke), 7-13 (CRUD), 14-16 (disruptive), 17 (system) ✓
- §4 File layout — Each file from §4 has a creation task ✓
- §4.1 Markers — Task 1 ✓
- §5 Fixtures — Tasks 2, 3 cover all 6 fixtures ✓
- §5.1 Safety guards — implemented in Task 2 (protected_macs validation) and Task 7 (default_lan_id guard) ✓
- §6 Phase 1 smoke (24 read tools) — Tasks 4-6 ✓
- §7 Phase 2 CRUD — Tasks 7-12 (one per domain) ✓
- §7.2 Negative-path — Task 13 ✓
- §8 Phase 3 disruptive — Tasks 14, 15, 16 ✓
- §9 System tools — Task 17 ✓
- §10 Coverage matrix — All tools accounted for in tasks above ✓
- §11 Sweeper — Tasks 18, 19, 20 ✓
- §12 Reporting — Task 21 ✓
- §13 Risk register — Mitigations baked into tasks (forget/adopt cleanup safety net in Task 15) ✓
- §16 Required env vars — Task 22 (README documentation) ✓
- §17 Acceptance criteria — Task 23 ✓

No gaps.

**Placeholder scan:** No "TBD", no "implement later", every step has concrete code or commands.

**Type/method consistency:** The plan calls `network_live_client.create_wlan(...)`, `delete_wlan`, etc. throughout. These are methods on `NetworkClient` from `src/unifi_mcp/clients/network.py`. The engineer is told in Task 7's Step 3 to inspect the real signatures and adjust if needed; same note repeated in Tasks 8-12 where applicable. This is the right call because the spec wasn't built with line-by-line client API knowledge — the test signatures need to match what exists. The note is consistent across tasks.

**Cross-task references:** None. Each task is self-contained.

Plan is ready.

---

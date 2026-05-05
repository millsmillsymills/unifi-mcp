# Network MCP Comprehensive Live Test — Design

- **Status:** Draft, brainstorming approved 2026-04-27
- **Owner:** mills
- **Branch:** `fix-103-protect-integration-path` (or follow-on)
- **Scope:** Comprehensive live test coverage of all 59 `unifi-mcp` Network API tools against the local UniFi controller at the UCG Ultra (192.168.1.1).

## 1. Goal

Exercise every Network tool in `src/unifi_mcp/tools/network/` against live hardware, prove the wiring works end-to-end, validate CRUD persistence + idempotency where applicable, and produce a durable pytest integration suite that future contributors can re-run after any client/tool change.

This mirrors the recent #103 Protect integration work but applied to the much larger Network surface (59 tools vs Protect's 15).

## 2. Constraints

| Constraint | Source |
|---|---|
| **Off-limits devices:** UCG Ultra (gateway) + the switch directly uplinked to it + the AP directly uplinked to that switch/gateway. | User directive (2026-04-27). |
| **Off-limits config target:** the management VLAN / default LAN. May read; must not create/update/delete. | User directive (2026-04-27). |
| **Allowed:** all downstream UniFi devices, settings, configurations, clients, VLANs, firewall rules, port-profiles, port-forwards, routes, WLANs. | User directive (2026-04-27). |
| **Test artifacts:** prefix `mcptest-`. Free-form descriptions tagged "Created by unifi-mcp integration test on 2026-04-27." | Convention. |
| **CI:** never runs the live suite. CI continues to run only `tests/unit/`. | Project convention; no live hardware in CI. |

## 3. Coverage philosophy: smoke + flows

- **Phase 1 — smoke:** every read tool fires once. Cheap insurance against signature/auth/path bugs (the class of bug Protect just hit in #103).
- **Phase 2 — non-disruptive CRUD flows:** for each CRUD domain (wlan, networks, firewall, port-forwards, port-profiles, routing), run `create → read-back → update → read-back → delete → confirm-gone`.
- **Phase 3 — disruptive tier:** device-action and client-action tools, gated behind a `disruptive` pytest marker AND `UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1` env var. Two-key opt-in.
- **System tools:** mixed disposition; covered in `test_network_system_live.py`.

Coverage target: **all 59 tools** exercised at least once OR explicitly excluded with documented reason. The coverage matrix is in §10.

## 4. File layout

```
tests/integration/
├── conftest.py                              # +shared fixtures (§5)
├── test_network_live.py                     # EXPAND from 6 → 24 read tools (Phase 1)
├── test_network_clients_live.py             # NEW — Phase 3, disruptive
├── test_network_devices_live.py             # NEW — Phase 3, disruptive
├── test_network_firewall_live.py            # NEW — Phase 2
├── test_network_networks_live.py            # NEW — Phase 2
├── test_network_port_forward_live.py        # NEW — Phase 2
├── test_network_port_profiles_live.py       # NEW — Phase 2
├── test_network_routing_live.py             # NEW — Phase 2
├── test_network_system_live.py              # NEW — system tools (§8)
└── test_network_wlan_live.py                # NEW — Phase 2

scripts/
└── cleanup_mcptest_artifacts.py             # NEW — orphan-artifact sweeper (§9)

docs/superpowers/specs/
└── 2026-04-27-network-comprehensive-test-design.md   # this file

pyproject.toml                               # +disruptive marker registration
```

### 4.1 Pytest markers and invocations

Markers:
- `integration` — already registered; gates the live suite.
- `disruptive` — NEW. Gates tests that bounce ports, kick clients, restart devices, or run `forget_device`/`adopt_device`.

Default invocations:

```bash
# Full safe suite (Phase 1 smoke + Phase 2 CRUD + non-disruptive system tools from §9)
uv run pytest tests/integration/ -v -m "integration and not disruptive"

# Full coverage including disruptive (Phase 3 + disruptive system)
UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 \
  uv run pytest tests/integration/ -v -m integration

# Sweeper (run before/after a session to confirm a clean baseline)
uv run python scripts/cleanup_mcptest_artifacts.py            # interactive
uv run python scripts/cleanup_mcptest_artifacts.py --dry-run  # list only
uv run python scripts/cleanup_mcptest_artifacts.py --force    # no prompt
```

Tests marked `disruptive` **skip** with a clear reason if `UNIFI_MCP_TEST_ALLOW_DISRUPTIVE` is not `1`, even when collected via `-m disruptive`. Two-key safety: marker + env var.

## 5. Shared fixtures (`tests/integration/conftest.py`)

Six new session-scoped fixtures alongside the existing `network_live_client`. All read once per session for speed and to keep "what's safe" immutable across tests.

```python
@pytest.fixture(scope="session")
def protected_macs() -> frozenset[str]:
    """MACs that must NEVER be modified.

    Set via UNIFI_MCP_TEST_PROTECTED_MACS=aa:bb:cc:dd:ee:ff,...
    Fail-fast (with a printed list of devices via network_list_devices)
    if unset — explicit allowlist required, no auto-detection.
    """

@pytest.fixture(scope="session")
def test_target_mac(network_live_client, protected_macs) -> str:
    """MAC of the designated downstream device for disruptive device-action tests.

    Set via UNIFI_MCP_TEST_TARGET_MAC=...
    Asserts target ∉ protected_macs at session start.
    Asserts target_role != "uplink-to-protected" (best-effort topology check).
    """

@pytest.fixture(scope="session")
def test_client_mac() -> str:
    """MAC of the test client for kick/block/unblock flows.

    Set via UNIFI_MCP_TEST_CLIENT_MAC=...
    Asserts != local machine MAC (foot-gun guard).
    Skips dependent tests if unset.
    """

@pytest.fixture(scope="session")
def default_lan_id(network_live_client) -> str:
    """_id of the default corporate network. networks-domain tests
    must never target this. Resolved from list_networks with
    purpose=='corporate' and is_default==True."""

@pytest.fixture(scope="session")
def mcptest_prefix() -> str:
    """All artifacts named {prefix}{domain}-{uuid4-hex[:8]}.
    Default: 'mcptest-'. Override via UNIFI_MCP_TEST_PREFIX.
    Session-scoped because session-scoped fixtures (test_vlan_id) depend on it."""

@pytest.fixture(scope="session")
def test_vlan_id(network_live_client, mcptest_prefix):
    """Session-scoped sandbox VLAN for dependent tests (wlan, port-profiles,
    firewall rules, port-forwards). Created in 90-99 range using lowest
    unused ID. Skipped (not failed) if creation fails — dependents skip too.

    Manages its own teardown via yield/finally (cannot depend on the
    function-scoped cleanup_register). Teardown is best-effort: logs
    WARNING on failure but never raises, so test failures aren't masked."""

@pytest.fixture
def cleanup_register(network_live_client):
    """Per-test stack-based cleanup for function-scoped artifacts created
    inside individual tests. Yields register(callable, *args).
    finally pops in LIFO order, best-effort deletes, logs WARNING on
    cleanup failure with artifact ID/name. Never raises (would mask
    the test's real failure).

    Session-scoped artifacts (e.g. test_vlan_id) manage their own teardown
    via fixture yield/finally — pytest disallows session fixtures depending
    on function-scoped ones."""
```

### 5.1 Safety guards baked into fixtures

1. `protected_macs` and `test_target_mac` fail-fast at collection time if env vars unset, with a printed device list.
2. `test_target_mac` asserts `target ∉ protected_macs` at session start.
3. `default_lan_id` cached once; networks-domain tests have a per-test guard `assert request_target_id != default_lan_id` before any update/delete.
4. `cleanup_register` cleanup failures log but never raise.
5. `test_vlan_id` picks the lowest unused VLAN ID in 90-99; fails with clear reason if all are in use.

### 5.2 Trade-off

Session-scoped `protected_macs` means changing the protected set mid-session requires a pytest restart. Intentional — mid-session mutation of "what's safe" is exactly the kind of confusion that leads to mistakes.

## 6. Phase 1 — read-only smoke pass

Expand `tests/integration/test_network_live.py` from 6 tests to 24 — one per read tool. No write tools fire. Failures here block all later phases.

| Module | Tools (one test each) |
|---|---|
| `stats` (9) | `get_health`, `list_events`, `list_devices`, `list_devices_basic`, `list_active_clients`, `list_configured_clients`, `list_all_clients`, `get_dpi_stats`, `get_sysinfo` |
| `clients` (1) | `network_get_client` (parametrized over a MAC pulled from `list_active_clients`) |
| `devices` (1) | `network_get_device` (parametrized over the `test_target_mac` fixture) |
| `firewall` (4) | `list_firewall_rules`, `get_firewall_rule`, `list_firewall_groups`, `get_firewall_group` |
| `networks` (2) | `list_networks`, `get_network` (uses `default_lan_id` for read; never writes) |
| `port_forward` (2) | `list_port_forwards`, `get_port_forward` (skips with reason if list empty) |
| `port_profiles` (2) | `list_port_profiles`, `get_port_profile` |
| `routing` (2) | `list_routes`, `get_route` (skips with reason if list empty) |
| `wlan` (2) | `list_wlans`, `get_wlan` |

Test shape (mirrors the existing 6):

```python
async def test_network_list_firewall_rules_returns_list(network_live_client):
    result = await network_live_client.list_firewall_rules()
    assert "data" in result
    assert isinstance(result["data"], list)
```

Assertions check shape only — `"data" in result`, `isinstance(..., list)`, presence of one obviously-required key (e.g. `version`, `mac`, `_id`). Content varies device-to-device; deep assertions would be brittle.

## 7. Phase 2 — non-disruptive CRUD round-trips

Six new files. Each runs the same shape: **create → read-back → update → read-back → delete → confirm-gone**. All artifacts named `mcptest-<domain>-<uuid8>`. All registered with `cleanup_register`.

### 7.1 Domain plan

**`test_network_wlan_live.py`** — Create unique SSID `mcptest-wlan-<uuid8>`, WPA2-PSK, hidden, on the test VLAN. Read → update passphrase → read → delete → confirm absent.

**`test_network_networks_live.py`** — Create VLAN (ID via `test_vlan_id` fixture, name `mcptest-vlan-<uuid8>`, subnet `10.99.99.0/24`). Read → update description → read → delete → confirm absent. Per-test guard `assert request_target_id != default_lan_id`.

**`test_network_firewall_live.py`** — Two flows:
- *Rule flow:* Create drop rule from `192.0.2.0/24` (TEST-NET-1) to test VLAN, low priority, `mcptest-fw-rule-<uuid8>`. Read → update (drop → reject) → read → delete → confirm.
- *Group flow:* Create address group `mcptest-fw-grp-<uuid8>` with two TEST-NET-1 IPs. Read → update (add third IP) → read → delete → confirm.

**`test_network_port_forward_live.py`** — Create port-forward WAN port 60099 → `10.99.99.10:8080`, name `mcptest-pf-<uuid8>`, `enabled=False` (inert if cleanup fails). Read → update description → read → delete → confirm.

**`test_network_port_profiles_live.py`** — Create profile `mcptest-pp-<uuid8>` (access-mode, untagged VLAN = test VLAN, PoE off). Read → update (toggle a flag) → read → delete → confirm. **No `assign_port_profile` here** — disruptive; lives in `test_network_devices_live.py`.

**`test_network_routing_live.py`** — Create static route `192.0.2.0/24` (TEST-NET-1; never reachable) via `10.99.99.1`, name `mcptest-route-<uuid8>`. Read → update description → read → delete → confirm.

### 7.2 Cross-cutting design points

- **File ordering / dependencies:** WLAN, port-profiles, firewall rules, port-forwards depend on the test VLAN. Resolved via session-scoped `test_vlan_id` fixture in `conftest.py`. Fixture failure → dependent tests skip with clear reason (not fail).
- **Idempotency:** "Read-back after update" assertions compare *the specific field changed* — never full-object equality. UniFi echoes computed fields (timestamps, version counters) that mutate on every write.
- **Negative paths:** One per domain (6 total) — e.g. `test_create_wlan_with_invalid_security_returns_tool_error`. Confirms the error-mapping layer surfaces a `ToolError` rather than a raw exception. Not exhaustive — error-mapping has unit-test coverage already.

## 8. Phase 3 — disruptive tier

All tests `@pytest.mark.disruptive`. Skip unless `UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1`.

### 8.1 `test_network_devices_live.py`

Five flows against `test_target_mac`. File-level fixture asserts `target ∉ protected_macs` and `target_role != "uplink-to-protected"`; if either fails, every test in the file skips.

| Test | Action | Recovery |
|---|---|---|
| `test_locate_unlocate_roundtrip` | `locate_device` → wait 2s → `unlocate_device` | None — LEDs only. |
| `test_restart_device` | `restart_device` → poll `get_device` until `state == 1` (max 120s) | Device returns on its own. |
| `test_provision_device` | `provision_device` → poll until provisioning flag clears (max 60s) | Idempotent. |
| `test_power_cycle_port` | Resolve a non-uplink PoE port → `power_cycle_port` → wait 30s. Pre-flight: skip if no PoE device or port is uplink. | Connected device reconnects. |
| `test_forget_adopt_roundtrip` | `forget_device` → poll until target appears in `pending` (max 180s) → `adopt_device` → poll until `state == 1` (max 240s) | `cleanup_register` retries adopt in `finally`; fail-loud if unrecoverable. |

**Excluded outright:**
- `network_upgrade_device` — too risky (can brick). Manual-only; documented gap.
- `network_assign_port_profile` against a port currently in use — only fires against a port pre-flagged "available" (no link state, no LLDP neighbor). If no such port exists, test skips.

### 8.2 `test_network_clients_live.py`

Three flows against `test_client_mac`. Fixture sanity: assert `test_client_mac` is currently associated and is not the machine running the test (coarse `socket.gethostname()` MAC lookup; catches the obvious foot-gun).

| Test | Action | Recovery |
|---|---|---|
| `test_block_unblock_client_roundtrip` | `block_client` → `get_client` (assert `blocked == True`) → `unblock_client` → `get_client` (assert `blocked == False`) | `cleanup_register` ensures `unblock_client` runs in `finally`. |
| `test_kick_client` | `kick_client` → poll `list_active_clients` for absence (max 30s) | Client reconnects on its own. |
| `test_authorize_unauthorize_guest_roundtrip` | **Skipped by default** — `"requires unauthenticated guest on a guest portal"` | Documented gap. Manually arrange a guest device and unset the skip to run. |

### 8.3 Forget/adopt risk acknowledgment

The `forget_adopt_roundtrip` test is the riskiest in the suite. If `adopt_device` fails after `forget_device` succeeded, the target is in "pending" state and effectively unmanaged until manually re-adopted. Mitigations:

1. `cleanup_register` pushes a final `adopt_device` retry that runs even if the test body fails.
2. The test polls `list_devices` for the pending state *before* calling adopt; if the target never appears as pending, the test fails fast and skips the adopt.
3. The two-key opt-in (marker + env var).

Documented in the spec as "the test most likely to need manual intervention."

## 9. System tools (`test_network_system_live.py`)

| Tool | Test | Marker | Notes |
|---|---|---|---|
| `network_get_settings` | `test_get_settings_returns_shape` | non-disruptive | Asserts at least one expected key. |
| `network_update_settings` | `test_update_settings_no_op_roundtrip` | non-disruptive | No-op pattern: read → write same value → read → assert unchanged. Targets `super_identity.site_desc` (low-stakes string). |
| `network_run_speedtest` | `test_run_speedtest_returns_result` | **disruptive** | Asserts shape (`xput_download`, `xput_upload`, `latency`). Disruptive because of WAN load. |
| `network_create_backup` | `test_create_backup_returns_path_or_url` | non-disruptive | Best-effort delete via backup-delete endpoint if exposed; otherwise documented as "leaves ~1MB artifact on controller, manually clearable via UI." |
| `network_archive_events` | `test_archive_events_returns_ok` | non-disruptive | One-way operation. Only fires if `list_events()` returned ≥1 unarchived event in smoke pass; otherwise skips with reason. |
| `network_reset_dpi` | `test_reset_dpi` | **disruptive + extra gate** | Triple-gate: marker + `UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1` + `UNIFI_MCP_TEST_ALLOW_DPI_RESET=1`. Permanent data loss if triggered. |
| `network_upgrade_device` | — | — | Excluded outright (matches §8.1). |
| `network_power_cycle_port` | — | — | Covered in `test_network_devices_live.py`. |
| `network_unauthorize_guest` | — | — | Paired with `authorize_guest` in `test_network_clients_live.py`. |

### 9.1 Trade-offs called out

- **`update_settings` no-op:** weakest test; doesn't prove the write *works*, only that it doesn't *fail*. Acceptable — same philosophy as smoke pass elsewhere.
- **`archive_events` opt-out-if-quiet:** a quiet network = no test coverage. Acceptable — better than archiving real ops alerts.
- **`reset_dpi` triple-gate:** historical-data-loss is permanent. Three keys; opting in is deliberate.

## 10. Coverage matrix

All 59 Network tools accounted for:

| Module | Tools | Coverage |
|---|---|---|
| `stats` (9) | All 9 read tools | Phase 1 smoke. |
| `clients` (5) | `get_client` | Phase 1 smoke. |
| | `block_client`, `unblock_client`, `kick_client` | Phase 3 disruptive (`test_network_clients_live.py`). |
| | `authorize_guest` | Phase 3 disruptive (skipped by default — needs guest portal setup). |
| `devices` (7) | `get_device` | Phase 1 smoke. |
| | `restart_device`, `provision_device`, `locate_device`, `unlocate_device` | Phase 3 disruptive (`test_network_devices_live.py`). |
| | `forget_device`, `adopt_device` | Phase 3 disruptive — paired round-trip. |
| `firewall` (10) | `list_firewall_rules`, `get_firewall_rule`, `list_firewall_groups`, `get_firewall_group` | Phase 1 smoke. |
| | `create/update/delete_firewall_rule`, `create/update/delete_firewall_group` | Phase 2 CRUD. |
| `networks` (5) | `list_networks`, `get_network` | Phase 1 smoke. |
| | `create/update/delete_network` | Phase 2 CRUD (test VLAN, never default LAN). |
| `port_forward` (5) | `list_port_forwards`, `get_port_forward` | Phase 1 smoke. |
| | `create/update/delete_port_forward` | Phase 2 CRUD. |
| `port_profiles` (6) | `list_port_profiles`, `get_port_profile` | Phase 1 smoke. |
| | `create/update/delete_port_profile` | Phase 2 CRUD. |
| | `assign_port_profile` | Phase 3 disruptive (against an available port only). |
| `routing` (5) | `list_routes`, `get_route` | Phase 1 smoke. |
| | `create/update/delete_route` | Phase 2 CRUD. |
| `system` (9) | `get_settings`, `update_settings`, `run_speedtest`, `create_backup`, `archive_events`, `reset_dpi` | §9. |
| | `upgrade_device` | **Excluded** (manual only). |
| | `power_cycle_port` | Covered under `devices` (§8.1). |
| | `unauthorize_guest` | Covered under `clients` (§8.2). |
| `wlan` (5) | `list_wlans`, `get_wlan` | Phase 1 smoke. |
| | `create/update/delete_wlan` | Phase 2 CRUD. |

**Total:** 59 tools, 58 covered, 1 excluded (`upgrade_device`). 1 covered-but-skipped-by-default (`authorize_guest`).

## 11. Cleanup sweeper (`scripts/cleanup_mcptest_artifacts.py`)

Standalone script (not a pytest fixture) for finding and removing orphan `mcptest-*` artifacts.

```bash
uv run python scripts/cleanup_mcptest_artifacts.py            # interactive prompt per item
uv run python scripts/cleanup_mcptest_artifacts.py --dry-run  # list only
uv run python scripts/cleanup_mcptest_artifacts.py --force    # delete without prompt
uv run python scripts/cleanup_mcptest_artifacts.py --prefix custom-  # override prefix
```

**Behavior:**
1. Reuses `NetworkClient` from `clients/network.py` and the same `.env` as the suite.
2. Iterates list-tools across all CRUD domains, filters by name prefix.
3. **Sorts deletions in dependency order** (the genuinely useful bit):
   1. WLANs (depend on networks)
   2. Port-forwards (depend on networks)
   3. Port-profiles (depend on networks)
   4. Firewall rules (may depend on firewall groups + networks)
   5. Static routes (may depend on networks)
   6. Firewall groups (independent)
   7. Networks/VLANs (last)
4. Prints a numbered plan; default mode prompts `y/N` per item.
5. Best-effort: a delete failure logs and continues.
6. Exits 0 on success, 1 if any deletion failed.

Estimated size: ~150 lines.

## 12. Reporting

No custom reporter. Three reasons:
1. `pytest -v` already prints per-test pass/fail; matches the rest of the live suite.
2. `tests/integration/artifacts/` exists for any test that wants to dump a JSON response for inspection — opt-in, no test needs to.
3. A custom reporter would be premature abstraction.

`conftest.py` adds a `pytest_terminal_summary` hook printing a one-line summary of any artifacts left in the cleanup_register's "failed-cleanup" log, with the suggested sweeper command.

## 13. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| `forget_device` succeeds but `adopt_device` hangs/fails | Medium | Two-key opt-in; `cleanup_register` retries adopt in finally; documented as "manual intervention possible." |
| Test VLAN ID 90-99 collides with existing VLAN | Low | Session fixture queries `list_networks`, picks lowest unused ID, fails with clear reason if 90-99 fully in use. |
| Protected MAC env var is wrong (typo, wrong device) | Low | Suite prints resolved protected device list at session start; user can ctrl-C before any write fires. |
| `mcptest-*` prefix collides with user's pre-existing artifacts | Very low | `--prefix` override on sweeper; convention documented. |
| `update_settings` no-op writes a value the controller rejects on round-trip echo | Low | Test uses free-form description field; on rejection, fails the test and surfaces the offending field. |
| Suite leaves disabled port-forward on WAN port 60099 | Very low | Created `enabled=False`; sweeper picks up by name; even if missed, port 60099 is high enough to avoid common service collisions. |
| Speedtest causes WAN saturation during work hours | Medium | Disruptive marker; user opts in when ready. |
| DPI stats reset destroys analysis data | High if triggered | Triple-gate; skipped by default. |

## 14. Out of scope

- **Site Manager API** — separate API surface (3 read tools); future spec can mirror this approach.
- **Protect API** — covered by recent #103 work + separate live tests (`test_protect_live.py`).
- **`network_upgrade_device`** — manual-only; documented gap.
- **Multi-site testing** — assumes the configured `UNIFI_NETWORK_SITE` (default `default`) is the test site.
- **CI integration** — live suite never runs in CI (no live hardware).

## 15. Implementation budget (rough)

| Component | Size |
|---|---|
| Phase 1 smoke (expand existing file) | ~150 lines added |
| Phase 2 CRUD (6 new files) | ~600 lines |
| Phase 3 disruptive (2 new files) | ~300 lines |
| System tools (1 new file) | ~150 lines |
| Sweeper script | ~150 lines |
| Shared fixtures (`conftest.py`) | ~120 lines |
| **Total** | **~1500 lines, 9 new files + 2 modified** |

Approx 67 tests covering all 59 Network tools. Some tools touched by multiple tests; some explicitly skipped (`upgrade_device`, `authorize_guest` happy-path).

## 16. Required env vars

Documented for the user when running the suite:

```bash
# Required for any disruptive tier run
export UNIFI_MCP_TEST_PROTECTED_MACS="aa:bb:cc:dd:ee:ff,11:22:33:44:55:66,..."
export UNIFI_MCP_TEST_TARGET_MAC="aa:bb:cc:dd:ee:fa"
export UNIFI_MCP_TEST_CLIENT_MAC="dd:ee:ff:00:11:22"
export UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1

# Triple-gate for DPI reset only
export UNIFI_MCP_TEST_ALLOW_DPI_RESET=1

# Optional
export UNIFI_MCP_TEST_PREFIX="mcptest-"   # default
```

The suite fail-fasts at session start with a printed device list if `UNIFI_MCP_TEST_PROTECTED_MACS` is unset.

## 17. Acceptance criteria

The implementation is "done" when:

1. The non-disruptive default suite passes green: `uv run pytest tests/integration/ -v -m "integration and not disruptive"`.
2. The full disruptive suite passes green at least once: `UNIFI_MCP_TEST_ALLOW_DISRUPTIVE=1 uv run pytest tests/integration/ -v -m integration`.
3. The sweeper script identifies and removes a manually-created `mcptest-*` artifact in dependency order.
4. After a full disruptive run, `cleanup_mcptest_artifacts.py --dry-run` reports no orphans.
5. The coverage matrix in §10 has every tool accounted for.

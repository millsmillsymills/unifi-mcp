# Protect MCP Live Test Plan

**Date:** 2026-04-27
**Branch context:** drafted on `fix-103-protect-integration-path`
**Hardware under test:** UCK-G2-Plus at `192.168.1.220`, Protect controller running integration v1, with one freshly-adopted camera dedicated to testing
**Author:** brainstorming pass with the user — destructive testing authorized provided it cannot brick the device

## Goal

Exercise every Protect MCP tool (15 total) end-to-end against live hardware, capture findings as GitHub issues, and leave behind a permanent integration test suite that can be re-run to detect regressions.

This spec covers planning. The implementation plan is produced separately by `superpowers:writing-plans`.

## Non-goals

- CI integration of the live tests (would require self-hosted runner + secrets injection).
- Refactoring `ProtectClient` or any tool layer module — only fixes whose absence would block the test from running.
- Closing #130 — `bootstrap` and `events` are tested as **negative locks**, not fixed.

## Scope

### In scope — all 15 Protect tools

| Tool | Test type | Notes |
|---|---|---|
| `protect_get_nvr` | happy path | precondition class |
| `protect_list_cameras` | happy path | asserts new camera present |
| `protect_get_camera` | happy + 1 negative (unknown id) | exercises 404 → `UniFiNotFoundError` mapping |
| `protect_list_chimes` / `_lights` / `_sensors` / `_viewers` | happy path each | shape only |
| `protect_get_snapshot` | happy + `max_bytes` cap + unknown id | validates #106 cap path |
| `protect_export_video` | happy (5s window from now-30s) + `max_bytes` cap + reversed start/end | validates #32/#64 streaming cap |
| `protect_get_bootstrap` | xfail-strict negative | locks in #130 contract |
| `protect_list_events` | xfail-strict negative | locks in #130 contract |
| `protect_set_recording_mode` | round-trip *current → "always" → original*; one invalid mode (`"xyz"`) | restoration via fixture finalizer |
| `protect_set_smart_detection` | round-trip + one bogus type (`"blueGiraffe"`) | finalizer restores |
| `protect_update_camera` | round-trip name + `ledSettings.isEnabled`; one malformed payload | finalizer restores |
| `protect_update_nvr` | round-trip benign setting (e.g., NVR name) with read-back; one malformed payload | **first** live validation of `PUT /nvrs` (currently `TODO(#130)` at `clients/protect.py:174`); finalizer restores |

### Deferred / out of scope

- Concurrency / rate-limit stress.
- Firmware operations (none exposed by the MCP).
- Network-level config changes that could lose controller connectivity.

## Test architecture

- **File:** `tests/integration/test_protect_live.py`
- **Marker:** `@pytest.mark.integration` (already configured in `pyproject.toml`).
- **Skip gates** (any one missing → whole module skips with a clear reason):
  - `UNIFI_PROTECT_HOST` and `UNIFI_PROTECT_API` set in env
  - `UNIFI_LIVE_TEST=1` (explicit opt-in — prevents accidental hits when running `pytest -m integration` against a different controller)
- **Driver:** FastMCP in-memory `Client(mcp_server)` — same code path production runs in, minus the JSON-RPC envelope. Validates registration, mode gating, and error mapping; not the stdio protocol surface (out of scope this round).
- **Server mode:** `readwrite` — write tools must register so they can be exercised.
- **Fixtures:**
  - Session-scoped: `protect_config`, `mcp_server` (calls `unifi_mcp.server.create_server` exactly as production does), `mcp_client`, `test_camera_id`.
  - Function-scoped: `restore_camera_state`, `restore_nvr_state` — capture before, restore in finalizer regardless of test outcome.
- **Evidence capture:** each test writes its full request/response to `tests/integration/.evidence/<test_name>.json`. Path added to `.gitignore`. Becomes the issue-attachment source.

## Test phases

Tests are grouped into classes and executed in this order:

1. **`TestPrecondition`** — `validate_connection`, `protect_get_nvr` returns dict with `id/name/version`, `protect_list_cameras` ≥ 1 entry. First-line catch for #131-class wrong-scope keys. Failures here mark every later test as skipped with the precondition reason rather than producing a cascade of red.
2. **`TestReads`** — chimes/lights/sensors/viewers + `get_camera` happy + unknown id.
3. **`TestMedia`** — snapshot (size > 1KB, JPEG magic bytes), export_video (size > 0, MP4 magic bytes), `max_bytes` cap behavior, negative cases.
4. **`TestKnownBroken`** — `bootstrap` and `list_events` decorated `@pytest.mark.xfail(strict=True, reason="#130")`. They MUST fail today; if they ever pass, xfail-strict flips to a hard failure and we know to close #130.
5. **`TestWrites`** — for each write tool: capture original → apply change → read back → assert change took → finalizer restores. Plus one `pytest.raises(ToolError)` test per write tool with malformed input.

Reads before writes so we don't mutate state via tools that haven't been verified. Writes last so any drift is contained to the end of the run and finalizers run regardless.

## Findings → issues taxonomy

| Class | Definition | Default action |
|---|---|---|
| `bug` | Tool raises unexpected exception or returns wrong type/shape on a happy-path call | New issue, label `bug` |
| `bug-write` | Write tool succeeds at HTTP level but the change doesn't persist (read-back differs) | New issue, label `bug` + `protect-writes` |
| `error-mapping` | Tool surfaces a raw `httpx.HTTPStatusError` instead of a `ToolError` with actionable message | New issue, label `bug` |
| `diagnostic` | Tool works but the WARN/ERROR log on failure is unactionable (e.g. #129's empty 401) | Comment on existing if related; otherwise new issue, label `diagnostic` |
| `regression-of-known` | Reproduces #129 / #130 / #131 against this hardware | **Comment** on existing issue with current hardware + repro; no new issue |
| `tool-disabled-from-fastmcp` | Tool didn't register on a `readwrite` server with valid Protect config | New issue, label `bug` (severe) |

### New-issue template

```
**Hardware:** UCK-G2-Plus, Protect <version>, camera model <model>
**Tool:** `protect_xxx`
**Mode:** readwrite
**Repro:** `pytest tests/integration/test_protect_live.py::TestX::test_y -v`

**Expected:** <one sentence>
**Observed:** <one sentence>

**Evidence:**
<request JSON>
<response JSON or exception class + message>
```

## Deliverables

1. `tests/integration/test_protect_live.py` — committed. Closes #43 ("live-hardware end-to-end verification — deferred").
2. Comments added to #129 / #130 / #131 with current-hardware evidence (whichever apply after the run).
3. Zero-to-many new GitHub issues — one per novel finding, using the template above.
4. A short closing summary in chat: tools passed / tools failed / issues filed/updated.

## Open questions

None at brainstorm close. The implementation plan (next step) will resolve fixture details (e.g., precise NVR write payload chosen for benign round-trip).

# Protect MCP Live Test Plan

**Date:** 2026-04-27 (rev 2 — refreshed against existing test infrastructure)
**Branch context:** drafted on `fix-103-protect-integration-path`
**Hardware under test:** UCK-G2-Plus at `192.168.1.220`, Protect controller running integration v1, with one freshly-adopted camera dedicated to testing. Destructive testing authorized provided it cannot brick the device.

## Goal

Reach end-to-end coverage for every Protect MCP tool (15 total) at the FastMCP tool boundary against live hardware, capture findings as GitHub issues, and leave the existing live-test suites stricter so #130 cannot silently regress.

This spec covers planning. The implementation plan is produced separately by `superpowers:writing-plans`.

## Existing infrastructure (extending, not greenfield)

This work extends the live-hardware suite that already exists. Three files are relevant:

- **`tests/integration/conftest.py`** — provides `protect_live_client` (direct `ProtectClient`, env-gated by `UNIFI_PROTECT_API`). Reused as-is.
- **`tests/integration/test_protect_live.py`** — client-level tests covering `validate_connection`, `get_nvr`, `list_cameras`, `get_snapshot` (with JPEG magic-byte assertion), and `list_events` as `xfail-strict` for #130. Extended with `export_video` coverage.
- **`tests/integration/test_all_tools_live.py`** — MCP-tool-boundary suite (uses `Client(create_server())`). Already covers all 6 Protect no-arg reads via `NO_ARG_READ_TOOLS` + `protect_get_camera` via `DETAIL_READ_TOOLS`. Has `TestWriteRoundtrips` (Network-only today), `TestDestructive`, `TestModeGatingLive`. Convention: writes gated by `LIVE_TEST_WRITES=1`, destructive ops by `LIVE_TEST_DESTRUCTIVE=1`. Per-session evidence dumped to `tests/integration/artifacts/<timestamp>/`. Extended with Protect write coverage and an xfail-strict set for #130-affected reads.

Conventions inherited from this suite (the new spec MUST follow them, not invent parallel ones):

- Skip-gate env vars: `LIVE_TEST_WRITES=1`, `LIVE_TEST_DESTRUCTIVE=1` (no new `UNIFI_LIVE_TEST` flag).
- Evidence artifact path: `tests/integration/artifacts/<UTC-timestamp>/<tool_name>.json`.
- Server constructed via `unifi_mcp.server.create_server()` (real env, real lifespan).
- Driver: in-memory `fastmcp.Client(server)` for MCP-level tests; direct `ProtectClient` for byte-level / streaming-cap tests.

## Coverage gap analysis (15 Protect tools)

| Tool | Currently covered? | Gap |
|---|---|---|
| `protect_get_nvr` | ✅ both files | none |
| `protect_list_cameras` | ✅ both files | none |
| `protect_get_camera` | ✅ `test_all_tools_live.DETAIL_READ_TOOLS` | none |
| `protect_list_chimes` / `_lights` / `_sensors` / `_viewers` | ✅ MCP-level | none |
| `protect_get_snapshot` | ✅ client-level (JPEG magic bytes) | add MCP-level shape check (`format/data_base64/size_bytes` dict) |
| `protect_export_video` | ❌ no coverage anywhere | full coverage, both client- and MCP-level |
| `protect_get_bootstrap` | ⚠ MCP-level: in `NO_ARG_READ_TOOLS` w/o xfail → masks #130 | move to xfail-strict set at MCP boundary |
| `protect_list_events` | ⚠ client-level xfail-strict (✅) **but** MCP-level in `NO_ARG_READ_TOOLS` w/o xfail (masks #130) | move to xfail-strict set at MCP boundary |
| `protect_set_recording_mode` | ❌ | round-trip + 1 negative |
| `protect_set_smart_detection` | ❌ | round-trip + 1 negative |
| `protect_update_camera` | ❌ (only mentioned in `TestModeGatingLive` as a tool that must hide in readonly) | round-trip + 1 negative |
| `protect_update_nvr` | ❌ | round-trip + 1 negative — **first** live validation of `PUT /nvrs` (currently `TODO(#130)` at `clients/protect.py:174`) |

Net new work = `export_video` coverage + 4 Protect write round-trips + 4 negative-input tests + xfail-strict reclassification of `protect_get_bootstrap` and `protect_list_events` at the MCP layer.

## Scope

### In scope

- Extend **`test_protect_live.py`** with `export_video` (client-level — exercises streaming `max_bytes` cap; takes a 5-second window from now-30s).
- Extend **`test_all_tools_live.py`** with:
  - **Reclassification:** new top-level set `XFAIL_NO_ARG_READ_TOOLS = {"protect_get_bootstrap", "protect_list_events"}` consumed by `TestReadTools.test_every_no_arg_read_tool` so these tools are expected-failure with reason `#130` (matches existing client-level xfail). Locks #130 status at the MCP layer too.
  - **`TestProtectWriteRoundtrips`** class, gated by `LIVE_TEST_WRITES=1` (existing convention). For each Protect write tool: capture original via the matching read tool → apply mutation → read back → assert mutation took → restore in `finally`. Each test name follows the existing `test_<entity>_<action>` style (e.g., `test_recording_mode_roundtrip`).
  - **`TestProtectWriteNegatives`** class, also gated by `LIVE_TEST_WRITES=1`. One `pytest.raises(ToolError)` test per write tool with malformed input (invalid recording mode, bogus smart-detect type, malformed `update_camera` payload, malformed `update_nvr` payload).
  - **`protect_get_snapshot` MCP-shape test** — asserts response dict has `format == "jpeg"`, `size_bytes > 1024`, `data_base64` decodes to bytes starting with JPEG magic (`\xff\xd8\xff`).

### Out of scope

- CI integration of the live suite (would require self-hosted runner + secrets).
- Refactoring `ProtectClient` or any tool layer module beyond fixes whose absence would block the test from running.
- Closing #130 — `bootstrap`/`events` stay locked-in via xfail-strict.
- Cross-API tests (Network/SiteManager remain untouched).

## Test architecture (changes only — existing infra reused as-is)

- **No new files.** Edits to `test_protect_live.py` and `test_all_tools_live.py`.
- **Restoration via `try/finally`** inside each round-trip test (matches the existing `TestWriteRoundtrips` pattern of capture-then-cleanup; no new fixture machinery needed). On test failure, the finalizer still runs, restoring the captured original.
- **Camera selection:** `_unwrap_list(await _invoke(client, "protect_list_cameras"))[0]["id"]` — first camera, same convention `DETAIL_READ_TOOLS` already uses. Skip the test cleanly if no cameras.
- **NVR write target:** benign string field readable via `protect_get_nvr` (e.g., `name`). Capture pre-test, restore in `finally`.
- **Camera write target for `update_camera`:** combination of a string field and a nested settings field (`name` plus `ledSettings.isEnabled`) — exercises both the simple-key and nested-dict PUT shapes against `cameras/{id}`.

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
**Repro:** `LIVE_TEST_WRITES=1 uv run pytest tests/integration/test_all_tools_live.py::TestX::test_y -v`

**Expected:** <one sentence>
**Observed:** <one sentence>

**Evidence:**
<request JSON>
<response JSON or exception class + message>
```

## Deliverables

1. **Extended `tests/integration/test_protect_live.py`** — adds `protect_export_video` client-level test (happy path + reversed-window negative + `max_bytes` cap behavior).
2. **Extended `tests/integration/test_all_tools_live.py`** — adds `XFAIL_NO_ARG_READ_TOOLS` reclassification, `TestProtectWriteRoundtrips`, `TestProtectWriteNegatives`, and `protect_get_snapshot` MCP-shape test.
3. **Comments on #129 / #130 / #131** with current-hardware evidence (whichever apply after the run).
4. **Zero-to-many new GitHub issues** — one per novel finding, using the template above.
5. **Closing summary in chat:** tools passed / tools failed / issues filed/updated.

## Open questions

None at brainstorm close. The implementation plan resolves the precise NVR write payload chosen for benign round-trip (e.g., `name`) and the snapshot/export `max_bytes` cap values (already configured via `UNIFI_MAX_SNAPSHOT_BYTES` / `UNIFI_MAX_EXPORT_BYTES`).

## What changed in rev 2

- Removed the planned new-from-scratch `test_protect_live.py` — file already exists with 5 tests.
- Removed invented `UNIFI_LIVE_TEST=1` skip-gate; aligned with existing `LIVE_TEST_WRITES=1` / `LIVE_TEST_DESTRUCTIVE=1`.
- Removed invented `tests/integration/.evidence/` path; aligned with existing `tests/integration/artifacts/<ts>/`.
- Removed `TestPrecondition` / `TestReads` / `TestKnownBroken` class scaffolding — equivalents already exist in `test_all_tools_live.py`.
- Surfaced an actual existing bug: `protect_get_bootstrap` and `protect_list_events` are in `NO_ARG_READ_TOOLS` without xfail at the MCP layer, masking #130.
- Adjusted "Closes #43" claim — `test_all_tools_live.py` already closes #91; this work doesn't fully close #43 either, just narrows its remaining surface.

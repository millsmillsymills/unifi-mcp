# Protect MCP Live Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reach end-to-end coverage for every Protect MCP tool against live hardware (UCK-G2-Plus + new test camera) and surface any defects as GitHub issues. Spec: `docs/superpowers/specs/2026-04-27-protect-mcp-live-test-plan.md`.

**Architecture:** Extends the two existing live-test files. Follows established conventions — `LIVE_TEST_WRITES=1` opt-in for write tests, `tests/integration/artifacts/<UTC-timestamp>/` for evidence dumps, in-memory `fastmcp.Client(create_server())` at the MCP boundary, direct `ProtectClient` for byte-level streaming.

**Tech Stack:** pytest, pytest-asyncio, fastmcp, httpx, base64.

**Hardware preconditions** (operator before running anything):
- `UNIFI_PROTECT_HOST=192.168.1.220` set in `.env` (memory: default fallback to Network host points at the wrong device).
- `UNIFI_PROTECT_API` populated with a **Protect-scoped** key (memory: a Network-scoped key 401s here — see #131).
- New camera adopted and online (visible in the UCK-G2-Plus UI's camera list).
- `UNIFI_MODE=readwrite` and `LIVE_TEST_WRITES=1` exported in the shell when running the write phase. Both must be set; either alone is a no-op skip.

---

## File Structure

- **Modify:** `tests/integration/test_all_tools_live.py`
  - Add module-level `XFAIL_NO_ARG_READ_TOOLS` set, `_redact_data_base64` helper.
  - Remove `unifi_protect_get_bootstrap` and `unifi_protect_list_events` from `NO_ARG_READ_TOOLS`.
  - Add `TestReadTools.test_xfail_no_arg_read_tool` (parametrized, xfail-strict).
  - Add `TestReadTools.test_protect_get_snapshot_shape`.
  - Add `TestProtectWriteRoundtrips` class (4 round-trip tests, gated by `LIVE_TEST_WRITES=1`).
  - Add `TestProtectWriteNegatives` class (4 malformed-input tests, gated by `LIVE_TEST_WRITES=1`).

- **Modify:** `tests/integration/test_protect_live.py`
  - Add `import time`.
  - Add `test_export_video_returns_data` (happy path).
  - Add `test_export_video_reversed_window_raises` (negative).

(`tests/integration/conftest.py` is reused as-is — `protect_live_client` already handles `UNIFI_PROTECT_HOST` / `UNIFI_PROTECT_PORT` / `UNIFI_PROTECT_VERIFY_SSL` and skips cleanly when the API key is missing.)

---

## Task 0: Establish a green baseline against current hardware

**Files:** none (verification only).

This is a pause-and-confirm step. If the existing suite is red, every test we add will inherit the breakage and we'll waste a cycle chasing red herrings.

- [ ] **Step 1: Confirm env config**

```bash
grep -E "^UNIFI_(PROTECT|MODE)" /Users/mills/Desktop/Projects/unifi-mcp/.env
```

Expected: `UNIFI_PROTECT_HOST=192.168.1.220`, `UNIFI_PROTECT_API=...`, `UNIFI_MODE=...`.
If `UNIFI_PROTECT_HOST` is missing, the Protect client points at the Network gateway and every test fails with 401/connection errors. Fix before continuing.

- [ ] **Step 2: Run the existing client-level Protect suite**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && uv run pytest tests/integration/test_protect_live.py -v -m integration
```

Expected:
```
test_validate_connection                       PASSED
test_get_nvr_returns_identifier                PASSED
test_list_cameras_returns_list                 PASSED
test_get_snapshot_returns_jpeg                 PASSED
test_list_events_returns_list                  XFAIL  (#130)
```

Failure modes and resolutions:
- All `401`: Protect API key has wrong scope — see #131. Stop and ask user for a Protect-scoped key before continuing.
- All `ConnectionError`: `UNIFI_PROTECT_HOST` is wrong — fix `.env` to `192.168.1.220`.
- `test_get_snapshot_returns_jpeg` fails with "No cameras connected": the new camera isn't adopted yet on the NVR. Adopt it before continuing.
- `test_list_events_returns_list` shows `XPASS` (strict): #130 has been fixed upstream by Ubiquiti — proceed and adjust Task 1 to remove the xfail there.

- [ ] **Step 3: Run the existing MCP-tool-boundary Protect reads**

```bash
uv run pytest tests/integration/test_all_tools_live.py::TestReadTools -v -m integration
```

Expected:
- `test_every_no_arg_read_tool` currently FAILS with `unifi_protect_get_bootstrap` and `unifi_protect_list_events` in the failures list (because they're in `NO_ARG_READ_TOOLS` without xfail). This is the bug Task 1 fixes — record the exception messages from the artifacts dump for use in the #130 evidence comment later.
- `test_detail_read_tools_via_list_first` PASSES (covers `unifi_protect_get_camera`).

- [ ] **Step 4: Save the baseline artifacts dir**

```bash
ls /Users/mills/Desktop/Projects/unifi-mcp/tests/integration/artifacts/ | tail -1
```

Note the most recent timestamp dir — its `unifi_protect_get_bootstrap.json` and `unifi_protect_list_events.json` files contain the integration-v1 404 response shapes that go into Task 10's #130 evidence comment.

- [ ] **Step 5: Do not commit anything yet — Task 0 is a verification step.**

---

## Task 1: Reclassify `unifi_protect_get_bootstrap` and `unifi_protect_list_events` to xfail-strict at MCP layer

**Files:**
- Modify: `tests/integration/test_all_tools_live.py:94-124` (the `NO_ARG_READ_TOOLS` literal) and `tests/integration/test_all_tools_live.py:149-171` (`TestReadTools` class).

**Why:** these endpoints are documented missing on integration v1 (#130). The client-level suite already xfail-stricts `list_events`. The MCP-level suite currently lists them in `NO_ARG_READ_TOOLS` *without* xfail, so a real-hardware run shows them as plain failures — masking the #130 contract behind generic test red.

- [ ] **Step 1: Remove the two tools from `NO_ARG_READ_TOOLS`**

Find these two lines inside the `NO_ARG_READ_TOOLS = {...}` literal:

```python
    "unifi_protect_get_bootstrap",
    ...
    "unifi_protect_list_events",
```

Delete both. The Protect block in the set should become:

```python
    # Protect
    "unifi_protect_get_nvr",
    "unifi_protect_list_cameras",
    "unifi_protect_list_chimes",
    "unifi_protect_list_lights",
    "unifi_protect_list_sensors",
    "unifi_protect_list_viewers",
```

- [ ] **Step 2: Add `XFAIL_NO_ARG_READ_TOOLS` immediately below `NO_ARG_READ_TOOLS`**

Insert after the closing `}` of `NO_ARG_READ_TOOLS`, before `# Read tools that take required args`:

```python
# Read tools that exist in the registered set but have no integration-v1
# endpoint — the legacy /proxy/protect/api/ exposed bootstrap and events,
# the new /proxy/protect/integration/v1/ does not. Tracked in #130. The
# strict xfail flips to a hard failure if Ubiquiti ever adds them back,
# signaling that #130 can close.
XFAIL_NO_ARG_READ_TOOLS = {
    "unifi_protect_get_bootstrap": "#130 — integration/v1 has no bootstrap endpoint",
    "unifi_protect_list_events": "#130 — integration/v1 has no events endpoint",
}
```

- [ ] **Step 3: Add the parametrized xfail-strict test inside `TestReadTools`**

Insert after `test_detail_read_tools_via_list_first` (around line 197), still inside `class TestReadTools`:

```python
    @pytest.mark.parametrize(
        "tool_name",
        [
            pytest.param(name, marks=pytest.mark.xfail(strict=True, reason=reason))
            for name, reason in XFAIL_NO_ARG_READ_TOOLS.items()
        ],
    )
    async def test_xfail_no_arg_read_tool(self, live_client, artifacts, tool_name):
        """Tools that should fail today per #130. Strict xfail flips to a hard
        failure if Ubiquiti adds these endpoints back, signaling #130 can close.
        """
        tool_defs = {t.name for t in await live_client.list_tools()}
        if tool_name not in tool_defs:
            pytest.skip(f"{tool_name} not registered (Protect API not configured?)")
        payload = await _invoke(live_client, tool_name)
        # If we got here, the integration API now exposes this endpoint —
        # capture the payload so the operator can confirm the new shape.
        artifacts.dump(tool_name, {"ok": True, "payload": payload})
```

- [ ] **Step 4: Verify the file imports cleanly**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && uv run python -c "import tests.integration.test_all_tools_live"
```

Expected: no output. Any import error → fix syntax before continuing.

- [ ] **Step 5: Run the harness skip test (no live hardware needed)**

```bash
uv run pytest tests/integration/test_all_tools_live.py::test_harness_skips_cleanly_without_env -v
```

Expected: `PASSED`.

- [ ] **Step 6: Run live**

```bash
uv run pytest tests/integration/test_all_tools_live.py::TestReadTools -v -m integration
```

Expected:
- `test_every_no_arg_read_tool` PASSES (because the two #130 tools are no longer in the iterated set).
- `test_xfail_no_arg_read_tool[unifi_protect_get_bootstrap]` XFAILS.
- `test_xfail_no_arg_read_tool[unifi_protect_list_events]` XFAILS.
- `test_detail_read_tools_via_list_first` PASSES.

If `test_every_no_arg_read_tool` still fails on a different Protect tool, that's a real bug — capture the artifacts dump (`tests/integration/artifacts/<latest>/`) and continue to Task 2; we'll triage in Task 10.

- [ ] **Step 7: Commit**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && git add tests/integration/test_all_tools_live.py
git commit -m "$(cat <<'EOF'
test: reclassify #130 Protect reads to xfail-strict at MCP layer

unifi_protect_get_bootstrap and unifi_protect_list_events are documented missing on
integration v1 (#130). They were in NO_ARG_READ_TOOLS without xfail, so a
real-hardware run showed them as generic test failures. Move them to a
new XFAIL_NO_ARG_READ_TOOLS map and assert via parametrized xfail-strict
so the suite stays green today and flips to a hard failure if Ubiquiti
ever adds the endpoints back (signaling #130 can close).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add MCP-shape test for `unifi_protect_get_snapshot`

**Files:**
- Modify: `tests/integration/test_all_tools_live.py` — add `_redact_data_base64` helper and a new test method inside `TestReadTools`.

**Why:** existing client-level test asserts JPEG bytes. The MCP layer wraps bytes as `{"format": "jpeg", "data_base64": "<...>", "size_bytes": <n>}` (see `src/unifi_mcp/tools/protect/media.py:34-38`). Without an MCP-level shape test, a regression in the wrapping (e.g., wrong key name, missing `size_bytes`, dropped magic bytes) goes undetected.

- [ ] **Step 1: Add `_redact_data_base64` helper near `_unwrap_list`**

Find `def _unwrap_list(payload: Any) -> list[dict[str, Any]]:` (around line 200). Insert before it:

```python
def _redact_data_base64(payload: Any) -> Any:
    """Replace base64 image/video data with a size summary in artifact dumps.

    Snapshot/export payloads carry the entire encoded media inline. Without
    redaction, every artifact run would write multi-megabyte JSON files.
    """
    if isinstance(payload, dict) and "data_base64" in payload:
        return {**payload, "data_base64": f"<{len(payload['data_base64'])} chars redacted>"}
    return payload
```

- [ ] **Step 2: Add `import base64` to the imports block at the top of the file**

Find the existing imports block (lines 26-38). Add `import base64` after `import json`:

```python
import base64
import json
```

- [ ] **Step 3: Add `test_protect_get_snapshot_shape` inside `TestReadTools`**

Insert after `test_xfail_no_arg_read_tool` (added in Task 1):

```python
    async def test_protect_get_snapshot_shape(self, live_client, artifacts):
        """Snapshot tool returns the documented {format, data_base64, size_bytes}
        shape and the decoded bytes are a real JPEG.
        """
        tool_defs = {t.name for t in await live_client.list_tools()}
        if "unifi_protect_get_snapshot" not in tool_defs or "unifi_protect_list_cameras" not in tool_defs:
            pytest.skip("Protect tools not registered")

        cameras = _unwrap_list(await _invoke(live_client, "unifi_protect_list_cameras"))
        if not cameras:
            pytest.skip("No cameras adopted on the NVR")
        camera_id = cameras[0].get("id")
        assert camera_id, f"First camera entry missing id: {cameras[0]!r}"

        payload = await _invoke(live_client, "unifi_protect_get_snapshot", {"camera_id": camera_id})
        artifacts.dump(
            "unifi_protect_get_snapshot",
            {"ok": True, "camera_id": camera_id, "payload": _redact_data_base64(payload)},
        )

        assert isinstance(payload, dict), f"Snapshot payload must be dict, got {type(payload).__name__}"
        assert payload.get("format") == "jpeg", f"Expected format='jpeg', got {payload.get('format')!r}"
        assert payload.get("size_bytes", 0) > 1024, (
            f"Snapshot suspiciously small: {payload.get('size_bytes')} bytes"
        )
        data_b64 = payload.get("data_base64") or ""
        assert data_b64, "Missing or empty data_base64 field"
        decoded = base64.b64decode(data_b64)
        assert decoded.startswith(b"\xff\xd8\xff"), (
            f"Decoded bytes are not a JPEG (first 4 bytes: {decoded[:4]!r})"
        )
        assert len(decoded) == payload["size_bytes"], (
            f"size_bytes={payload['size_bytes']} disagrees with decoded length {len(decoded)}"
        )
```

- [ ] **Step 4: Verify import**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && uv run python -c "import tests.integration.test_all_tools_live"
```

Expected: no output.

- [ ] **Step 5: Run live**

```bash
uv run pytest tests/integration/test_all_tools_live.py::TestReadTools::test_protect_get_snapshot_shape -v -m integration
```

Expected: `PASSED`. If it fails, examine the artifacts dump — likely outcomes:
- `format` mismatch → file as `bug` (the tool's documented shape is wrong).
- `size_bytes` disagrees with decoded length → file as `bug` (off-by-base64-padding-error).
- Snapshot < 1024 bytes → likely a camera initializing edge case; rerun. If persistent, `bug` and capture the camera's stream state.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_all_tools_live.py
git commit -m "test: add MCP-shape assertion for unifi_protect_get_snapshot

Existing client-level test verifies JPEG bytes. The MCP tool wraps bytes
as {format, data_base64, size_bytes} — verify that envelope at the
boundary that agents actually see, including base64 round-trip integrity.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add `unifi_protect_export_video` client-level tests

**Files:**
- Modify: `tests/integration/test_protect_live.py` — add `import time` and two tests.

**Why:** `unifi_protect_export_video` has zero coverage anywhere in the suite. Memory says snapshot/export against an unknown camera id returns 429 (rate-limit) on integration v1 — interesting but separate. Here we just exercise the happy path against a known camera + one negative shape.

- [ ] **Step 1: Add `import time` to the imports block**

Find the imports block in `tests/integration/test_protect_live.py` (lines 8-12). Replace:

```python
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration
```

with:

```python
from __future__ import annotations

import time

import httpx
import pytest

from unifi_mcp.errors import UniFiError

pytestmark = pytest.mark.integration
```

- [ ] **Step 2: Append `test_export_video_returns_data` to the file**

After the existing `test_list_events_returns_list` (line 54):

```python


async def test_export_video_returns_data(protect_live_client):
    """Export a 5-second window from ~30s ago. Asserts non-empty bytes; size
    sanity check guards against the controller returning an empty/0-byte
    response on a brand-new camera with no recordings yet (treat that as a
    skip, not a fail — the test is about the export endpoint, not retention).
    """
    cameras = await protect_live_client.list_cameras()
    if not cameras:
        pytest.skip("No cameras connected to the NVR")
    camera_id = cameras[0].get("id")
    assert camera_id, "First camera entry missing id"

    end_ms = int(time.time() * 1000) - 5_000
    start_ms = end_ms - 5_000

    data = await protect_live_client.export_video(camera_id, start=start_ms, end=end_ms)
    assert isinstance(data, bytes), f"Expected bytes, got {type(data).__name__}"
    if len(data) == 0:
        pytest.skip("Export returned 0 bytes — likely no recording yet for the new camera")
    assert len(data) > 1024, f"Export suspiciously small: {len(data)} bytes"
```

- [ ] **Step 3: Append `test_export_video_reversed_window_raises`**

```python


async def test_export_video_reversed_window_raises(protect_live_client):
    """A reversed time window (start > end) should fail at the API rather than
    silently returning an empty/garbage clip. Accept either a UniFiError
    (mapped 4xx) or an httpx.HTTPError (raw timeout/transport) — the test is
    that the failure surfaces, not its precise class.
    """
    cameras = await protect_live_client.list_cameras()
    if not cameras:
        pytest.skip("No cameras connected to the NVR")
    camera_id = cameras[0].get("id")
    assert camera_id, "First camera entry missing id"

    now_ms = int(time.time() * 1000)
    with pytest.raises((UniFiError, httpx.HTTPError)):
        await protect_live_client.export_video(camera_id, start=now_ms, end=now_ms - 60_000)
```

- [ ] **Step 4: Verify import**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && uv run python -c "import tests.integration.test_protect_live"
```

Expected: no output.

- [ ] **Step 5: Run live**

```bash
uv run pytest tests/integration/test_protect_live.py -v -m integration -k export_video
```

Expected: both PASSED. If `test_export_video_reversed_window_raises` does NOT raise, the integration API is silently accepting reversed windows — that's a `bug` finding (file an issue: the integration API or our client should reject reversed ranges; agents passing bad windows should get an error, not a corrupt clip).

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_protect_live.py
git commit -m "test: add export_video happy path + reversed-window negative

Cover unifi_protect_export_video at the client level — was previously untested
anywhere in the suite. Treats 0-byte response as 'no recording yet' skip
(avoids false negatives on a freshly-adopted camera with no retention).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Add `TestProtectWriteRoundtrips` scaffolding + `test_recording_mode_roundtrip`

**Files:**
- Modify: `tests/integration/test_all_tools_live.py` — add module-level `_first_camera_id` helper next to `_unwrap_list`, and add a new class after the existing `TestWriteRoundtrips`.

**Why:** the existing `TestWriteRoundtrips` is Network-only. Protect writes have never been validated against live hardware (`TODO(#130)` at `clients/protect.py:174`). Each round-trip captures the original value, mutates, asserts via read-back, and restores in `finally`. The `_first_camera_id` helper is hoisted to module level to match the existing convention (`_invoke`, `_unwrap_list`, `_writes_enabled` are all module-level) and to be reused by Task 8's negatives class.

- [ ] **Step 1: Add module-level helper next to `_unwrap_list`**

Find `def _unwrap_list(payload: Any) -> list[dict[str, Any]]:` and the closing `return []`. After it, before the `# ── Write-tool audit` section:

```python


async def _first_protect_camera_id(client: Client) -> str:
    """Return the id of the first adopted camera, or pytest.skip if none.

    Used by every Protect write test to pick a target. Skips cleanly
    rather than failing when no camera is adopted (e.g., NVR exists but
    operator hasn't added a camera yet).
    """
    cameras = _unwrap_list(await _invoke(client, "unifi_protect_list_cameras"))
    if not cameras:
        pytest.skip("No cameras adopted on the NVR")
    camera_id = cameras[0].get("id")
    assert camera_id, f"First camera entry missing id: {cameras[0]!r}"
    return camera_id
```

- [ ] **Step 2: Add the `TestProtectWriteRoundtrips` class with the first test**

Insert after `TestWriteRoundtrips` and before `TestDeviceLocateCycle` (around line 263):

```python
@pytest.mark.skipif(not _writes_enabled(), reason=WRITE_GATE_REASON)
class TestProtectWriteRoundtrips:
    """Curated capture → mutate → read-back → restore roundtrips for the
    four Protect write tools. Each test runs against the first adopted
    camera (or the NVR for update_nvr) and restores the original value in
    `finally` even on assertion failure.
    """

    async def test_recording_mode_roundtrip(self, live_client, artifacts):
        """Capture current recordingSettings.mode, set 'always', read back,
        then restore. The legal modes are always | motion | never | schedule.
        """
        camera_id = await _first_protect_camera_id(live_client)

        before = await _invoke(live_client, "unifi_protect_get_camera", {"camera_id": camera_id})
        original_mode = (
            before.get("recordingSettings", {}).get("mode")
            if isinstance(before, dict)
            else None
        )
        artifacts.dump(
            "recording_mode_before",
            {"camera_id": camera_id, "original_mode": original_mode, "snapshot": before},
        )
        if not original_mode:
            pytest.skip(f"Could not read recordingSettings.mode from camera (got {before!r})")

        target = "always" if original_mode != "always" else "motion"

        try:
            applied = await _invoke(
                live_client,
                "unifi_protect_set_recording_mode",
                {"camera_id": camera_id, "mode": target},
            )
            artifacts.dump("recording_mode_applied", {"target": target, "response": applied})

            after = await _invoke(live_client, "unifi_protect_get_camera", {"camera_id": camera_id})
            after_mode = (
                after.get("recordingSettings", {}).get("mode")
                if isinstance(after, dict)
                else None
            )
            artifacts.dump("recording_mode_readback", {"after_mode": after_mode, "snapshot": after})
            assert after_mode == target, (
                f"Read-back mismatch: set {target!r}, read back {after_mode!r}"
            )
        finally:
            await _invoke(
                live_client,
                "unifi_protect_set_recording_mode",
                {"camera_id": camera_id, "mode": original_mode},
            )
            artifacts.dump("recording_mode_restored", {"restored_mode": original_mode})
```

- [ ] **Step 2: Verify import**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && uv run python -c "import tests.integration.test_all_tools_live"
```

Expected: no output.

- [ ] **Step 3: Run live with writes enabled**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && \
  UNIFI_MODE=readwrite LIVE_TEST_WRITES=1 \
  uv run pytest tests/integration/test_all_tools_live.py::TestProtectWriteRoundtrips::test_recording_mode_roundtrip -v -m integration
```

Expected: `PASSED`.

Likely failure modes (each is a finding):
- `Read-back mismatch: set 'always', read back 'motion'` → write tool succeeded at HTTP level but the controller dropped the change. File as `bug-write` against #130 evidence comment if the response was 200 silently no-op.
- `ToolError: Invalid request` from the SET call → the integration v1 PUT shape is different from what `clients/protect.py:set_recording_mode` sends. File as `bug` (Protect write is broken on integration v1) referencing the artifacts dump.
- `ToolError: Resource not found` → camera id resolution issue at the integration boundary. Capture and continue to next test; investigate in Task 10.

If the test fails, the `finally` still runs and restores the original mode — confirm by re-reading the camera in the UCK UI or via `unifi_protect_get_camera`.

- [ ] **Step 4: Commit (test result either way — passing test commits coverage; failing test commits the regression-detector that will start passing once #130-related write fixes ship)**

```bash
git add tests/integration/test_all_tools_live.py
git commit -m "test: add TestProtectWriteRoundtrips scaffolding + recording_mode

First round-trip coverage for Protect write tools. Captures
recordingSettings.mode, mutates, reads back, and restores in finally.
First live validation of PUT cameras/{id} against integration v1
(previously TODO #130 in clients/protect.py:174).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Add `test_smart_detection_roundtrip`

**Files:** Modify `tests/integration/test_all_tools_live.py` — add a new method to `TestProtectWriteRoundtrips`.

- [ ] **Step 1: Append the method to the class**

Insert after `test_recording_mode_roundtrip`:

```python
    async def test_smart_detection_roundtrip(self, live_client, artifacts):
        """Capture current smartDetectSettings.objectTypes, set ['person'],
        read back, then restore.
        """
        camera_id = await _first_protect_camera_id(live_client)

        before = await _invoke(live_client, "unifi_protect_get_camera", {"camera_id": camera_id})
        original = (
            list(before.get("smartDetectSettings", {}).get("objectTypes", []))
            if isinstance(before, dict)
            else None
        )
        artifacts.dump(
            "smart_detection_before",
            {"camera_id": camera_id, "original": original, "snapshot": before},
        )
        if original is None:
            pytest.skip(f"Could not read smartDetectSettings from camera (got {before!r})")

        target = ["person"]

        try:
            applied = await _invoke(
                live_client,
                "unifi_protect_set_smart_detection",
                {"camera_id": camera_id, "object_types": target},
            )
            artifacts.dump("smart_detection_applied", {"target": target, "response": applied})

            after = await _invoke(live_client, "unifi_protect_get_camera", {"camera_id": camera_id})
            after_types = (
                list(after.get("smartDetectSettings", {}).get("objectTypes", []))
                if isinstance(after, dict)
                else None
            )
            artifacts.dump("smart_detection_readback", {"after_types": after_types, "snapshot": after})
            assert after_types == target, (
                f"Read-back mismatch: set {target!r}, read back {after_types!r}"
            )
        finally:
            await _invoke(
                live_client,
                "unifi_protect_set_smart_detection",
                {"camera_id": camera_id, "object_types": original},
            )
            artifacts.dump("smart_detection_restored", {"restored": original})
```

- [ ] **Step 2: Run live**

```bash
UNIFI_MODE=readwrite LIVE_TEST_WRITES=1 \
  uv run pytest tests/integration/test_all_tools_live.py::TestProtectWriteRoundtrips::test_smart_detection_roundtrip -v -m integration
```

Expected: `PASSED`. Same failure-mode taxonomy as Task 4.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_all_tools_live.py
git commit -m "test: add Protect smart_detection roundtrip

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Add `test_update_camera_roundtrip`

**Files:** Modify `tests/integration/test_all_tools_live.py` — add a new method to `TestProtectWriteRoundtrips`.

- [ ] **Step 1: Append the method**

```python
    async def test_update_camera_roundtrip(self, live_client, artifacts):
        """Round-trip a string field (name) and a nested settings field
        (ledSettings.isEnabled) via unifi_protect_update_camera. Exercises both
        the simple-key and nested-dict shapes of PUT cameras/{id} on
        integration v1.
        """
        camera_id = await _first_protect_camera_id(live_client)

        before = await _invoke(live_client, "unifi_protect_get_camera", {"camera_id": camera_id})
        if not isinstance(before, dict):
            pytest.skip(f"Camera response is not a dict: {before!r}")
        original_name = before.get("name")
        original_led = before.get("ledSettings", {}).get("isEnabled")
        artifacts.dump(
            "update_camera_before",
            {"camera_id": camera_id, "name": original_name, "led": original_led, "snapshot": before},
        )
        if original_name is None or original_led is None:
            pytest.skip(
                f"Camera missing name or ledSettings.isEnabled (got name={original_name!r}, led={original_led!r})"
            )

        target_name = f"{original_name} [mcp-test]"
        target_led = not original_led

        try:
            applied = await _invoke(
                live_client,
                "unifi_protect_update_camera",
                {
                    "camera_id": camera_id,
                    "data": {"name": target_name, "ledSettings": {"isEnabled": target_led}},
                },
            )
            artifacts.dump(
                "update_camera_applied",
                {"target_name": target_name, "target_led": target_led, "response": applied},
            )

            after = await _invoke(live_client, "unifi_protect_get_camera", {"camera_id": camera_id})
            after_name = after.get("name") if isinstance(after, dict) else None
            after_led = after.get("ledSettings", {}).get("isEnabled") if isinstance(after, dict) else None
            artifacts.dump(
                "update_camera_readback",
                {"after_name": after_name, "after_led": after_led, "snapshot": after},
            )
            assert after_name == target_name, (
                f"name read-back mismatch: set {target_name!r}, read back {after_name!r}"
            )
            assert after_led == target_led, (
                f"led read-back mismatch: set {target_led!r}, read back {after_led!r}"
            )
        finally:
            await _invoke(
                live_client,
                "unifi_protect_update_camera",
                {
                    "camera_id": camera_id,
                    "data": {"name": original_name, "ledSettings": {"isEnabled": original_led}},
                },
            )
            artifacts.dump(
                "update_camera_restored",
                {"restored_name": original_name, "restored_led": original_led},
            )
```

- [ ] **Step 2: Run live**

```bash
UNIFI_MODE=readwrite LIVE_TEST_WRITES=1 \
  uv run pytest tests/integration/test_all_tools_live.py::TestProtectWriteRoundtrips::test_update_camera_roundtrip -v -m integration
```

Expected: `PASSED`. If it fails, examine which assertion fired:
- name fails but led passes → camera renaming may require a different shape (e.g., top-level `name` rejected). `bug-write`.
- led fails but name passes → nested-dict PUT shape isn't being honored. `bug-write`.
- both fail → broader issue, possibly auth/scope.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_all_tools_live.py
git commit -m "test: add Protect update_camera roundtrip (name + nested LED settings)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Add `test_update_nvr_roundtrip`

**Files:** Modify `tests/integration/test_all_tools_live.py` — add a new method to `TestProtectWriteRoundtrips`.

**Why:** This is the **first** live validation of `PUT /nvrs` on integration v1 — `clients/protect.py:174` carries `TODO(#130): verify PUT /nvrs (vs /nvrs/{id}) on live readwrite hardware.` If this test fails because the path is wrong (`PUT /nvrs/{id}` instead of `PUT /nvrs`), that's an immediate `bug` against the client and the test will be fixed once the client is fixed.

- [ ] **Step 1: Append the method**

```python
    async def test_update_nvr_roundtrip(self, live_client, artifacts):
        """Round-trip the NVR name via unifi_protect_update_nvr. First live-hardware
        validation of PUT /nvrs on integration v1 — see TODO(#130) in
        clients/protect.py.
        """
        before = await _invoke(live_client, "unifi_protect_get_nvr")
        if not isinstance(before, dict):
            pytest.skip(f"NVR response is not a dict: {before!r}")
        original_name = before.get("name")
        artifacts.dump("update_nvr_before", {"name": original_name, "snapshot": before})
        if not original_name:
            pytest.skip(f"NVR missing name field (got {before!r})")

        target_name = f"{original_name} [mcp-test]"

        try:
            applied = await _invoke(
                live_client,
                "unifi_protect_update_nvr",
                {"data": {"name": target_name}},
            )
            artifacts.dump("update_nvr_applied", {"target_name": target_name, "response": applied})

            after = await _invoke(live_client, "unifi_protect_get_nvr")
            after_name = after.get("name") if isinstance(after, dict) else None
            artifacts.dump("update_nvr_readback", {"after_name": after_name, "snapshot": after})
            assert after_name == target_name, (
                f"NVR name read-back mismatch: set {target_name!r}, read back {after_name!r}"
            )
        finally:
            await _invoke(
                live_client,
                "unifi_protect_update_nvr",
                {"data": {"name": original_name}},
            )
            artifacts.dump("update_nvr_restored", {"restored_name": original_name})
```

- [ ] **Step 2: Run live**

```bash
UNIFI_MODE=readwrite LIVE_TEST_WRITES=1 \
  uv run pytest tests/integration/test_all_tools_live.py::TestProtectWriteRoundtrips::test_update_nvr_roundtrip -v -m integration
```

Expected: `PASSED`. Most likely failure: `Resource not found` or `Invalid request` because the integration API expects `PUT /nvrs/{id}` not `PUT /nvrs`. If that happens, the test (and the client) need updating — but for now, **commit the failing test** as the regression-detector and file the bug. The `finally` may itself fail; if so the NVR name has the `[mcp-test]` suffix appended — note this in the issue and operator can rename via UI.

- [ ] **Step 3: Commit (regardless of pass/fail — see Task 10)**

```bash
git add tests/integration/test_all_tools_live.py
git commit -m "test: add Protect update_nvr roundtrip (TODO #130 clients/protect.py:174)

First live-hardware validation of PUT /nvrs on integration v1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Add `TestProtectWriteNegatives` class with 4 malformed-input tests

**Files:** Modify `tests/integration/test_all_tools_live.py` — append a new class after `TestProtectWriteRoundtrips`.

**Why:** Each write tool should surface a `ToolError` (mapped from `UniFiError`) when given malformed input — not a raw `httpx` exception or a silent success. This validates the error-mapping path end-to-end.

- [ ] **Step 1: Add `from fastmcp.exceptions import ToolError` to the imports block**

Find the imports block and add to the existing fastmcp import line:

```python
from fastmcp import Client
from fastmcp.exceptions import ToolError
```

- [ ] **Step 2: Append the class**

Insert after `TestProtectWriteRoundtrips`:

```python
@pytest.mark.skipif(not _writes_enabled(), reason=WRITE_GATE_REASON)
class TestProtectWriteNegatives:
    """Each Protect write tool with malformed input must surface a ToolError
    (mapped from UniFiError), not a raw httpx exception or a silent success.
    Mutations attempted here are rejected by the controller, so no restoration
    is needed.
    """

    async def test_set_recording_mode_invalid_mode(self, live_client, artifacts):
        camera_id = await _first_protect_camera_id(live_client)
        with pytest.raises(ToolError) as exc_info:
            await _invoke(
                live_client,
                "unifi_protect_set_recording_mode",
                {"camera_id": camera_id, "mode": "this-is-not-a-real-mode"},
            )
        artifacts.dump(
            "set_recording_mode_invalid",
            {"camera_id": camera_id, "error": str(exc_info.value)},
        )

    async def test_set_smart_detection_bogus_type(self, live_client, artifacts):
        camera_id = await _first_protect_camera_id(live_client)
        with pytest.raises(ToolError) as exc_info:
            await _invoke(
                live_client,
                "unifi_protect_set_smart_detection",
                {"camera_id": camera_id, "object_types": ["blueGiraffe"]},
            )
        artifacts.dump(
            "set_smart_detection_bogus",
            {"camera_id": camera_id, "error": str(exc_info.value)},
        )

    async def test_update_camera_unknown_field(self, live_client, artifacts):
        camera_id = await _first_protect_camera_id(live_client)
        with pytest.raises(ToolError) as exc_info:
            await _invoke(
                live_client,
                "unifi_protect_update_camera",
                {"camera_id": camera_id, "data": {"thisIsNotAField": "garbage"}},
            )
        artifacts.dump(
            "update_camera_unknown_field",
            {"camera_id": camera_id, "error": str(exc_info.value)},
        )

    async def test_update_nvr_unknown_field(self, live_client, artifacts):
        with pytest.raises(ToolError) as exc_info:
            await _invoke(
                live_client,
                "unifi_protect_update_nvr",
                {"data": {"thisIsNotAField": "garbage"}},
            )
        artifacts.dump("update_nvr_unknown_field", {"error": str(exc_info.value)})
```

- [ ] **Step 3: Verify import**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && uv run python -c "import tests.integration.test_all_tools_live"
```

- [ ] **Step 4: Run live**

```bash
UNIFI_MODE=readwrite LIVE_TEST_WRITES=1 \
  uv run pytest tests/integration/test_all_tools_live.py::TestProtectWriteNegatives -v -m integration
```

Expected: all four `PASSED`. Likely surprises (each is a finding):
- A test does *not* raise → the integration API silently accepts the malformed payload. File as `bug-write` (data integrity risk: garbage gets persisted).
- A test raises but with a non-`ToolError` exception → error-mapping in `handle_client_error` missed a case. File as `error-mapping`.
- The error message is empty/uninformative (`HTTP 400:` with no body) → that's a #129 regression — comment on #129 with the artifacts dump.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_all_tools_live.py
git commit -m "test: add TestProtectWriteNegatives — malformed-input checks

Each of the four Protect write tools must surface a ToolError when given
malformed input. Validates the UniFiError -> ToolError mapping at the
MCP boundary for the Protect write surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Final consolidated run + collect findings

**Files:** none (read-only).

- [ ] **Step 1: Run the full Protect-relevant suite**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && \
  UNIFI_MODE=readwrite LIVE_TEST_WRITES=1 \
  uv run pytest tests/integration/test_protect_live.py tests/integration/test_all_tools_live.py -v -m integration 2>&1 | tee /tmp/protect-live-run.txt
```

- [ ] **Step 2: Build a findings inventory**

Read `/tmp/protect-live-run.txt`. For each non-`PASSED`, non-`XFAIL` line:
- Test name
- Failure category from the spec's taxonomy table
- Path to the relevant `tests/integration/artifacts/<latest>/<file>.json`

Save the inventory to a scratch file (do not commit):

```bash
ls /Users/mills/Desktop/Projects/unifi-mcp/tests/integration/artifacts/ | tail -1
```

The most recent timestamp dir is the evidence source for Task 10 / Task 11.

- [ ] **Step 3: Sanity check — at least one of the assertion-driven tests should have surfaced *something***

If literally every test passed, that's plausible (all-green hardware), but: spot-check the `update_nvr` artifacts dump. If `unifi_protect_update_nvr` actually round-tripped successfully on `PUT /nvrs`, that closes the `TODO(#130)` at `clients/protect.py:174` — note that as a positive finding, see Task 10.

---

## Task 10: Update existing issues with current-hardware evidence

**Files:** none (GitHub).

For each `regression-of-known` finding, post a comment on the relevant existing issue using the new-issue template (adapted as a comment).

- [ ] **Step 1: #130 — bootstrap and events still 404**

If Task 1's xfail tests both XFAILed (expected outcome on current hardware):

```bash
gh issue comment 130 --body "$(cat <<'EOF'
Confirmed against UCK-G2-Plus (Protect 7.0.107) with a freshly-adopted camera, 2026-04-27.

`unifi_protect_get_bootstrap` and `unifi_protect_list_events` continue to return 404 on `/proxy/protect/integration/v1/`. Locked in at the MCP layer via `XFAIL_NO_ARG_READ_TOOLS` in `tests/integration/test_all_tools_live.py` — strict-xfail flips to a hard failure when Ubiquiti adds these endpoints back, signaling this can close.

Evidence: `tests/integration/artifacts/<ts>/unifi_protect_get_bootstrap.json`, `unifi_protect_list_events.json` (404 envelopes).
EOF
)"
```

- [ ] **Step 2: #131 — key-scope footgun**

If Task 0 surfaced no 401s at all, the current `K4Tx...` key in `.env` *is* Protect-scoped (a delta from the `48b8414` snapshot). Comment on #131:

```bash
gh issue comment 131 --body "$(cat <<'EOF'
Update — as of 2026-04-27 the `.env` `UNIFI_PROTECT_API` key is correctly Protect-scoped (no longer the Network-scoped key referenced in the original snapshot). Live tests against UCK-G2-Plus pass `validate_connection`, `get_nvr`, and `list_cameras`. The original footgun (key-scope mismatch with no surface-level signal) remains; this comment is a positive data point that operators *can* fix it by re-issuing in the UI with Protect scope.
EOF
)"
```

(Skip this comment if Task 0 surfaced 401s — the issue is still active and re-confirming it adds nothing.)

- [ ] **Step 3: #129 — uninformative 401 WARN**

Only comment if a test in Task 0/9 surfaced a `HTTP 401:` line with empty body. If so, attach the relevant artifacts dump.

---

## Task 11: File new issues for novel findings

**Files:** none (GitHub).

For each finding in Task 9's inventory that is *not* a regression-of-known, file a new issue using the spec's template.

- [ ] **Step 1: For each novel finding, file with `gh issue create`**

Template (one heredoc per finding):

```bash
gh issue create \
  --title "bug: <one-line summary>" \
  --label bug \
  --body "$(cat <<'EOF'
**Hardware:** UCK-G2-Plus, Protect 7.0.107, camera <model> (freshly adopted 2026-04-27)
**Tool:** `protect_xxx`
**Mode:** readwrite
**Repro:** `LIVE_TEST_WRITES=1 UNIFI_MODE=readwrite uv run pytest tests/integration/test_all_tools_live.py::TestX::test_y -v`

**Expected:** <one sentence>
**Observed:** <one sentence>

**Evidence:**

```json
<paste from tests/integration/artifacts/<ts>/<file>.json — redacted of base64 if applicable>
```

Surfaced by the live-test rollout in PR <branch URL>.
EOF
)"
```

- [ ] **Step 2: If Task 7's `update_nvr_roundtrip` failed with `404` or `Invalid request`**

That validates the long-standing `TODO(#130)` — file or update one issue specifically against `clients/protect.py:174`:

```bash
gh issue create \
  --title "bug: unifi_protect_update_nvr fails on integration v1 — PUT /nvrs path is wrong" \
  --label bug \
  --body "<filled per template, with the artifacts dump>"
```

- [ ] **Step 3: Track issue numbers for the closing summary**

Keep a running list as you file: `#NNN: <title>`.

---

## Task 12: Closing summary

**Files:** none (chat output).

- [ ] **Step 1: Post in chat**

```
Protect live-test rollout complete.

Tests added: 8 new (export_video x2, snapshot-shape, 4 write-roundtrips, 4 write-negatives) + 1 reclassification (xfail-strict for #130 reads at MCP layer).
Tests passed: <N>/<total>
Tests xfailed (expected): unifi_protect_get_bootstrap, unifi_protect_list_events (#130)

Issues:
- Updated #130 with current-hardware evidence: <link>
- <other update-comments>
- Filed: <list of #NNN with one-line titles>

#43 status: still open (covers more than Protect); narrowed remaining surface to <X>.
```

- [ ] **Step 2: Mark Task 0 finalized — clean working tree**

```bash
cd /Users/mills/Desktop/Projects/unifi-mcp && git status
```

If anything is uncommitted (e.g., a test change that resulted from a finding-driven fix), decide explicitly: commit it on this branch, or stash and address separately. Don't leave the tree dirty.

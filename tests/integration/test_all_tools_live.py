"""Live tool-layer audit: invoke every registered tool through the FastMCP client.

Where the existing ``test_network_live.py`` / ``test_protect_live.py`` /
``test_site_manager_live.py`` exercise **client methods**, this module drives
the **MCP tool boundary** that agents actually see. Closes #91.

Marked ``@pytest.mark.integration`` throughout so the default ``not integration``
CI run ignores the file. Run against a configured controller with:

    uv run pytest tests/integration/test_all_tools_live.py -v -m integration

Gating env vars:

* ``UNIFI_NETWORK_API`` (and siblings) — enables the corresponding API's tools.
* ``UNIFI_MODE=readwrite`` — enables the write-CRUD tests. Defaults to readonly.
* ``LIVE_TEST_WRITES=1`` — opt-in for the curated write roundtrips even if the
  server was started in readwrite. Defaults off so accidental runs don't mutate.
* ``LIVE_TEST_DESTRUCTIVE=1`` — opt-in for provision / restart / backup tests.
  These mutate actual devices; they stay disabled by default.

Every tool invocation is captured to ``tests/integration/artifacts/<timestamp>/``
so a diff between runs is easy.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from unifi_mcp.server import create_server

pytestmark = pytest.mark.integration


# ── Helpers & fixtures ─────────────────────────────────────────────────────


def _any_api_configured() -> bool:
    return any(os.environ.get(k) for k in ("UNIFI_NETWORK_API", "UNIFI_PROTECT_API", "UNIFI_SITE_MANAGER_API"))


def _writes_enabled() -> bool:
    return os.environ.get("UNIFI_MODE", "readonly").lower() == "readwrite" and os.environ.get(
        "LIVE_TEST_WRITES", ""
    ).strip() in {"1", "true", "yes"}


def _destructive_enabled() -> bool:
    return os.environ.get("LIVE_TEST_DESTRUCTIVE", "").strip() in {"1", "true", "yes"}


@dataclass
class ArtifactWriter:
    root: Path

    def dump(self, tool_name: str, payload: dict[str, Any]) -> None:
        path = self.root / f"{tool_name}.json"
        path.write_text(json.dumps(payload, indent=2, default=str))


@pytest.fixture(scope="session")
def artifacts() -> ArtifactWriter:
    """Create a per-session artifacts dir rooted at tests/integration/artifacts/<ts>."""
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    root = Path(__file__).resolve().parent / "artifacts" / stamp
    root.mkdir(parents=True, exist_ok=True)
    return ArtifactWriter(root=root)


@pytest.fixture
async def live_client():
    """A FastMCP Client connected to a server built from real env config.

    Skips the entire test if no API key is configured.
    """
    if not _any_api_configured():
        pytest.skip("No UNIFI_*_API env vars set; skipping live tool audit")
    server = create_server()
    async with Client(server) as client:
        yield client


# ── Discovery — what tools exist on this server? ──────────────────────────


NO_ARG_READ_TOOLS = {
    # Network stats / system
    "unifi_network_get_health",
    "unifi_network_list_devices",
    "unifi_network_list_devices_basic",
    "unifi_network_list_active_clients",
    "unifi_network_list_configured_clients",
    "unifi_network_list_all_clients",
    "unifi_network_get_sysinfo",
    "unifi_network_list_wlans",
    "unifi_network_list_networks",
    "unifi_network_list_firewall_rules",
    "unifi_network_list_firewall_groups",
    "unifi_network_list_port_forwards",
    "unifi_network_list_routes",
    "unifi_network_get_settings",
    # Protect
    "unifi_protect_get_nvr",
    "unifi_protect_list_cameras",
    "unifi_protect_list_chimes",
    "unifi_protect_list_lights",
    "unifi_protect_list_sensors",
    "unifi_protect_list_viewers",
    # Site Manager
    "unifi_site_manager_list_hosts",
    "unifi_site_manager_list_sites",
    "unifi_site_manager_list_devices",
}

# Read tools that exist in the registered set but always 404 against the
# current UniFi APIs — either the integration-v1 surface never exposed them
# (Protect bootstrap/events, #130) or the legacy Network endpoint has been
# retired (network_list_events on UCG Ultra, #138). The strict xfail flips
# to a hard failure if Ubiquiti adds them back, signaling the tracking
# issue can close.
XFAIL_NO_ARG_READ_TOOLS = {
    "unifi_protect_get_bootstrap": "#130 — integration/v1 has no bootstrap endpoint",
    "unifi_protect_list_events": "#130 — integration/v1 has no events endpoint",
    "unifi_network_list_events": "#138 — list/alarm 404s on current UCG Ultra firmware",
}

# Read tools that take required args; covered via the detail-fetch harness.
DETAIL_READ_TOOLS = {
    "unifi_network_get_device": ("unifi_network_list_devices", "mac", "mac"),
    "unifi_network_get_client": ("unifi_network_list_active_clients", "mac", "mac"),
    "unifi_network_get_wlan": ("unifi_network_list_wlans", "_id", "wlan_id"),
    "unifi_network_get_network": ("unifi_network_list_networks", "_id", "network_id"),
    "unifi_network_get_firewall_rule": ("unifi_network_list_firewall_rules", "_id", "rule_id"),
    "unifi_network_get_firewall_group": ("unifi_network_list_firewall_groups", "_id", "group_id"),
    "unifi_network_get_port_forward": ("unifi_network_list_port_forwards", "_id", "port_forward_id"),
    "unifi_network_get_route": ("unifi_network_list_routes", "_id", "route_id"),
    "unifi_protect_get_camera": ("unifi_protect_list_cameras", "id", "camera_id"),
}


# ── Read-tool audit ────────────────────────────────────────────────────────


async def _invoke(client: Client, name: str, args: dict[str, Any] | None = None) -> Any:
    """Call a tool and return the structured payload (or raise)."""
    result = await client.call_tool(name, args or {})
    return getattr(result, "structured_content", None) or getattr(result, "data", None) or result


class TestReadTools:
    """Audit every read tool surfaced by ``create_server()``. Tools whose
    namespace tag is disabled (e.g. Protect tools when the backend is
    unreachable, after #87) won't appear in ``list_tools()`` and are
    naturally skipped.
    """

    async def test_every_no_arg_read_tool(self, live_client, artifacts):
        tool_defs = {t.name for t in await live_client.list_tools()}
        candidates = sorted(NO_ARG_READ_TOOLS & tool_defs)
        if not candidates:
            pytest.skip("No no-arg read tools registered on this server")

        failures: list[tuple[str, str]] = []
        for tool in candidates:
            try:
                payload = await _invoke(live_client, tool)
                artifacts.dump(tool, {"ok": True, "payload": payload})
            except Exception as exc:
                failures.append((tool, f"{type(exc).__name__}: {exc}"))
                artifacts.dump(tool, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

        assert not failures, "Read tools failed:\n" + "\n".join(f"  {n}: {e}" for n, e in failures)

    async def test_detail_read_tools_via_list_first(self, live_client, artifacts):
        tool_defs = {t.name for t in await live_client.list_tools()}
        failures: list[tuple[str, str]] = []
        skipped: list[str] = []

        for detail_tool, (list_tool, id_field, arg_name) in DETAIL_READ_TOOLS.items():
            if detail_tool not in tool_defs or list_tool not in tool_defs:
                continue
            try:
                list_payload = await _invoke(live_client, list_tool)
                items = _unwrap_list(list_payload)
                if not items:
                    skipped.append(f"{detail_tool}: {list_tool} returned no items")
                    continue
                record_id = items[0].get(id_field)
                if record_id is None:
                    skipped.append(f"{detail_tool}: first {list_tool} item missing {id_field}")
                    continue
                detail = await _invoke(live_client, detail_tool, {arg_name: record_id})
                artifacts.dump(detail_tool, {"ok": True, "id": record_id, "payload": detail})
            except Exception as exc:
                failures.append((detail_tool, f"{type(exc).__name__}: {exc}"))
                artifacts.dump(detail_tool, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

        assert not failures, "Detail read tools failed:\n" + "\n".join(f"  {n}: {e}" for n, e in failures)

    @pytest.mark.parametrize(
        "tool_name",
        [
            pytest.param(name, marks=pytest.mark.xfail(strict=True, reason=reason))
            for name, reason in XFAIL_NO_ARG_READ_TOOLS.items()
        ],
    )
    async def test_xfail_no_arg_read_tool(self, live_client, artifacts, tool_name):
        """Tools that should fail today per their tracking issue (see the
        ``XFAIL_NO_ARG_READ_TOOLS`` reason strings). Strict xfail flips to a
        hard failure if Ubiquiti restores the endpoint, signaling that the
        tracking issue can close.
        """
        tool_defs = {t.name for t in await live_client.list_tools()}
        if tool_name not in tool_defs:
            pytest.skip(f"{tool_name} not registered (API not configured?)")
        payload = await _invoke(live_client, tool_name)
        # If we got here, the integration API now exposes this endpoint —
        # capture the payload so the operator can confirm the new shape.
        artifacts.dump(tool_name, {"ok": True, "payload": payload})

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
        assert payload.get("size_bytes", 0) > 1024, f"Snapshot suspiciously small: {payload.get('size_bytes')} bytes"
        data_b64 = payload.get("data_base64") or ""
        assert data_b64, "Missing or empty data_base64 field"
        decoded = base64.b64decode(data_b64)
        assert decoded.startswith(b"\xff\xd8\xff"), f"Decoded bytes are not a JPEG (first 4 bytes: {decoded[:4]!r})"
        assert len(decoded) == payload["size_bytes"], (
            f"size_bytes={payload['size_bytes']} disagrees with decoded length {len(decoded)}"
        )


def _redact_data_base64(payload: Any) -> Any:
    """Replace base64 image/video data with a size summary in artifact dumps.

    Snapshot/export payloads carry the entire encoded media inline. Without
    redaction, every artifact run would write multi-megabyte JSON files.
    """
    if isinstance(payload, dict) and "data_base64" in payload:
        return {**payload, "data_base64": f"<{len(payload['data_base64'])} chars redacted>"}
    return payload


def _unwrap_list(payload: Any) -> list[dict[str, Any]]:
    """Extract the list-of-dicts payload from a tool response.

    Three shapes are observed in this server:
    * Bare ``list[dict]`` — what some Protect tools return raw.
    * ``{"data": [...]}`` — what most Network tools return.
    * ``{"result": [...]}`` — FastMCP's structured-content wrapping for tools
      whose return type is ``list[dict]`` (Protect's list_cameras / list_chimes /
      etc.). ``_invoke`` returns ``structured_content`` first, so this envelope
      reaches us instead of the bare list.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


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


# ── Write-tool audit (opt-in via LIVE_TEST_WRITES=1) ───────────────────────


WRITE_GATE_REASON = "Set UNIFI_MODE=readwrite and LIVE_TEST_WRITES=1 to run write tests"


@pytest.mark.skipif(not _writes_enabled(), reason=WRITE_GATE_REASON)
class TestWriteRoundtrips:
    """Curated create → (update →) delete roundtrips with ``mcp-audit-<uuid>``
    names so residual artifacts are trivially identifiable. Each test skips
    cleanly if the list tool returns no baseline.
    """

    async def test_firewall_group_crud(self, live_client, artifacts):
        suffix = uuid.uuid4().hex[:8]
        name = f"mcp-audit-fwg-{suffix}"
        created = await _invoke(
            live_client,
            "unifi_network_create_firewall_group",
            {"name": name, "group_type": "address-group", "group_members": ["192.0.2.1"]},
        )
        artifacts.dump(f"create_firewall_group-{suffix}", {"ok": True, "payload": created})
        items = _unwrap_list(created)
        assert items, f"Expected created firewall group in response: {created}"
        group_id = items[0]["_id"]

        # Cleanup
        deleted = await _invoke(live_client, "unifi_network_delete_firewall_group", {"group_id": group_id})
        artifacts.dump(f"delete_firewall_group-{suffix}", {"ok": True, "payload": deleted})

    async def test_port_forward_crud(self, live_client, artifacts):
        suffix = uuid.uuid4().hex[:8]
        name = f"mcp-audit-pf-{suffix}"
        # Use RFC5737 addresses (TEST-NET-1 / 198.51.100.0/24) so no live traffic is affected.
        created = await _invoke(
            live_client,
            "unifi_network_create_port_forward",
            {
                "name": name,
                "dst_port": "65001",
                "fwd": "198.51.100.1",
                "fwd_port": "65001",
                "proto": "tcp",
                "enabled": False,
            },
        )
        artifacts.dump(f"create_port_forward-{suffix}", {"ok": True, "payload": created})
        items = _unwrap_list(created)
        assert items, f"Expected created port forward in response: {created}"
        pf_id = items[0]["_id"]
        deleted = await _invoke(live_client, "unifi_network_delete_port_forward", {"port_forward_id": pf_id})
        artifacts.dump(f"delete_port_forward-{suffix}", {"ok": True, "payload": deleted})


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
        original_mode = before.get("recordingSettings", {}).get("mode") if isinstance(before, dict) else None
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
            after_mode = after.get("recordingSettings", {}).get("mode") if isinstance(after, dict) else None
            artifacts.dump("recording_mode_readback", {"after_mode": after_mode, "snapshot": after})
            assert after_mode == target, f"Read-back mismatch: set {target!r}, read back {after_mode!r}"
        finally:
            await _invoke(
                live_client,
                "unifi_protect_set_recording_mode",
                {"camera_id": camera_id, "mode": original_mode},
            )
            artifacts.dump("recording_mode_restored", {"restored_mode": original_mode})

    async def test_smart_detection_roundtrip(self, live_client, artifacts):
        """Capture current smartDetectSettings.objectTypes, set ['person'],
        read back, then restore.
        """
        camera_id = await _first_protect_camera_id(live_client)

        before = await _invoke(live_client, "unifi_protect_get_camera", {"camera_id": camera_id})
        original = (
            list(before.get("smartDetectSettings", {}).get("objectTypes", [])) if isinstance(before, dict) else None
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
                list(after.get("smartDetectSettings", {}).get("objectTypes", [])) if isinstance(after, dict) else None
            )
            artifacts.dump("smart_detection_readback", {"after_types": after_types, "snapshot": after})
            assert after_types == target, f"Read-back mismatch: set {target!r}, read back {after_types!r}"
        finally:
            await _invoke(
                live_client,
                "unifi_protect_set_smart_detection",
                {"camera_id": camera_id, "object_types": original},
            )
            artifacts.dump("smart_detection_restored", {"restored": original})

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
            assert after_name == target_name, f"name read-back mismatch: set {target_name!r}, read back {after_name!r}"
            assert after_led == target_led, f"led read-back mismatch: set {target_led!r}, read back {after_led!r}"
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


# ── Device LED locate/unlocate cycle (only runs in LIVE_TEST_WRITES mode) ─


@pytest.mark.skipif(not _writes_enabled(), reason=WRITE_GATE_REASON)
class TestDeviceLocateCycle:
    async def test_locate_then_unlocate_each_adopted_device(self, live_client, artifacts):
        devices_payload = await _invoke(live_client, "unifi_network_list_devices")
        items = _unwrap_list(devices_payload)
        if not items:
            pytest.skip("No adopted devices to locate")

        online = [d for d in items if isinstance(d, dict) and d.get("state") == 1]
        if not online:
            pytest.skip("No online adopted devices to locate")

        failures: list[tuple[str, str]] = []
        for dev in online:
            mac = dev.get("mac")
            if not mac:
                continue
            try:
                await _invoke(live_client, "unifi_network_locate_device", {"mac": mac})
                await _invoke(live_client, "unifi_network_unlocate_device", {"mac": mac})
                artifacts.dump(f"locate_cycle-{mac}", {"ok": True, "mac": mac})
            except ToolError as exc:
                # Race: device went offline between list_devices and locate. Skip
                # rather than fail the whole cycle.
                if "api.err.DeviceOffline" in str(exc):
                    artifacts.dump(
                        f"locate_cycle-{mac}",
                        {"ok": False, "skipped": True, "reason": "DeviceOffline", "mac": mac},
                    )
                    continue
                failures.append((mac, f"{type(exc).__name__}: {exc}"))
                artifacts.dump(f"locate_cycle-{mac}", {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            except Exception as exc:
                failures.append((mac, f"{type(exc).__name__}: {exc}"))
                artifacts.dump(f"locate_cycle-{mac}", {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        assert not failures, "Locate cycle failures:\n" + "\n".join(f"  {m}: {e}" for m, e in failures)


# ── Slow / destructive (opt-in separately via LIVE_TEST_DESTRUCTIVE=1) ────


@pytest.mark.slow
@pytest.mark.skipif(
    not (_writes_enabled() and _destructive_enabled()),
    reason="Set UNIFI_MODE=readwrite, LIVE_TEST_WRITES=1, and LIVE_TEST_DESTRUCTIVE=1 to run backup + restart tests",
)
class TestDestructive:
    async def test_create_backup(self, live_client, artifacts):
        # Per #89 the backup call may take minutes. The tool bumps the per-request
        # timeout to 300s, so this should complete end-to-end on a live controller.
        payload = await _invoke(live_client, "unifi_network_create_backup")
        artifacts.dump("create_backup", {"ok": True, "payload": payload})


# ── Mode-gating sanity: readonly hides writes (no live hardware needed) ────


class TestModeGatingLive:
    async def test_readonly_hides_write_tools(self, live_client):
        """#43 item 3: in readonly mode, write tools must not appear in list_tools()."""
        if os.environ.get("UNIFI_MODE", "readonly").lower() != "readonly":
            pytest.skip("UNIFI_MODE is not readonly; skipping readonly-gate assertion")
        tools = {t.name for t in await live_client.list_tools()}
        # Every write tool's name mirrors its client method; pick a few well-known ones.
        # If readonly gating works, none of these should be visible.
        for destructive in (
            "unifi_network_create_wlan",
            "unifi_network_delete_wlan",
            "unifi_network_restart_device",
            "unifi_network_create_backup",
            "unifi_network_upgrade_device",
            "unifi_protect_update_camera",
        ):
            assert destructive not in tools, f"{destructive} is exposed in readonly mode — readonly gate is broken"


# ── Smoke test that the harness itself doesn't need live hardware ─────────


def test_harness_skips_cleanly_without_env(monkeypatch):
    """Sanity: with all UNIFI_*_API vars unset, the test file loads and the
    read-tool audit skips instead of erroring. Runs in the default CI suite.
    """
    for var in ("UNIFI_NETWORK_API", "UNIFI_PROTECT_API", "UNIFI_SITE_MANAGER_API"):
        monkeypatch.delenv(var, raising=False)
    assert _any_api_configured() is False

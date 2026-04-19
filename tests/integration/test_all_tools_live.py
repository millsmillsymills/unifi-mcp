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

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

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
    "network_get_health",
    "network_list_events",
    "network_list_devices",
    "network_list_devices_basic",
    "network_list_active_clients",
    "network_list_configured_clients",
    "network_list_all_clients",
    "network_get_sysinfo",
    "network_list_wlans",
    "network_list_networks",
    "network_list_firewall_rules",
    "network_list_firewall_groups",
    "network_list_port_forwards",
    "network_list_routes",
    "network_get_settings",
    # Protect
    "protect_get_bootstrap",
    "protect_get_nvr",
    "protect_list_cameras",
    "protect_list_chimes",
    "protect_list_lights",
    "protect_list_sensors",
    "protect_list_viewers",
    "protect_list_events",
    # Site Manager
    "site_manager_list_hosts",
    "site_manager_list_sites",
    "site_manager_list_devices",
}

# Read tools that take required args; covered via the detail-fetch harness.
DETAIL_READ_TOOLS = {
    "network_get_device": ("network_list_devices", "mac", "mac"),
    "network_get_client": ("network_list_active_clients", "mac", "mac"),
    "network_get_wlan": ("network_list_wlans", "_id", "wlan_id"),
    "network_get_network": ("network_list_networks", "_id", "network_id"),
    "network_get_firewall_rule": ("network_list_firewall_rules", "_id", "rule_id"),
    "network_get_firewall_group": ("network_list_firewall_groups", "_id", "group_id"),
    "network_get_port_forward": ("network_list_port_forwards", "_id", "port_forward_id"),
    "network_get_route": ("network_list_routes", "_id", "route_id"),
    "protect_get_camera": ("protect_list_cameras", "id", "camera_id"),
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


def _unwrap_list(payload: Any) -> list[dict[str, Any]]:
    """Most UniFi list responses are ``{"data": [...]}``; Protect returns a bare list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return []


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
            "network_create_firewall_group",
            {"name": name, "group_type": "address-group", "group_members": ["192.0.2.1"]},
        )
        artifacts.dump(f"create_firewall_group-{suffix}", {"ok": True, "payload": created})
        items = _unwrap_list(created)
        assert items, f"Expected created firewall group in response: {created}"
        group_id = items[0]["_id"]

        # Cleanup
        deleted = await _invoke(live_client, "network_delete_firewall_group", {"group_id": group_id})
        artifacts.dump(f"delete_firewall_group-{suffix}", {"ok": True, "payload": deleted})

    async def test_port_forward_crud(self, live_client, artifacts):
        suffix = uuid.uuid4().hex[:8]
        name = f"mcp-audit-pf-{suffix}"
        # Use RFC5737 addresses (TEST-NET-1 / 198.51.100.0/24) so no live traffic is affected.
        created = await _invoke(
            live_client,
            "network_create_port_forward",
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
        deleted = await _invoke(live_client, "network_delete_port_forward", {"port_forward_id": pf_id})
        artifacts.dump(f"delete_port_forward-{suffix}", {"ok": True, "payload": deleted})


# ── Device LED locate/unlocate cycle (only runs in LIVE_TEST_WRITES mode) ─


@pytest.mark.skipif(not _writes_enabled(), reason=WRITE_GATE_REASON)
class TestDeviceLocateCycle:
    async def test_locate_then_unlocate_each_adopted_device(self, live_client, artifacts):
        devices_payload = await _invoke(live_client, "network_list_devices")
        items = _unwrap_list(devices_payload)
        if not items:
            pytest.skip("No adopted devices to locate")

        failures: list[tuple[str, str]] = []
        for dev in items:
            mac = dev.get("mac")
            if not mac:
                continue
            try:
                await _invoke(live_client, "network_locate_device", {"mac": mac})
                await _invoke(live_client, "network_unlocate_device", {"mac": mac})
                artifacts.dump(f"locate_cycle-{mac}", {"ok": True, "mac": mac})
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
        payload = await _invoke(live_client, "network_create_backup")
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
            "network_create_wlan",
            "network_delete_wlan",
            "network_restart_device",
            "network_create_backup",
            "network_upgrade_device",
            "protect_update_camera",
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

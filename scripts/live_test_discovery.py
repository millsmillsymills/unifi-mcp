"""Read-only discovery pass for the live-test bench.

Emits a deny-list (resources the primary WAP depends on, off-limits to writes)
and an allow-list (devices/clients/WLANs safe to mutate), so subsequent write
tests can be scoped without risking the primary WAP at MAC 9c:05:d6:19:a1:c8.

Usage:
    set -a; source .env; set +a
    uv run python scripts/live_test_discovery.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from unifi_mcp.clients.network import NetworkClient

PRIMARY_WAP_MAC = "9c:05:d6:19:a1:c8"
TEST_CLIENT_MAC = "f8:e4:3b:78:91:b3"


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _norm_mac(value: Any) -> str:
    return str(value or "").strip().lower()


async def discover() -> dict[str, Any]:
    api_key = os.environ.get("UNIFI_NETWORK_API")
    if not api_key:
        print("UNIFI_NETWORK_API not set", file=sys.stderr)
        sys.exit(2)

    host = os.environ.get("UNIFI_NETWORK_HOST", "192.168.1.1")
    port = int(os.environ.get("UNIFI_NETWORK_PORT", "443"))
    site = os.environ.get("UNIFI_NETWORK_SITE", "default")
    verify_ssl = _bool_env("UNIFI_NETWORK_VERIFY_SSL")
    if not verify_ssl:
        print(
            f"WARNING: TLS verification disabled for {host}:{port} (set UNIFI_NETWORK_VERIFY_SSL=1 to enable)",
            file=sys.stderr,
        )

    client = NetworkClient(
        base_url=f"https://{host}:{port}",
        api_key=api_key,
        site=site,
        verify_ssl=verify_ssl,
        timeout=int(os.environ.get("UNIFI_REQUEST_TIMEOUT", "30")),
        max_retries=int(os.environ.get("UNIFI_MAX_RETRIES", "3")),
    )

    try:
        devices = (await client.list_devices()).get("data", [])
        wlans = (await client.list_wlans()).get("data", [])
        networks = (await client.list_networks()).get("data", [])
        firewall_rules = (await client.list_firewall_rules()).get("data", [])
        port_forwards = (await client.list_port_forwards()).get("data", [])
        port_profiles = (await client.list_port_profiles()).get("data", [])
        routes = (await client.list_routes()).get("data", [])
        active_clients = (await client.list_active_clients()).get("data", [])
    finally:
        await client.close()

    wap = next((d for d in devices if _norm_mac(d.get("mac")) == PRIMARY_WAP_MAC), None)
    if wap is None:
        print(f"Primary WAP {PRIMARY_WAP_MAC} not found in device list", file=sys.stderr)
        print("Available device MACs:", file=sys.stderr)
        for d in devices:
            print(f"  {_norm_mac(d.get('mac'))}  {d.get('name', '?')}  ({d.get('model', '?')})", file=sys.stderr)
        sys.exit(3)

    test_client = next((c for c in active_clients if _norm_mac(c.get("mac")) == TEST_CLIENT_MAC), None)

    default_lan = next(
        (n for n in networks if n.get("purpose") == "corporate" and (n.get("is_default") or not n.get("vlan"))),
        None,
    )

    enabled_wlans = [w for w in wlans if w.get("enabled")]

    other_devices = [
        d for d in devices if _norm_mac(d.get("mac")) != PRIMARY_WAP_MAC and d.get("type") not in {"ugw", "udm", "uxg"}
    ]
    gateway_devices = [d for d in devices if d.get("type") in {"ugw", "udm", "uxg"}]

    return {
        "primary_wap": {
            "mac": _norm_mac(wap.get("mac")),
            "name": wap.get("name"),
            "model": wap.get("model"),
            "type": wap.get("type"),
            "state": wap.get("state"),
            "adopted": wap.get("adopted"),
            "ip": wap.get("ip"),
            "version": wap.get("version"),
            "_id": wap.get("_id"),
        },
        "gateway_devices": [
            {"mac": _norm_mac(d.get("mac")), "name": d.get("name"), "model": d.get("model"), "type": d.get("type")}
            for d in gateway_devices
        ],
        "candidate_tier_c_devices": [
            {
                "mac": _norm_mac(d.get("mac")),
                "name": d.get("name"),
                "model": d.get("model"),
                "type": d.get("type"),
                "state": d.get("state"),
                "_id": d.get("_id"),
            }
            for d in other_devices
        ],
        "test_client_found": test_client is not None,
        "test_client": (
            {
                "mac": _norm_mac(test_client.get("mac")),
                "hostname": test_client.get("hostname") or test_client.get("name"),
                "ip": test_client.get("ip"),
                "is_wired": test_client.get("is_wired"),
                "uplink_mac": test_client.get("ap_mac") or test_client.get("sw_mac"),
            }
            if test_client
            else None
        ),
        "default_lan": (
            {"_id": default_lan.get("_id"), "name": default_lan.get("name"), "vlan": default_lan.get("vlan")}
            if default_lan
            else None
        ),
        "enabled_wlans": [
            {"_id": w.get("_id"), "name": w.get("name"), "networkconf_id": w.get("networkconf_id")}
            for w in enabled_wlans
        ],
        "totals": {
            "devices": len(devices),
            "wlans": len(wlans),
            "networks": len(networks),
            "firewall_rules": len(firewall_rules),
            "port_forwards": len(port_forwards),
            "port_profiles": len(port_profiles),
            "routes": len(routes),
            "active_clients": len(active_clients),
        },
    }


def _build_deny_list(report: dict[str, Any]) -> dict[str, list[str]]:
    wap = report["primary_wap"]
    deny_device_macs: list[str] = [wap["mac"]] + [d["mac"] for d in report["gateway_devices"]]
    deny_network_ids: list[str] = []
    if report["default_lan"]:
        deny_network_ids.append(report["default_lan"]["_id"])

    deny_wlan_ids: list[str] = [w["_id"] for w in report["enabled_wlans"]]

    return {
        "device_macs": sorted(set(deny_device_macs)),
        "network_ids": sorted(set(deny_network_ids)),
        "wlan_ids": sorted(set(deny_wlan_ids)),
    }


def main() -> None:
    report = asyncio.run(discover())
    deny = _build_deny_list(report)

    out_dir = Path("tests/integration/artifacts/discovery")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (out_dir / "deny_list.json").write_text(json.dumps(deny, indent=2))

    wap = report["primary_wap"]
    print("=" * 72)
    print("LIVE-TEST DISCOVERY REPORT")
    print("=" * 72)
    print(f"\nPrimary WAP (OFF-LIMITS): {wap['mac']}  {wap['name']}  ({wap['model']}, {wap['type']})")
    print(f"  state={wap['state']}  adopted={wap['adopted']}  ip={wap['ip']}  fw={wap['version']}")
    print(f"\nGateway devices (OFF-LIMITS): {len(report['gateway_devices'])}")
    for d in report["gateway_devices"]:
        print(f"  {d['mac']}  {d['name']}  ({d['model']}, {d['type']})")
    print(f"\nCandidate Tier-C target devices (SAFE to mutate): {len(report['candidate_tier_c_devices'])}")
    for d in report["candidate_tier_c_devices"]:
        print(f"  {d['mac']}  {d['name']}  ({d['model']}, {d['type']}, state={d['state']})")
    print(f"\nTest client {TEST_CLIENT_MAC}: {'FOUND' if report['test_client_found'] else 'NOT FOUND on controller'}")
    if report["test_client"]:
        c = report["test_client"]
        print(f"  hostname={c['hostname']}  ip={c['ip']}  wired={c['is_wired']}  via={c['uplink_mac']}")
    if report["default_lan"]:
        n = report["default_lan"]
        print(f"\nDefault LAN (OFF-LIMITS): {n['_id']}  name={n['name']}  vlan={n['vlan']}")
    print(f"\nEnabled WLANs (OFF-LIMITS to delete/disable): {len(report['enabled_wlans'])}")
    for w in report["enabled_wlans"]:
        print(f"  {w['_id']}  name={w['name']}")
    print("\nTotals:")
    for k, v in report["totals"].items():
        print(f"  {k}: {v}")
    print("\nDeny-list summary:")
    for k, v in deny.items():
        print(f"  {k}: {len(v)} entries")
    print(f"\nArtifacts written: {out_dir / 'report.json'}, {out_dir / 'deny_list.json'}")


if __name__ == "__main__":
    main()

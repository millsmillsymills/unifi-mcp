"""Live Network API tests. Require a reachable UniFi controller + UNIFI_NETWORK_API.

Run manually:

    uv run pytest tests/integration/test_network_live.py -v -m integration

Each test skips individually if the ``network_live_client`` fixture can't be built.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_validate_connection(network_live_client):
    assert await network_live_client.validate_connection() is True


async def test_get_health_returns_subsystems(network_live_client):
    result = await network_live_client.get_health()
    assert "data" in result
    subsystems = {entry.get("subsystem") for entry in result["data"]}
    # The UniFi health endpoint reliably returns at least WAN + LAN.
    assert "wan" in subsystems
    assert "lan" in subsystems


async def test_list_devices_returns_list(network_live_client):
    result = await network_live_client.list_devices()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_list_active_clients_returns_list(network_live_client):
    result = await network_live_client.list_active_clients()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_get_sysinfo_has_version(network_live_client):
    result = await network_live_client.get_sysinfo()
    assert "data" in result
    data = result["data"]
    assert data, "Expected at least one sysinfo entry"
    assert any("version" in entry for entry in data)


async def test_list_events_returns_shape(network_live_client):
    # Regression test for #86: `stat/event` was 404 on current controllers; we
    # now hit `stat/alarm`. Assert the tool returns the standard UniFi envelope.
    result = await network_live_client.list_events(limit=1)
    assert "data" in result
    assert isinstance(result["data"], list)


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

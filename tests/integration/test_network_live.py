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

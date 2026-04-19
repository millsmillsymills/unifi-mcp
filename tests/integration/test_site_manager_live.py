"""Live Site Manager API tests. Require UNIFI_SITE_MANAGER_API.

Run manually:

    uv run pytest tests/integration/test_site_manager_live.py -v -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_validate_connection(site_manager_live_client):
    assert await site_manager_live_client.validate_connection() is True


async def test_list_hosts_returns_data(site_manager_live_client):
    result = await site_manager_live_client.list_hosts()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_list_sites_returns_data(site_manager_live_client):
    result = await site_manager_live_client.list_sites()
    assert "data" in result
    assert isinstance(result["data"], list)


async def test_list_devices_returns_data(site_manager_live_client):
    result = await site_manager_live_client.list_devices()
    assert "data" in result
    assert isinstance(result["data"], list)

"""Live Protect API tests. Require a reachable NVR + UNIFI_PROTECT_API.

Run manually:

    uv run pytest tests/integration/test_protect_live.py -v -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_validate_connection(protect_live_client):
    assert await protect_live_client.validate_connection() is True


async def test_get_nvr_returns_identifier(protect_live_client):
    nvr = await protect_live_client.get_nvr()
    # NVR payload always carries at least one of these top-level identifiers.
    assert any(key in nvr for key in ("id", "mac", "name"))


async def test_list_cameras_returns_list(protect_live_client):
    cameras = await protect_live_client.list_cameras()
    assert isinstance(cameras, list)


async def test_get_snapshot_returns_jpeg(protect_live_client):
    cameras = await protect_live_client.list_cameras()
    if not cameras:
        pytest.skip("No cameras connected to the NVR")
    camera_id = cameras[0].get("id")
    assert camera_id, "First camera entry missing id"
    snapshot = await protect_live_client.get_snapshot(camera_id)
    # JPEG magic bytes.
    assert snapshot.startswith(b"\xff\xd8\xff"), "Snapshot is not a JPEG"
    assert len(snapshot) > 1024, "Snapshot suspiciously small"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "#130 — the integration API at /proxy/protect/integration/v1/ does not "
        "expose an events endpoint (returns 404 NOT_FOUND). Flip this xfail to "
        "a plain test when #130 ships either the removal or a WebSocket-based "
        "replacement."
    ),
)
async def test_list_events_returns_list(protect_live_client):
    events = await protect_live_client.list_events(limit=1)
    assert isinstance(events, list)

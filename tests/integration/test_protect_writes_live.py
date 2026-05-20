"""Live Protect write tests.

Per ``project_protect_integration_api_surface`` memory + #139, only
``set_recording_mode`` is expected to work end-to-end on integration v1.
The other three writes (``set_smart_detection``, ``update_camera``,
``update_nvr``) return HTTP 404 ``Entity 'endpoint' not found`` from the
controller because integration v1 doesn't wire those PUT bodies through
to backing handlers.

This test locks in the current upstream behavior so a future controller-
side fix is detected as a positive signal (the assertion flips).

Run:
    uv run pytest tests/integration/test_protect_writes_live.py -v -m integration

set_recording_mode is gated behind LIVE_TEST_PROTECT_WRITES=1 because a
silent mode flip on a real surveillance setup would be a problem. For
dedicated test hardware this gate is just opt-in confirmation.
"""

from __future__ import annotations

import logging
import os

import pytest

from unifi_mcp.errors import UniFiNotFoundError

LOG = logging.getLogger(__name__)

pytestmark = pytest.mark.integration


def _writes_enabled() -> bool:
    return os.environ.get("LIVE_TEST_PROTECT_WRITES", "").strip().lower() in {"1", "true", "yes", "on"}


PROTECT_WRITE_GATE_REASON = "Set LIVE_TEST_PROTECT_WRITES=1 to run set_recording_mode against the test camera"


async def _pick_test_camera_id(protect_live_client) -> str:
    cameras = await protect_live_client.list_cameras()
    if not cameras:
        pytest.skip("No cameras adopted on Protect controller")
    cam = cameras[0]
    cam_id = cam.get("id") or cam.get("_id")
    assert isinstance(cam_id, str), f"camera record missing id: {cam}"
    return cam_id


class TestSetSmartDetectionMissing:
    """Lock in upstream 404 for set_smart_detection on integration v1."""

    async def test_set_smart_detection_returns_not_found(self, protect_live_client):
        camera_id = await _pick_test_camera_id(protect_live_client)
        with pytest.raises(UniFiNotFoundError):
            await protect_live_client.set_smart_detection(camera_id, ["person"])


class TestUpdateCameraMissing:
    """Lock in upstream 404 for update_camera with arbitrary body on integration v1."""

    async def test_update_camera_returns_not_found(self, protect_live_client):
        camera_id = await _pick_test_camera_id(protect_live_client)
        with pytest.raises(UniFiNotFoundError):
            await protect_live_client.update_camera(camera_id, {"name": "should-404"})


class TestUpdateNvrMissing:
    """Lock in upstream 404 for update_nvr on integration v1 (PUT /nvrs)."""

    async def test_update_nvr_returns_not_found(self, protect_live_client):
        with pytest.raises(UniFiNotFoundError):
            await protect_live_client.update_nvr({"name": "should-404"})


@pytest.mark.skipif(not _writes_enabled(), reason=PROTECT_WRITE_GATE_REASON)
class TestSetRecordingModeWrite:
    """``set_recording_mode`` round-trip against the test camera.

    Per memory (Protect integration v1 surface), the PUT cameras/{id} with
    ``recordingSettings`` is round-trip-confirmed on the older G3-flex camera,
    but on G3 Flex hardware running newer firmware the GET response may no
    longer include ``recordingSettings`` — in that case we can't capture the
    original mode for restoration and the test skips.
    """

    async def test_set_recording_mode_roundtrip(self, protect_live_client):
        camera_id = await _pick_test_camera_id(protect_live_client)
        camera = await protect_live_client.get_camera(camera_id)
        original = camera.get("recordingSettings", {}).get("mode") if isinstance(camera, dict) else None
        if not original:
            pytest.skip(
                "Camera GET response has no recordingSettings.mode; round-trip cannot capture original. "
                "PUT path may still work but is no longer verifiable via integration v1 GET."
            )

        new_mode = "never" if original != "never" else "always"

        try:
            response = await protect_live_client.set_recording_mode(camera_id, new_mode)
            assert isinstance(response, dict), "set_recording_mode must return a dict"
        finally:
            try:
                await protect_live_client.set_recording_mode(camera_id, original)
            except Exception as exc:
                LOG.warning("Cleanup set_recording_mode(%s, %s) failed: %s", camera_id, original, exc)

"""Unit coverage for the live_write collection guard (#277, Part B).

The integration suite is excluded from CI, so its ``pytest_collection_modifyitems``
guard never runs there. These tests exercise the guard's logic directly against
the pytest item protocol it relies on (``iter_markers`` / ``get_closest_marker``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from tests.integration.conftest import _is_write_gated, pytest_collection_modifyitems

if TYPE_CHECKING:
    from collections.abc import Iterator

_WRITE_GATE_REASON = "Set UNIFI_MODE=readwrite and LIVE_TEST_WRITES=1 to run write tests"


class _Marker:
    def __init__(self, name: str, **kwargs: object) -> None:
        self.name = name
        self.kwargs = kwargs


class _Item:
    """Minimal stand-in for ``pytest.Item`` exposing the marker API the guard uses."""

    def __init__(self, nodeid: str, *markers: _Marker) -> None:
        self.nodeid = nodeid
        self._markers = markers

    def iter_markers(self, name: str) -> Iterator[_Marker]:
        return (m for m in self._markers if m.name == name)

    def get_closest_marker(self, name: str) -> _Marker | None:
        return next((m for m in self._markers if m.name == name), None)


def _item(nodeid: str, *markers: _Marker) -> pytest.Item:
    """Build a stub typed as ``pytest.Item`` (it implements the marker API the guard uses)."""
    return cast("pytest.Item", _Item(nodeid, *markers))


def test_write_gate_detected_by_reason() -> None:
    assert _is_write_gated(_item("t::a", _Marker("skipif", reason=_WRITE_GATE_REASON)))
    assert not _is_write_gated(_item("t::a", _Marker("skipif", reason="needs live hardware")))
    assert not _is_write_gated(_item("t::a"))


def test_guard_raises_for_write_gated_without_marker() -> None:
    item = _item("t::a", _Marker("skipif", reason=_WRITE_GATE_REASON))
    with pytest.raises(pytest.UsageError, match="missing the live_write marker"):
        pytest_collection_modifyitems(items=[item])


def test_guard_lists_every_offender() -> None:
    items = [
        _item("t::a", _Marker("skipif", reason=_WRITE_GATE_REASON)),
        _item("t::b", _Marker("skipif", reason=_WRITE_GATE_REASON), _Marker("live_write")),
        _item("t::c", _Marker("skipif", reason=_WRITE_GATE_REASON)),
    ]
    with pytest.raises(pytest.UsageError) as excinfo:
        pytest_collection_modifyitems(items=items)
    message = str(excinfo.value)
    assert "t::a" in message
    assert "t::c" in message
    assert "t::b" not in message  # carries live_write, not an offender


def test_guard_passes_when_marker_present() -> None:
    item = _item("t::a", _Marker("skipif", reason=_WRITE_GATE_REASON), _Marker("live_write"))
    pytest_collection_modifyitems(items=[item])  # must not raise


def test_guard_ignores_non_write_gated_tests() -> None:
    items = [
        _item("t::read", _Marker("skipif", reason="needs live hardware")),
        _item("t::plain"),
    ]
    pytest_collection_modifyitems(items=items)  # must not raise

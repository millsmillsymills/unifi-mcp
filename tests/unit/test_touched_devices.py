"""Unit coverage for the ``TouchedDevices`` bench-bricking guard (#271).

``TouchedDevices`` is the safety net that stops the live write sweep from
applying more than one destructive op to the same device per session. It
ships in ``tests/integration/conftest.py`` and previously had no coverage of
its own — a refactor that dropped ``.strip().lower()`` or swapped
``pytest.fail`` for a warning would silently disarm it (#276).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.integration.conftest import TouchedDevices

_LIVE_TEST_PATH = Path(__file__).parent.parent / "integration" / "test_all_tools_live.py"

# Destructive Network tools: at most one may target a given MAC per session.
_DESTRUCTIVE_TOOLS = frozenset(
    {
        "unifi_network_forget_device",
        "unifi_network_adopt_device",
        "unifi_network_upgrade_device",
        "unifi_network_provision_device",
        "unifi_network_restart_device",
    }
)


def test_first_claim_is_recorded() -> None:
    """A first claim succeeds; a second claim on the same MAC then fails,
    proving the first was recorded."""
    guard = TouchedDevices()
    guard.claim("aa:bb:cc:11:22:33", "forget")

    with pytest.raises(pytest.fail.Exception, match="#271"):
        guard.claim("aa:bb:cc:11:22:33", "adopt")


def test_repeat_claim_names_prior_op() -> None:
    guard = TouchedDevices()
    guard.claim("aa:bb:cc:11:22:33", "forget")

    with pytest.raises(pytest.fail.Exception, match="already touched by forget"):
        guard.claim("aa:bb:cc:11:22:33", "restart")


def test_distinct_macs_claim_independently() -> None:
    guard = TouchedDevices()
    guard.claim("aa:bb:cc:11:22:33", "forget")
    guard.claim("aa:bb:cc:44:55:66", "restart")  # must not raise


@pytest.mark.parametrize(
    "variant",
    [
        "aa:bb:cc:11:22:33",  # colon form
        "aa-bb-cc-11-22-33",  # dash form
        "aabbcc112233",  # no separators
        "AA:BB:CC:11:22:33",  # upper-case
        "  aa:bb:cc:11:22:33  ",  # surrounding whitespace
    ],
)
def test_equivalent_mac_forms_collide(variant: str) -> None:
    """Every separator/case/whitespace variant folds to the same canonical
    12-hex key, so it collides with a prior claim on the same device (#278)."""
    guard = TouchedDevices()
    guard.claim("aabbcc112233", "forget")

    with pytest.raises(pytest.fail.Exception, match="#271"):
        guard.claim(variant, "adopt")


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "   ",  # whitespace only
        "aa:bb:cc:11:22",  # too short (10 hex)
        "aa:bb:cc:11:22:33:44",  # too long (14 hex)
        "zz:zz:zz:zz:zz:zz",  # non-hex
        "not-a-mac",  # garbage
    ],
)
def test_invalid_mac_is_rejected(bad: str) -> None:
    """Unparseable input fails fast rather than slipping through as a
    degenerate key (#278)."""
    guard = TouchedDevices()
    with pytest.raises(pytest.fail.Exception, match="invalid MAC"):
        guard.claim(bad, "forget")


def _destructive_invoke_tool(call: ast.Call) -> str | None:
    """Tool name if ``call`` is ``_invoke(client, "<destructive>", ...)``."""
    if not (isinstance(call.func, ast.Name) and call.func.id == "_invoke"):
        return None
    if len(call.args) < 2 or not isinstance(call.args[1], ast.Constant):
        return None
    name = call.args[1].value
    if isinstance(name, str) and name in _DESTRUCTIVE_TOOLS:
        return name
    return None


def _calls_touched_devices_claim(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "claim"
        and isinstance(func.value, ast.Name)
        and func.value.id == "touched_devices"
    )


def test_every_destructive_test_guards_with_touched_devices() -> None:
    """AST invariant: any test that invokes a destructive Network tool must
    also call ``touched_devices.claim`` somewhere in its body. Catches a
    refactor that deletes a claim line and re-arms the #271 brick scenario.

    Checked at function granularity rather than per-invoke ordering because
    ``test_forget_adopt_cycle`` deliberately runs a recovery adopt without a
    claim (conftest #271 recovery path); that function still claims earlier.
    """
    tree = ast.parse(_LIVE_TEST_PATH.read_text(encoding="utf-8"), filename=str(_LIVE_TEST_PATH))

    guarded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
        if not any(_destructive_invoke_tool(c) for c in calls):
            continue
        assert any(_calls_touched_devices_claim(c) for c in calls), (
            f"{node.name} invokes a destructive Network tool without calling "
            "touched_devices.claim — the #271 guard would be bypassed"
        )
        guarded.add(node.name)

    assert guarded == {
        "test_provision_device_smoke",
        "test_restart_non_protected_ap",
        "test_forget_adopt_cycle",
        "test_upgrade_device_smoke",
    }, f"unexpected set of destructive-op tests: {sorted(guarded)}"

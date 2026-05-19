"""Deterministic retry/backoff timing for ``BaseUniFiClient._request``.

Companion to ``test_base.py``'s outcome-level retry tests: those prove a
retry eventually happens; these pin down *when* and *how long* it sleeps.

Without these assertions, a regression that silently narrows the retry-able
exception set, drops the ``before_sleep`` log, halves the exponential-backoff
multiplier, or stops honoring ``Retry-After`` would still pass the outcome
tests. Each test mocks ``asyncio.sleep`` (via the ``unifi_mcp.clients.base``
module reference) so the suite runs in milliseconds and never waits for the
wall clock.

Issue #251 (§2c, deterministic branch of #97). The chaos branch
(iptables/``tc netem``) stays live-only.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from unifi_mcp.clients.base import BaseUniFiClient
from unifi_mcp.errors import UniFiConnectionError, UniFiRateLimitError, UniFiTimeoutError

BASE_URL = "https://10.0.0.1:443"


class _ConcreteClient(BaseUniFiClient):
    """Minimal concrete subclass so the abstract base is instantiable in tests."""

    async def validate_connection(self) -> bool:
        return True


@pytest.fixture
def record_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace ``asyncio.sleep`` (as used by ``base.py`` and tenacity) with a
    recorder that captures the requested durations without blocking.

    The patch targets ``unifi_mcp.clients.base.asyncio.sleep``; that attribute
    is the same module-level ``asyncio.sleep`` tenacity reaches through its
    lazy ``import asyncio`` inside ``_portable_async_sleep``, so both the
    explicit 429 sleep and the tenacity-driven transient-retry sleep land in
    the same list.
    """
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("unifi_mcp.clients.base.asyncio.sleep", _fake_sleep)
    return slept


@pytest.fixture
async def client_max_retries_3() -> AsyncIterator[_ConcreteClient]:
    """A client with ``max_retries=3`` so the tenacity exp-backoff sequence
    exposes two retry sleeps (attempts 1+2 fail, attempt 3 is the last) —
    enough to verify the ``1 -> 2`` step without hitting the ``max=10`` clamp.
    """
    client = _ConcreteClient(
        base_url=BASE_URL,
        api_key="test-api-key",
        verify_ssl=False,
        timeout=5,
        max_retries=3,
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def client_max_retries_5() -> AsyncIterator[_ConcreteClient]:
    """A client with ``max_retries=5`` (4 retry sleeps) to verify the
    ``wait_exponential(max=10)`` ceiling: the sequence would otherwise be
    ``1, 2, 4, 8, 16``; clamping makes attempt 5's wait ``10`` (we only see
    four sleeps because there's no sleep *after* the final attempt).
    """
    client = _ConcreteClient(
        base_url=BASE_URL,
        api_key="test-api-key",
        verify_ssl=False,
        timeout=5,
        max_retries=5,
    )
    try:
        yield client
    finally:
        await client.close()


class TestConnectErrorRetryCount:
    """The tenacity decorator retries on every ``ConnectError`` until either
    the request succeeds or ``stop_after_attempt(max_retries)`` is reached.
    """

    @respx.mock
    async def test_two_connect_errors_then_success_yields_three_attempts(
        self,
        client_max_retries_3: _ConcreteClient,
        record_sleeps: list[float],
    ) -> None:
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ]
        result = await client_max_retries_3.get("test")
        assert result == {"ok": True}
        # Initial attempt + two retries == three attempts total.
        assert route.call_count == 3
        # Two retry sleeps fired (no sleep after the final, successful, attempt).
        assert len(record_sleeps) == 2

    @respx.mock
    async def test_max_retries_attempts_then_surfaces_connection_error(
        self,
        client_max_retries_3: _ConcreteClient,
        record_sleeps: list[float],
    ) -> None:
        """All attempts fail with ``ConnectError`` -> mapped ``UniFiConnectionError``,
        with exactly ``max_retries`` total attempts and ``max_retries - 1`` retry
        sleeps.
        """
        route = respx.get(f"{BASE_URL}/test").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(UniFiConnectionError, match="refused"):
            await client_max_retries_3.get("test")
        assert route.call_count == 3
        # Two sleeps: between attempts 1->2 and 2->3. No sleep after the last failure.
        assert len(record_sleeps) == 2


class TestTimeoutExceptionPolicyByVerb:
    """``TimeoutException`` is in the tenacity retry-on set for GET/HEAD only
    (idempotent verbs). For POST/PUT/DELETE/PATCH the request reached the
    server and might have been partially processed; a blind retry could
    double-execute the write.
    """

    @respx.mock
    async def test_get_timeout_is_retried_with_exp_backoff(
        self,
        client_max_retries_3: _ConcreteClient,
        record_sleeps: list[float],
    ) -> None:
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.ReadTimeout("slow"),
            httpx.ReadTimeout("slow"),
            httpx.Response(200, json={"ok": True}),
        ]
        assert await client_max_retries_3.get("test") == {"ok": True}
        assert route.call_count == 3
        assert len(record_sleeps) == 2

    @pytest.mark.parametrize("verb", ["post", "put", "delete"])
    @respx.mock
    async def test_non_idempotent_timeout_fails_fast_with_no_sleeps(
        self,
        client_max_retries_3: _ConcreteClient,
        record_sleeps: list[float],
        verb: str,
    ) -> None:
        """POST/PUT/DELETE: exactly one attempt, zero retry sleeps."""
        route = getattr(respx, verb)(f"{BASE_URL}/test").mock(side_effect=httpx.ReadTimeout("slow"))
        method = getattr(client_max_retries_3, verb)
        kwargs: dict[str, object] = {} if verb == "delete" else {"json": {"x": 1}}
        with pytest.raises(UniFiTimeoutError):
            await method("test", **kwargs)
        assert route.call_count == 1
        assert record_sleeps == [], f"non-idempotent {verb.upper()} must not sleep before retrying"


class TestExponentialBackoffSequence:
    """``wait_exponential(multiplier=1, min=1, max=10)`` produces a deterministic
    sleep schedule on transient-error retries: ``1, 2, 4, 8, 10, 10, ...``.
    """

    @respx.mock
    async def test_three_retries_observe_one_two_four_sequence(
        self,
        client_max_retries_5: _ConcreteClient,
        record_sleeps: list[float],
    ) -> None:
        """With ``max_retries=5`` and four consecutive ``ConnectError``s plus a
        final success, the recorder sees ``[1, 2, 4, 8]``: the canonical
        ``multiplier=1`` doubling, below the ``max=10`` clamp.
        """
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ]
        assert await client_max_retries_5.get("test") == {"ok": True}
        assert route.call_count == 5
        assert record_sleeps == [1, 2, 4, 8]

    @respx.mock
    async def test_backoff_clamped_to_max_10(
        self,
        record_sleeps: list[float],
    ) -> None:
        """A long retry budget exposes the ``max=10`` ceiling: once the
        doubled value would exceed 10, the wait stays at 10. Verifies the
        regression where a misconfigured ``max`` (e.g. dropped to 5) would
        silently shorten the cap.
        """
        client = _ConcreteClient(base_url=BASE_URL, api_key="k", timeout=5, max_retries=7)
        try:
            route = respx.get(f"{BASE_URL}/test")
            route.side_effect = [
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                httpx.Response(200, json={"ok": True}),
            ]
            assert await client.get("test") == {"ok": True}
            # Expected: [1, 2, 4, 8, 10, 10]; the 5th/6th would be 16/32
            # without the max=10 ceiling.
            assert record_sleeps == [1, 2, 4, 8, 10, 10]
        finally:
            await client.close()


class TestRetryAfterHonoring:
    """The 429 path is independent of the tenacity transient-retry loop. It
    sleeps for ``Retry-After`` (capped to ``_MAX_RETRY_AFTER_SECONDS``) on
    idempotent verbs only.
    """

    @respx.mock
    async def test_retry_after_value_observed_exactly(
        self,
        client_max_retries_3: _ConcreteClient,
        record_sleeps: list[float],
    ) -> None:
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.Response(429, text="rate limited", headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": True}),
        ]
        assert await client_max_retries_3.get("test") == {"ok": True}
        assert route.call_count == 2
        # Exactly one sleep, exactly the header value (well under the 30s cap).
        assert record_sleeps == [7]

    @respx.mock
    async def test_missing_retry_after_falls_back_to_one_second(
        self,
        client_max_retries_3: _ConcreteClient,
        record_sleeps: list[float],
    ) -> None:
        """Header absent -> fixed 1s sleep (NOT exp-backoff). Pins down the
        current policy: the 429 loop has its own dwell, separate from
        ``wait_exponential``.
        """
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json={"ok": True}),
        ]
        assert await client_max_retries_3.get("test") == {"ok": True}
        assert record_sleeps == [1]

    @respx.mock
    async def test_repeated_429_uses_header_each_time(
        self,
        client_max_retries_3: _ConcreteClient,
        record_sleeps: list[float],
    ) -> None:
        """Two 429s followed by success -> two sleeps, each at the per-response
        Retry-After value. Confirms the loop reads the header per attempt
        rather than caching it.
        """
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.Response(429, text="rate limited", headers={"Retry-After": "2"}),
            httpx.Response(429, text="rate limited", headers={"Retry-After": "3"}),
            httpx.Response(200, json={"ok": True}),
        ]
        assert await client_max_retries_3.get("test") == {"ok": True}
        assert route.call_count == 3
        assert record_sleeps == [2, 3]


class TestBeforeSleepLogging:
    """``before_sleep_log(logger, logging.WARNING)`` must fire a WARNING on
    every tenacity-driven retry — without it, transient failures vanish from
    operator-visible logs.
    """

    @pytest.mark.usefixtures("record_sleeps")
    @respx.mock
    async def test_warning_logged_for_each_connect_error_retry(
        self,
        client_max_retries_3: _ConcreteClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ]
        with caplog.at_level(logging.WARNING, logger="unifi_mcp.clients.base"):
            assert await client_max_retries_3.get("test") == {"ok": True}

        retry_warnings = [
            r for r in caplog.records if r.levelno == logging.WARNING and "retrying" in r.getMessage().lower()
        ]
        # One ``before_sleep`` log per retry sleep.
        assert len(retry_warnings) == 2, (
            f"expected 2 before_sleep WARNINGs (one per retry); got {[r.getMessage() for r in caplog.records]!r}"
        )

    @pytest.mark.usefixtures("record_sleeps")
    @respx.mock
    async def test_warning_logged_for_each_429_retry(
        self,
        client_max_retries_3: _ConcreteClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The 429 loop emits its own ``Rate limited (429) ... sleeping ...``
        WARNING per attempt; this is distinct from the tenacity
        ``before_sleep`` warning but plays the same role for the rate-limit
        path.
        """
        route = respx.get(f"{BASE_URL}/test")
        route.side_effect = [
            httpx.Response(429, text="rate limited", headers={"Retry-After": "2"}),
            httpx.Response(429, text="rate limited", headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
        with caplog.at_level(logging.WARNING, logger="unifi_mcp.clients.base"):
            assert await client_max_retries_3.get("test") == {"ok": True}

        rate_limit_warnings = [
            r for r in caplog.records if r.levelno == logging.WARNING and "rate limited" in r.getMessage().lower()
        ]
        assert len(rate_limit_warnings) == 2, (
            f"expected 2 rate-limit WARNINGs; got {[r.getMessage() for r in caplog.records]!r}"
        )


class TestRateLimitBudgetExhaustion:
    """When the 429 loop runs out of retries it must surface
    ``UniFiRateLimitError`` rather than looping forever — and the sleep
    sequence must stop after the configured budget.
    """

    @respx.mock
    async def test_persistent_429_sleeps_bounded_by_max_retries(
        self,
        client_max_retries_3: _ConcreteClient,
        record_sleeps: list[float],
    ) -> None:
        route = respx.get(f"{BASE_URL}/test").mock(
            return_value=httpx.Response(429, text="rate limited", headers={"Retry-After": "1"})
        )
        with pytest.raises(UniFiRateLimitError, match="429"):
            await client_max_retries_3.get("test")
        # max_retries=3 -> initial + 3 retries == 4 attempts, 3 sleeps.
        assert route.call_count == 1 + 3
        assert record_sleeps == [1, 1, 1]

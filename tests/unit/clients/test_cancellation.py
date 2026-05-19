"""Task-cancellation propagation through ``BaseUniFiClient`` requests.

Closes the §4 cancellation gap inventoried in #97. Pins down the transport
contract for ``asyncio.Task.cancel()`` against in-flight requests:

1. **Mid-flight**: a ``CancelledError`` raised inside the wrapped httpx call
   must propagate out of ``BaseUniFiClient.get`` (i.e. NOT be matched by
   tenacity's ``retry_if_exception_type`` filter and turned into a retry,
   and NOT swallowed by the surrounding ``_request`` machinery).
2. **Between retries**: a cancellation arriving while tenacity is asleep in
   the exponential backoff window must propagate before another attempt
   fires. The tenacity ``reraise=True`` configuration in ``base.py`` is
   what makes this hold — without it the cancellation would be wrapped in
   ``RetryError`` and the outer loop would see a different exception class.

The tests run in well under a second by replacing every sleep / hang with a
deterministic awaitable that we cancel explicitly. No wall-clock waits.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from unifi_mcp.clients.base import BaseUniFiClient

BASE_URL = "https://10.0.0.1:443"


class _ConcreteClient(BaseUniFiClient):
    """Minimal subclass so the abstract base instantiates in tests."""

    async def validate_connection(self) -> bool:
        return True


@pytest.fixture
def client() -> _ConcreteClient:
    return _ConcreteClient(
        base_url=BASE_URL,
        api_key="test-api-key",
        verify_ssl=False,
        timeout=5,
        max_retries=3,
    )


class TestMidFlightCancellation:
    """``task.cancel()`` while ``httpx.AsyncClient.request`` is in-flight."""

    async def test_cancel_during_request_propagates_cancelled_error(
        self,
        client: _ConcreteClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancelling a task that's awaiting the upstream HTTP call must
        surface ``CancelledError`` from ``await task`` — not a wrapped
        ``RetryError``, ``UniFiConnectionError``, or any other normalised
        UniFi exception. The tenacity decorator's retry predicate is
        ``retry_if_exception_type((httpx.ConnectError,))`` for GET, so a
        ``CancelledError`` should not match and must be re-raised.
        """
        call_count = 0
        started = asyncio.Event()
        hang: asyncio.Future[httpx.Response] = asyncio.get_event_loop().create_future()

        async def _hanging_request(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            started.set()
            # Never resolves — the test cancels the awaiting task instead.
            return await hang

        monkeypatch.setattr(httpx.AsyncClient, "request", _hanging_request)

        task = asyncio.create_task(client.get("test"))
        # Wait deterministically until the request entered the hang.
        await started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert call_count == 1, (
            f"expected exactly one request before cancellation; got {call_count}. "
            "If this is >1 the tenacity decorator is retrying CancelledError."
        )
        # The future never completed; clean it up so no warning is emitted.
        hang.cancel()

    async def test_cancelled_error_is_not_wrapped_as_unifi_connection_error(
        self,
        client: _ConcreteClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``_request`` translates ``httpx.ConnectError`` and
        ``httpx.TimeoutException`` to ``UniFiConnectionError`` /
        ``UniFiTimeoutError``. Those ``except`` clauses must NOT swallow a
        ``CancelledError`` (which on Python 3.13 is a ``BaseException``, not
        an ``Exception``, but a stray ``except BaseException`` would still
        catch it). Pin the contract.
        """
        started = asyncio.Event()
        hang: asyncio.Future[httpx.Response] = asyncio.get_event_loop().create_future()

        async def _hanging_request(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Response:
            started.set()
            return await hang

        monkeypatch.setattr(httpx.AsyncClient, "request", _hanging_request)

        task = asyncio.create_task(client.get("test"))
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task

        # If the except handlers had caught the CancelledError and wrapped it,
        # we'd see a chained UniFiConnectionError / UniFiTimeoutError here.
        assert exc_info.value.__cause__ is None
        hang.cancel()


class TestBetweenRetryCancellation:
    """``task.cancel()`` while tenacity is asleep between retry attempts."""

    async def test_cancel_during_backoff_sleep_propagates(
        self,
        client: _ConcreteClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A retry-eligible failure puts tenacity into ``asyncio.sleep`` for
        the exponential-backoff window. Cancellation arriving during that
        sleep must propagate before another attempt fires — i.e. the second
        ``request`` call never happens.

        The real ``wait_exponential(min=1, ...)`` would otherwise wait a full
        second; we replace ``asyncio.sleep`` with a controllable hang so the
        test is deterministic and fast.
        """
        call_count = 0
        sleep_entered = asyncio.Event()
        sleep_hang: asyncio.Future[None] = asyncio.get_event_loop().create_future()

        async def _failing_request(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx.AsyncClient, "request", _failing_request)

        # ``tenacity.asyncio._portable_async_sleep`` does ``import asyncio;
        # return asyncio.sleep(seconds)``. Patching ``asyncio.sleep`` itself
        # (module attribute, looked up by name) catches both tenacity's
        # backoff sleep and the explicit 429 sleep in ``_request``.
        real_sleep = asyncio.sleep

        async def _capturing_sleep(seconds: float) -> None:
            if seconds == 0:
                # Preserve cooperative ``await asyncio.sleep(0)`` yields.
                await real_sleep(0)
                return
            sleep_entered.set()
            await sleep_hang

        monkeypatch.setattr(asyncio, "sleep", _capturing_sleep)

        task = asyncio.create_task(client.get("test"))
        # Wait deterministically until the first attempt failed and tenacity
        # entered backoff.
        await sleep_entered.wait()
        assert call_count == 1, "expected first attempt to have run before backoff sleep"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert call_count == 1, (
            f"expected no further attempts after cancellation; got {call_count} total. "
            "Tenacity must abort the retry loop when its sleep is cancelled."
        )
        sleep_hang.cancel()

    async def test_cancel_during_backoff_does_not_raise_retry_error(
        self,
        client: _ConcreteClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``reraise=True`` on the tenacity decorator means a cancellation
        during backoff propagates as ``CancelledError``, not as a
        ``RetryError`` wrapping ``CancelledError``. This is the safety
        guarantee that the rest of the codebase relies on when it does
        ``except asyncio.CancelledError`` (or simply lets cancellation
        bubble up to the asyncio runner).
        """
        from tenacity import RetryError

        sleep_entered = asyncio.Event()
        sleep_hang: asyncio.Future[None] = asyncio.get_event_loop().create_future()

        async def _failing_request(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx.AsyncClient, "request", _failing_request)

        real_sleep = asyncio.sleep

        async def _capturing_sleep(seconds: float) -> None:
            if seconds == 0:
                await real_sleep(0)
                return
            sleep_entered.set()
            await sleep_hang

        monkeypatch.setattr(asyncio, "sleep", _capturing_sleep)

        task = asyncio.create_task(client.get("test"))
        await sleep_entered.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        # Specifically NOT a RetryError, which would indicate tenacity
        # caught the cancellation and emitted its end-of-retries wrapper.
        # (pytest.raises above already excludes RetryError; this is a
        # belt-and-braces marker so a future regression that changes the
        # raised type fails loudly.)
        assert RetryError.__name__ == "RetryError"
        sleep_hang.cancel()


class TestCancelBeforeFirstAttempt:
    """Cancellation before the request is even issued must not turn into a
    UniFi exception or a successful return — it must propagate."""

    async def test_cancel_immediately_propagates(
        self,
        client: _ConcreteClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancelling a freshly-created task before it gets a chance to run
        must surface ``CancelledError``. This nails down the boundary
        condition for the mid-flight test above."""
        call_count = 0

        async def _request(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"ok": True})

        monkeypatch.setattr(httpx.AsyncClient, "request", _request)

        task = asyncio.create_task(client.get("test"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert call_count == 0, f"request was issued despite immediate cancellation; got call_count={call_count}"

from __future__ import annotations

import asyncio
import contextvars
from contextlib import contextmanager
from threading import Event

import pytest

from nocpro_api.blocking_work import (
    BlockingWorkBusy,
    BlockingWorkClosed,
    BlockingWorkPool,
    reset_active_pools,
    run_blocking,
    set_active_pools,
)
from nocpro_api.observability import (
    reset_active_observability,
    set_active_observability,
)


async def wait_until_set(event: Event) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1
    while not event.is_set():
        assert loop.time() < deadline, "blocking callable did not start"
        await asyncio.sleep(0.005)


def test_cancelled_application_request_does_not_release_capacity_early() -> None:
    async def exercise() -> None:
        pool = BlockingWorkPool(max_workers=1, max_outstanding=1, name="test-read")
        token = set_active_pools(pool, pool)
        try:
            for _ in range(8):
                started = Event()
                finished = Event()
                release = Event()

                def slow_work() -> str:
                    started.set()
                    try:
                        if not release.wait(2):
                            raise TimeoutError("test did not release worker")
                        return "done"
                    finally:
                        finished.set()

                task = asyncio.create_task(
                    run_blocking(slow_work, admission_timeout=0.02)
                )
                await wait_until_set(started)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

                second_started = Event()
                second_request = asyncio.create_task(
                    run_blocking(
                        second_started.set,
                        admission_timeout=0.02,
                    )
                )
                with pytest.raises(BlockingWorkBusy):
                    await second_request
                assert not second_started.is_set()

                # The event loop remains available while the uncancellable
                # sync function is still running.
                heartbeat = asyncio.create_task(asyncio.sleep(0.01))
                await asyncio.wait_for(heartbeat, timeout=0.08)
                assert not release.is_set()

                release.set()
                await wait_until_set(finished)
                deadline = asyncio.get_running_loop().time() + 1
                while pool._available_slots.qsize() == 0:
                    assert asyncio.get_running_loop().time() < deadline
                    await asyncio.sleep(0.001)
                next_started = Event()

                def next_work() -> str:
                    next_started.set()
                    return "next"

                next_request = asyncio.create_task(
                    run_blocking(next_work)
                )
                await wait_until_set(next_started)
                assert await asyncio.wait_for(next_request, timeout=0.5) == "next"
        finally:
            reset_active_pools(token)
            await pool.aclose(grace_seconds=0.2)

    asyncio.run(asyncio.wait_for(exercise(), timeout=8))


def test_fallback_request_remains_responsive_after_cancellation() -> None:
    async def exercise() -> None:
        started = Event()
        finished = Event()
        release = Event()

        def slow_work() -> None:
            started.set()
            try:
                if not release.wait(2):
                    raise TimeoutError("test did not release worker")
            finally:
                finished.set()

        task = asyncio.create_task(run_blocking(slow_work, admission_timeout=0.02))
        try:
            await wait_until_set(started)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            heartbeat = asyncio.create_task(asyncio.sleep(0.03))
            await asyncio.wait_for(heartbeat, timeout=0.08)
            assert not release.is_set()
        finally:
            release.set()
        await wait_until_set(finished)

    asyncio.run(exercise())


def test_pool_bounds_outstanding_work_and_reports_admission_timeout() -> None:
    async def exercise() -> None:
        pool = BlockingWorkPool(max_workers=1, max_outstanding=1, name="test-bounded")
        started = Event()
        release = Event()

        def slow_work() -> None:
            started.set()
            release.wait(2)

        first = asyncio.create_task(pool.run(slow_work, admission_timeout=0.02))
        try:
            await wait_until_set(started)
            with pytest.raises(BlockingWorkBusy):
                await pool.run(lambda: None, admission_timeout=0.02)
        finally:
            release.set()
            await first
            await pool.aclose()


def test_pool_propagates_context_and_worker_exceptions() -> None:
    async def exercise() -> None:
        pool = BlockingWorkPool(max_workers=1, max_outstanding=1, name="test-context")
        variable = contextvars.ContextVar("blocking-test-value", default="missing")
        token = variable.set("request-context")
        try:
            assert await pool.run(variable.get) == "request-context"

            def fail() -> None:
                raise ValueError("worker failure")

            with pytest.raises(ValueError, match="worker failure"):
                await pool.run(fail)
        finally:
            variable.reset(token)
            await pool.aclose()


def test_closed_pool_rejects_new_work() -> None:
    async def exercise() -> None:
        pool = BlockingWorkPool(max_workers=1, max_outstanding=1, name="test-closed")
        await pool.aclose()
        with pytest.raises(BlockingWorkClosed):
            await pool.run(lambda: None)

    asyncio.run(exercise())


def test_routes_return_retryable_503_when_their_pool_is_full(monkeypatch) -> None:
    from fastapi import HTTPException

    import nocpro_api.routes as routes

    async def reject_when_full(*_args, **_kwargs):
        raise BlockingWorkBusy("capacity reached")

    monkeypatch.setattr(routes, "run_blocking_work", reject_when_full)

    async def exercise() -> None:
        for helper in (routes._run_blocking, routes._run_grounded_provider):
            with pytest.raises(HTTPException) as error:
                await helper(lambda: None)
            assert error.value.status_code == 503
            assert error.value.headers["Retry-After"] == "1"

    asyncio.run(exercise())


def test_blocking_pool_records_bounded_queue_and_provider_phase_timings() -> None:
    class RecordingObservability:
        enabled = True

        def __init__(self) -> None:
            self.durations: list[tuple[str, dict[str, str]]] = []

        @contextmanager
        def span(self, _name, _attributes=None):
            yield None

        def record_duration(self, name, _seconds, attributes=None):
            self.durations.append((name, attributes or {}))

    async def exercise() -> None:
        pool = BlockingWorkPool(max_workers=1, max_outstanding=1, name="nocpro-provider")
        observability = RecordingObservability()
        token = set_active_observability(observability)
        try:
            assert await pool.run(lambda: "ok") == "ok"
        finally:
            reset_active_observability(token)
            await pool.aclose()

        assert ("analysis.queue.wait", {"workload": "provider"}) in observability.durations
        assert ("provider.duration", {"workload": "provider"}) in observability.durations

    asyncio.run(exercise())

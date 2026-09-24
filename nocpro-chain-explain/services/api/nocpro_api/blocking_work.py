"""Bounded bridges for the remaining synchronous analysis/provider functions.

The application owns one pool for API reads/snapshot preparation and one for
providers. A caller may be cancelled while its worker continues; the worker's
slot therefore remains occupied until the concurrent future actually ends.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import contextvars
from functools import partial
import os
from threading import BoundedSemaphore, Lock, get_ident
import time
from typing import Any, Callable, TypeVar

from .observability import active_observability


T = TypeVar("T")


class BlockingWorkBusy(RuntimeError):
    """The bounded pool has no admission slot before its deadline."""


class BlockingWorkClosed(RuntimeError):
    """Work was submitted after the application pool began shutting down."""


ActivePools = tuple["BlockingWorkPool", "BlockingWorkPool"]
_active_pools: contextvars.ContextVar[ActivePools | None] = contextvars.ContextVar(
    "nocpro_active_blocking_work_pools", default=None
)
_fallback_lock = Lock()
_fallback_pools: dict[str, tuple[ThreadPoolExecutor, BoundedSemaphore]] = {}


def _instrument_worker_call(call: Callable[[], T], workload: str) -> T:
    observability = active_observability()
    if observability is None:
        return call()
    metric = "provider.duration" if workload == "provider" else "analysis.compute.duration"
    started = time.perf_counter()
    with observability.span("blocking_work.execute", {"workload": workload}):
        try:
            return call()
        finally:
            observability.record_duration(
                metric,
                max(0.0, time.perf_counter() - started),
                {"workload": workload},
            )


def _record_admission_wait(workload: str, started: float, finished: float) -> None:
    observability = active_observability()
    if observability is None:
        return
    observability.record_duration(
        "analysis.queue.wait",
        max(0.0, finished - started),
        {"workload": workload},
    )


def set_active_pools(read_pool: "BlockingWorkPool", provider_pool: "BlockingWorkPool"):
    return _active_pools.set((read_pool, provider_pool))


def reset_active_pools(token: contextvars.Token) -> None:
    _active_pools.reset(token)


def active_pool(workload: str) -> "BlockingWorkPool | None":
    pools = _active_pools.get()
    if pools is None:
        return None
    if workload == "api-read":
        return pools[0]
    if workload == "provider":
        return pools[1]
    raise ValueError(f"unknown blocking workload: {workload}")


def _fallback_limit(workload: str) -> int:
    if workload == "provider":
        return 2
    if workload == "api-read":
        return 4
    raise ValueError(f"unknown blocking workload: {workload}")


async def _await_concurrent_result(
    loop: asyncio.AbstractEventLoop,
    future: Future[T],
    *,
    owner_thread_id: int,
    on_worker_done: Callable[[Future[T]], None],
    on_loop_done: Callable[[], None] | None = None,
) -> T:
    """Bridge a concurrent future without linking caller cancellation to it."""
    result = loop.create_future()

    def completed(completed_future: Future[T]) -> None:
        on_worker_done(completed_future)

        def finish_on_loop() -> None:
            if on_loop_done is not None:
                on_loop_done()
            if result.done():
                return
            if completed_future.cancelled():
                result.cancel()
                return
            try:
                result.set_result(completed_future.result())
            except BaseException as exc:
                result.set_exception(exc)

        try:
            if get_ident() == owner_thread_id:
                finish_on_loop()
            else:
                # asyncio Futures are loop-owned; worker callbacks must marshal
                # result delivery back to the owning loop.
                # Source: https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.loop.call_soon_threadsafe
                loop.call_soon_threadsafe(finish_on_loop)
        except RuntimeError:
            # The loop may already be closed during forced shutdown. Worker-side
            # cleanup has still run, and no request can consume this result.
            pass

    future.add_done_callback(completed)
    # This bridge Future has no cancellation link to the concurrent Future.
    return await result


async def _run_on_fallback_executor(
    function: Callable[..., T],
    *args: Any,
    workload: str,
    admission_timeout: float,
    **kwargs: Any,
) -> T:
    """Use a process-owned fallback pool outside an application lifespan."""
    loop = asyncio.get_running_loop()
    limit = _fallback_limit(workload)
    with _fallback_lock:
        fallback = _fallback_pools.get(workload)
        if fallback is None:
            fallback = (
                ThreadPoolExecutor(
                    max_workers=limit,
                    thread_name_prefix=f"nocpro-fallback-{workload}",
                ),
                BoundedSemaphore(limit),
            )
            _fallback_pools[workload] = fallback
        executor, slots = fallback
    deadline = loop.time() + admission_timeout
    admission_started = loop.time()
    while not slots.acquire(blocking=False):
        remaining = deadline - loop.time()
        if remaining <= 0:
            observability = active_observability()
            _record_admission_wait(workload, admission_started, loop.time())
            if observability is not None:
                observability.record_counter(
                    "analysis.queue.rejected", attributes={"workload": workload}
                )
            raise BlockingWorkBusy(f"{workload} work admission timed out")
        await asyncio.sleep(min(0.005, remaining))
    try:
        call = partial(function, *args, **kwargs)
        _record_admission_wait(workload, admission_started, loop.time())
        future = executor.submit(
            contextvars.copy_context().run,
            _instrument_worker_call,
            call,
            workload,
        )
    except BaseException:
        slots.release()
        raise
    return await _await_concurrent_result(
        loop,
        future,
        owner_thread_id=get_ident(),
        on_worker_done=lambda _completed: slots.release(),
    )


async def run_blocking(
    function: Callable[..., T],
    *args: Any,
    workload: str = "api-read",
    admission_timeout: float = 0.25,
    pool: "BlockingWorkPool | None" = None,
    **kwargs: Any,
) -> T:
    """Run blocking code without blocking the event loop or growing an unbounded queue."""
    selected_pool = pool or active_pool(workload)
    if selected_pool is None:
        return await _run_on_fallback_executor(
            function,
            *args,
            workload=workload,
            admission_timeout=admission_timeout,
            **kwargs,
        )
    return await selected_pool.run(
        function,
        *args,
        admission_timeout=admission_timeout,
        **kwargs,
    )


class BlockingWorkPool:
    """Application-scoped bounded ThreadPoolExecutor with cancellation-safe slots."""

    def __init__(self, *, max_workers: int, max_outstanding: int, name: str) -> None:
        if max_workers < 1 or max_outstanding < max_workers:
            raise ValueError("max_outstanding must be >= max_workers >= 1")
        self._name = name
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=name,
        )
        self._available_slots: asyncio.Queue[None] = asyncio.Queue(
            maxsize=max_outstanding
        )
        for _ in range(max_outstanding):
            self._available_slots.put_nowait(None)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._lock = Lock()
        self._pending: set[Future[Any]] = set()
        self._closed = False

    @classmethod
    def from_environment(cls, *, workload: str) -> "BlockingWorkPool":
        if workload == "api-read":
            workers_name, outstanding_name, workers_default, outstanding_default = (
                "NOCPRO_READ_WORKERS", "NOCPRO_READ_MAX_OUTSTANDING", 4, 8
            )
        elif workload == "provider":
            workers_name, outstanding_name, workers_default, outstanding_default = (
                "NOCPRO_PROVIDER_WORKERS", "NOCPRO_PROVIDER_MAX_OUTSTANDING", 2, 4
            )
        else:
            raise ValueError(f"unknown blocking workload: {workload}")
        workers = int(os.environ.get(workers_name, str(workers_default)))
        outstanding = int(os.environ.get(outstanding_name, str(outstanding_default)))
        return cls(max_workers=workers, max_outstanding=outstanding, name=f"nocpro-{workload}")

    async def run(
        self,
        function: Callable[..., T],
        *args: Any,
        admission_timeout: float = 0.25,
        **kwargs: Any,
    ) -> T:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
            self._loop_thread_id = get_ident()
        elif self._loop is not loop or self._loop_thread_id != get_ident():
            raise RuntimeError(f"{self._name} pool cannot be shared between event loops")
        if self._closed:
            raise BlockingWorkClosed(f"{self._name} pool is shutting down")
        admission_started = loop.time()
        try:
            await asyncio.wait_for(
                self._available_slots.get(),
                timeout=admission_timeout,
            )
        except TimeoutError as exc:
            workload = "provider" if self._name.endswith("provider") else "api-read"
            observability = active_observability()
            _record_admission_wait(workload, admission_started, loop.time())
            if observability is not None:
                observability.record_counter(
                    "analysis.queue.rejected", attributes={"workload": workload}
                )
            raise BlockingWorkBusy(f"{self._name} work admission timed out") from exc
        observability = active_observability()
        if observability is not None:
            workload = "provider" if self._name.endswith("provider") else "api-read"
            observability.record_duration(
                "analysis.queue.wait",
                max(0.0, loop.time() - admission_started),
                {"workload": workload},
            )

        if self._closed:
            self._available_slots.put_nowait(None)
            raise BlockingWorkClosed(f"{self._name} pool is shutting down")

        call = partial(function, *args, **kwargs)
        try:
            workload = "provider" if self._name.endswith("provider") else "api-read"
            future = self._executor.submit(
                contextvars.copy_context().run,
                _instrument_worker_call,
                call,
                workload,
            )
        except BaseException:
            self._available_slots.put_nowait(None)
            raise

        with self._lock:
            self._pending.add(future)

        def remove_pending(completed: Future[Any]) -> None:
            with self._lock:
                self._pending.discard(completed)

        return await _await_concurrent_result(
            loop,
            future,
            owner_thread_id=self._loop_thread_id,
            on_worker_done=remove_pending,
            on_loop_done=lambda: self._available_slots.put_nowait(None),
        )

    async def aclose(self, *, grace_seconds: float = 5.0) -> None:
        """Stop admission and wait asynchronously for a bounded grace period."""
        loop = asyncio.get_running_loop()
        if self._loop is not None and loop is not self._loop:
            raise RuntimeError(f"{self._name} pool must close on its owning event loop")
        self._closed = True
        with self._lock:
            pending = list(self._pending)
        for future in pending:
            future.cancel()
        try:
            if pending and grace_seconds > 0:
                wrapped = [asyncio.wrap_future(future, loop=loop) for future in pending]
                await asyncio.wait_for(
                    asyncio.gather(*wrapped, return_exceptions=True),
                    timeout=grace_seconds,
                )
        except TimeoutError:
            pass
        finally:
            # Python cannot force-stop a running thread. Synchronous
            # shutdown(wait=True) here would block the event loop again.
            self._executor.shutdown(wait=False, cancel_futures=True)

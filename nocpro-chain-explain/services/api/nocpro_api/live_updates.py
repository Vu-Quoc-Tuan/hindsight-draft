"""Bounded SSE transport for durable resource invalidations.

The event journal is authoritative only for ordering invalidations. Clients
must reload the corresponding REST resources; no analysis payload is streamed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import re
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.background import BackgroundTask

from .persistence.change_journal import (
    MAX_JOURNAL_REVISION,
    MAX_REPLAY_BATCH,
    ChangeEvent,
    ChangeJournalUnavailable,
    JournalPosition,
    journal_position,
    live_updates_enabled,
    read_changes_after,
)


LOGGER = logging.getLogger(__name__)
MAX_CURSOR_LENGTH = 56
MAX_EVENT_BYTES = 16 * 1024
DEFAULT_HEARTBEAT_SECONDS = 15.0
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_QUEUE_SIZE = 256
DEFAULT_MAX_SUBSCRIBERS = 64
_CURSOR_RE = re.compile(
    r"(?P<epoch>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}):(?P<revision>0|[1-9][0-9]{0,18})\Z"
)

events_router = APIRouter(prefix="/api/v1")


@dataclass(frozen=True)
class ChangeCursor:
    epoch: UUID
    revision: int


@dataclass(frozen=True)
class ResetNotice:
    reason: str
    position: JournalPosition


@dataclass(eq=False)
class _Subscriber:
    queue: asyncio.Queue[ChangeEvent | ResetNotice | None]
    overflowed: bool = False
    closed: bool = False


class SSEFrameTooLarge(ValueError):
    """A journal record exceeds the bounded SSE wire contract."""


class LiveUpdateCapacity(RuntimeError):
    """The API worker has reached its configured SSE connection limit."""


def parse_event_cursor(value: str | None) -> ChangeCursor | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_CURSOR_LENGTH:
        raise ValueError("Last-Event-ID is malformed")
    match = _CURSOR_RE.fullmatch(value)
    if match is None:
        raise ValueError("Last-Event-ID is malformed")
    revision = int(match.group("revision"))
    if revision > MAX_JOURNAL_REVISION:
        raise ValueError("Last-Event-ID revision is out of range")
    try:
        epoch = UUID(match.group("epoch"))
    except ValueError as exc:
        raise ValueError("Last-Event-ID epoch is malformed") from exc
    return ChangeCursor(epoch=epoch, revision=revision)


def _sse_frame(
    *,
    event: str,
    data: dict,
    event_id: str | None = None,
) -> bytes:
    encoded = json.dumps(
        data,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {encoded}")
    frame = ("\n".join(lines) + "\n\n").encode("utf-8")
    if len(frame) > MAX_EVENT_BYTES:
        raise SSEFrameTooLarge("serialized SSE event exceeds the size limit")
    return frame


def _change_frame(change: ChangeEvent) -> bytes:
    return _sse_frame(
        event="invalidate",
        event_id=change.event_id,
        data=change.to_payload(),
    )


def _reset_frame(reason: str, position: JournalPosition) -> bytes:
    return _sse_frame(
        event="reset",
        event_id=f"{position.epoch}:{position.revision}",
        data={
            "reason": reason,
            "epoch": str(position.epoch),
            "revision": position.revision,
        },
    )


def _heartbeat_frame(now: datetime | None = None) -> bytes:
    current = now or datetime.now(timezone.utc)
    timestamp = current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return _sse_frame(
        event="heartbeat",
        data={
            "schema_version": "change-event-v1",
            "server_time": timestamp,
        },
    )


class ChangeEventHub:
    """One bounded journal tailer and queue fan-out per API worker process."""

    def __init__(
        self,
        sessions: async_sessionmaker,
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        max_subscribers: int = DEFAULT_MAX_SUBSCRIBERS,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if not isinstance(queue_size, int) or isinstance(queue_size, bool) or queue_size < 1:
            raise ValueError("queue_size must be a positive integer")
        if (
            not isinstance(max_subscribers, int)
            or isinstance(max_subscribers, bool)
            or max_subscribers < 1
        ):
            raise ValueError("max_subscribers must be a positive integer")
        self.sessions = sessions
        self.poll_seconds = poll_seconds
        self.queue_size = queue_size
        self.max_subscribers = max_subscribers
        self._subscribers: set[_Subscriber] = set()
        self._lock = asyncio.Lock()
        self._tail_task: asyncio.Task[None] | None = None
        self._last_position: JournalPosition | None = None
        self._closed = False

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def position(self) -> JournalPosition:
        return await journal_position(self.sessions)

    async def subscribe(self) -> tuple[_Subscriber, JournalPosition]:
        """Register first, then read a high-water mark for lossless handoff."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("change event hub is closed")
            if len(self._subscribers) >= self.max_subscribers:
                raise LiveUpdateCapacity("live update subscriber limit reached")
            first_subscriber = not self._subscribers
            subscriber = _Subscriber(asyncio.Queue(maxsize=self.queue_size))
            self._subscribers.add(subscriber)
            try:
                position = await self.position()
            except BaseException:
                self._subscribers.discard(subscriber)
                raise
            if first_subscriber:
                # Older durable events are replayed by this connection from
                # its own cursor, not flooded into a newly-created live queue.
                self._last_position = position
                self._tail_task = asyncio.create_task(
                    self._tail(), name="change-event-journal-tailer"
                )
            elif self._tail_task is None or self._tail_task.done():
                # Defensive recovery if a previous tail task exited unexpectedly.
                self._last_position = position
                self._tail_task = asyncio.create_task(
                    self._tail(), name="change-event-journal-tailer"
                )
            return subscriber, position

    async def unsubscribe(self, subscriber: _Subscriber) -> None:
        task: asyncio.Task[None] | None = None
        async with self._lock:
            subscriber.closed = True
            self._subscribers.discard(subscriber)
            if not self._subscribers and self._tail_task is not None:
                task = self._tail_task
                self._tail_task = None
                task.cancel()
        if task is not None and task is not asyncio.current_task():
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def close(self) -> None:
        task: asyncio.Task[None] | None
        async with self._lock:
            self._closed = True
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
            for subscriber in subscribers:
                subscriber.closed = True
                while not subscriber.queue.empty():
                    try:
                        subscriber.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                subscriber.queue.put_nowait(None)
            task = self._tail_task
            self._tail_task = None
            if task is not None:
                task.cancel()
        if task is not None and task is not asyncio.current_task():
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _publish(self, change: ChangeEvent) -> None:
        for subscriber in tuple(self._subscribers):
            if subscriber.closed or subscriber.overflowed:
                continue
            try:
                subscriber.queue.put_nowait(change)
            except asyncio.QueueFull:
                # Do not block the shared tailer or grow memory for a slow tab.
                subscriber.overflowed = True

    def _broadcast_reset(self, reason: str, position: JournalPosition) -> None:
        notice = ResetNotice(reason=reason, position=position)
        for subscriber in tuple(self._subscribers):
            if subscriber.closed or subscriber.overflowed:
                continue
            while not subscriber.queue.empty():
                try:
                    subscriber.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            try:
                subscriber.queue.put_nowait(notice)
            except asyncio.QueueFull:
                subscriber.overflowed = True

    async def _tail(self) -> None:
        task = asyncio.current_task()
        try:
            while not self._closed and self._subscribers:
                try:
                    await self._tail_once()
                except asyncio.CancelledError:
                    raise
                except (ChangeJournalUnavailable, SQLAlchemyError):
                    LOGGER.warning("Live update journal poll failed", exc_info=True)
                except Exception:
                    LOGGER.exception("Unexpected live update journal poll failure")
                await asyncio.sleep(self.poll_seconds)
        finally:
            if self._tail_task is task:
                self._tail_task = None

    async def _tail_once(self) -> None:
        previous = self._last_position
        position = await self.position()
        if previous is None:
            self._last_position = position
            return
        if position.epoch != previous.epoch:
            self._broadcast_reset("EPOCH_CHANGED", position)
            self._last_position = position
            return
        if position.revision < previous.revision:
            self._broadcast_reset("CURSOR_AHEAD", position)
            self._last_position = position
            return
        if (
            position.revision > previous.revision
            and position.min_revision > previous.revision + 1
        ):
            self._broadcast_reset("CURSOR_EXPIRED", position)
            self._last_position = position
            return

        cursor_revision = previous.revision
        while cursor_revision < position.revision:
            batch = await read_changes_after(
                self.sessions,
                position.epoch,
                cursor_revision,
                limit=MAX_REPLAY_BATCH,
                through_revision=position.revision,
            )
            if not batch or batch[0].revision != cursor_revision + 1:
                current = await self.position()
                self._broadcast_reset("CURSOR_EXPIRED", current)
                self._last_position = current
                return
            for change in batch:
                if change.revision != cursor_revision + 1:
                    current = await self.position()
                    self._broadcast_reset("CURSOR_EXPIRED", current)
                    self._last_position = current
                    return
                self._publish(change)
                cursor_revision = change.revision
        self._last_position = position


async def _stream_events(
    hub: ChangeEventHub,
    subscriber: _Subscriber,
    position: JournalPosition,
    cursor: ChangeCursor | None,
    *,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
):
    cursor_epoch = position.epoch
    cursor_revision = position.revision
    try:
        yield b"retry: 3000\n\n"

        reset_reason: str | None = None
        if cursor is None:
            reset_reason = "INITIAL_SYNC"
        elif cursor.epoch != position.epoch:
            reset_reason = "EPOCH_CHANGED"
        elif cursor.revision > position.revision:
            reset_reason = "CURSOR_AHEAD"
        elif cursor.revision < position.min_revision - 1:
            reset_reason = "CURSOR_EXPIRED"

        if reset_reason is not None:
            yield _reset_frame(reset_reason, position)
        else:
            cursor_epoch = cursor.epoch
            cursor_revision = cursor.revision
            while cursor_revision < position.revision:
                if subscriber.overflowed:
                    current = await hub.position()
                    yield _reset_frame("BUFFER_OVERFLOW", current)
                    return
                batch = await read_changes_after(
                    hub.sessions,
                    cursor_epoch,
                    cursor_revision,
                    limit=MAX_REPLAY_BATCH,
                    through_revision=position.revision,
                )
                if not batch or batch[0].revision != cursor_revision + 1:
                    current = await hub.position()
                    yield _reset_frame("CURSOR_EXPIRED", current)
                    cursor_epoch, cursor_revision = current.epoch, current.revision
                    break
                replay_gap = False
                for change in batch:
                    if change.revision != cursor_revision + 1:
                        current = await hub.position()
                        yield _reset_frame("CURSOR_EXPIRED", current)
                        cursor_epoch, cursor_revision = current.epoch, current.revision
                        replay_gap = True
                        break
                    try:
                        frame = _change_frame(change)
                    except SSEFrameTooLarge:
                        current = await hub.position()
                        yield _reset_frame("CURSOR_EXPIRED", current)
                        cursor_epoch, cursor_revision = current.epoch, current.revision
                        replay_gap = True
                        break
                    yield frame
                    cursor_revision = change.revision
                if replay_gap:
                    break

        while True:
            if subscriber.overflowed:
                current = await hub.position()
                yield _reset_frame("BUFFER_OVERFLOW", current)
                return
            if subscriber.closed and subscriber.queue.empty():
                return
            try:
                item = await asyncio.wait_for(
                    subscriber.queue.get(), timeout=heartbeat_seconds
                )
            except asyncio.TimeoutError:
                yield _heartbeat_frame()
                continue
            if item is None:
                return
            if isinstance(item, ResetNotice):
                yield _reset_frame(item.reason, item.position)
                cursor_epoch, cursor_revision = (
                    item.position.epoch,
                    item.position.revision,
                )
                continue
            if item.epoch != cursor_epoch:
                current = await hub.position()
                yield _reset_frame("EPOCH_CHANGED", current)
                cursor_epoch, cursor_revision = current.epoch, current.revision
                continue
            if item.revision <= cursor_revision:
                continue
            if item.revision != cursor_revision + 1:
                current = await hub.position()
                yield _reset_frame("CURSOR_EXPIRED", current)
                cursor_epoch, cursor_revision = current.epoch, current.revision
                continue
            try:
                frame = _change_frame(item)
            except SSEFrameTooLarge:
                current = await hub.position()
                yield _reset_frame("CURSOR_EXPIRED", current)
                return
            yield frame
            cursor_revision = item.revision
    finally:
        await hub.unsubscribe(subscriber)


@events_router.get("/events", include_in_schema=False)
async def stream_change_events(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    try:
        cursor = parse_event_cursor(last_event_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_EVENT_CURSOR", "message": str(exc)},
        ) from exc

    hub = getattr(request.app.state, "live_updates_hub", None)
    if not live_updates_enabled() or not isinstance(hub, ChangeEventHub):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LIVE_UPDATES_UNAVAILABLE"},
        )
    try:
        subscriber, position = await hub.subscribe()
    except (ChangeJournalUnavailable, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LIVE_UPDATES_UNAVAILABLE"},
        ) from exc
    except LiveUpdateCapacity as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LIVE_UPDATES_CAPACITY"},
            headers={"Retry-After": "15"},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LIVE_UPDATES_UNAVAILABLE"},
        ) from exc

    return StreamingResponse(
        _stream_events(hub, subscriber, position, cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Vary": "Last-Event-ID",
        },
        background=BackgroundTask(hub.unsubscribe, subscriber),
    )

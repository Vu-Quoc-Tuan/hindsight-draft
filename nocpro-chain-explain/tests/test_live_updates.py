from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import UUID, uuid4
from types import SimpleNamespace

import httpx2
import pytest
from starlette.requests import Request

import nocpro_api.live_updates as live_updates
from nocpro_api import create_app
from nocpro_api.live_updates import (
    ChangeCursor,
    ChangeEventHub,
    LiveUpdateCapacity,
    SSEFrameTooLarge,
    _change_frame,
    _heartbeat_frame,
    _stream_events,
    parse_event_cursor,
    stream_change_events,
)
from nocpro_api.persistence.change_journal import (
    ChangeEvent,
    JournalPosition,
    _validate_event,
    read_changes_after,
)
from nocpro_api.workspace import Workspace


class _MemoryJournal:
    """Small async journal fake; database locking is covered by C1 Postgres tests."""

    def __init__(self) -> None:
        self.epoch = uuid4()
        self.revision = 0
        self.events: dict[int, ChangeEvent] = {}

    async def position(self) -> JournalPosition:
        revisions = sorted(self.events)
        return JournalPosition(
            epoch=self.epoch,
            min_revision=revisions[0] if revisions else self.revision + 1,
            revision=self.revision,
        )

    async def read_after(
        self,
        epoch: UUID,
        revision: int,
        *,
        limit: int,
        through_revision: int | None,
    ) -> list[ChangeEvent]:
        if epoch != self.epoch:
            return []
        return [
            self.events[item_revision]
            for item_revision in sorted(self.events)
            if item_revision > revision
            and (through_revision is None or item_revision <= through_revision)
        ][:limit]

    def append(
        self,
        *,
        event_type: str = "snapshot.changed",
        snapshot_id: str = "s1",
        snapshot_version: str = "1",
        chain_id: str | None = None,
        invalidates: tuple[str, ...] = ("catalog", "chain-list"),
    ) -> ChangeEvent:
        self.revision += 1
        change = ChangeEvent(
            epoch=self.epoch,
            revision=self.revision,
            event_type=event_type,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            chain_id=chain_id,
            topology_version=None,
            identity_digest=None,
            invalidates=invalidates,
            created_at=datetime.now(timezone.utc),
        )
        self.events[change.revision] = change
        return change


def _patch_journal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def position(journal: _MemoryJournal) -> JournalPosition:
        return await journal.position()

    async def read_after(
        journal: _MemoryJournal,
        epoch: UUID,
        revision: int,
        *,
        limit: int,
        through_revision: int | None = None,
    ) -> list[ChangeEvent]:
        return await journal.read_after(
            epoch,
            revision,
            limit=limit,
            through_revision=through_revision,
        )

    monkeypatch.setattr(live_updates, "journal_position", position)
    monkeypatch.setattr(live_updates, "read_changes_after", read_after)


def test_parse_event_cursor_is_strict_and_bounded() -> None:
    epoch = uuid4()
    assert parse_event_cursor(f"{epoch}:0") == ChangeCursor(epoch, 0)
    assert parse_event_cursor(f"{epoch}:9223372036854775807") == ChangeCursor(
        epoch, 9_223_372_036_854_775_807
    )
    assert parse_event_cursor(None) is None
    for value in (
        "",
        "not-a-cursor",
        f"{epoch}:-1",
        f"{epoch}:01",
        f"{epoch}:9223372036854775808",
        f"{epoch}:{'1' * 30}",
    ):
        with pytest.raises(ValueError):
            parse_event_cursor(value)


def test_journal_identity_fields_and_wire_frames_are_bounded() -> None:
    with pytest.raises(ValueError, match="snapshot_id"):
        _validate_event(
            event_type="snapshot.changed",
            snapshot_id="x" * 256,
            snapshot_version="1",
            chain_id=None,
            topology_version=None,
            identity_digest=None,
            invalidates=["catalog"],
        )
    change = ChangeEvent(
        epoch=uuid4(),
        revision=1,
        event_type="snapshot.changed",
        snapshot_id="x" * 20_000,
        snapshot_version="1",
        chain_id=None,
        topology_version=None,
        identity_digest=None,
        invalidates=("catalog",),
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(SSEFrameTooLarge):
        _change_frame(change)


def test_journal_replay_query_is_bounded_by_the_captured_high_water_mark() -> None:
    epoch = uuid4()
    row = SimpleNamespace(
        epoch=epoch,
        revision=4,
        event_type="snapshot.changed",
        snapshot_id="s1",
        snapshot_version="1",
        chain_id=None,
        topology_version=None,
        identity_digest=None,
        invalidates=["catalog"],
        created_at=datetime.now(timezone.utc),
    )

    class Scalars:
        def all(self):
            return [row]

    class Session:
        statement = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalars(self, statement):
            self.statement = statement
            return Scalars()

    session = Session()

    class Sessions:
        def __call__(self):
            return session

    async def exercise() -> None:
        changes = await read_changes_after(
            Sessions(), epoch, 3, limit=10, through_revision=5
        )
        assert [change.revision for change in changes] == [4]
        assert "change_events.revision <=" in str(session.statement)
        with pytest.raises(ValueError):
            await read_changes_after(
                Sessions(), epoch, 3, through_revision=2
            )
        with pytest.raises(ValueError):
            await read_changes_after(Sessions(), epoch, True)

    asyncio.run(exercise())


def test_heartbeat_is_named_and_does_not_advance_event_id() -> None:
    frame = _heartbeat_frame()
    assert frame.startswith(b"event: heartbeat\n")
    assert b'"schema_version":"change-event-v1"' in frame
    assert b'"server_time":' in frame
    assert b"id:" not in frame


def test_event_stream_replays_in_bounded_pages_and_resumes_live_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_journal(monkeypatch)

    async def exercise() -> None:
        journal = _MemoryJournal()
        for index in range(105):
            journal.append(snapshot_id=f"s-{index}")
        hub = ChangeEventHub(journal, poll_seconds=0.005, queue_size=300)
        try:
            subscriber, position = await hub.subscribe()
            stream = _stream_events(
                hub,
                subscriber,
                position,
                ChangeCursor(journal.epoch, 0),
                heartbeat_seconds=0.01,
            )
            assert await anext(stream) == b"retry: 3000\n\n"
            replayed = [await anext(stream) for _ in range(105)]
            ids = [
                int(frame.split(b"\n", 1)[0].removeprefix(b"id: ").split(b":")[1])
                for frame in replayed
            ]
            assert ids == list(range(1, 106))
            assert all(b"event: invalidate\n" in frame for frame in replayed)
            assert all(b'"schema_version":"change-event-v1"' in frame for frame in replayed)

            journal.append(
                event_type="quality.changed",
                snapshot_id="s-live",
                snapshot_version="2",
                chain_id="C-1",
                invalidates=("quality-summary", "chain-detail"),
            )
            live_frame = await asyncio.wait_for(anext(stream), timeout=1.0)
            assert live_frame.startswith(
                f"id: {journal.epoch}:106\nevent: invalidate\n".encode()
            )
            assert b'"event_type":"quality.changed"' in live_frame

            heartbeat = await asyncio.wait_for(anext(stream), timeout=1.0)
            assert heartbeat.startswith(b"event: heartbeat\n")
            assert b"id:" not in heartbeat
            await stream.aclose()
            assert hub.subscriber_count == 0
            assert hub._tail_task is None
        finally:
            await hub.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("cursor_kind", "expected_reason"),
    [
        ("initial", "INITIAL_SYNC"),
        ("epoch", "EPOCH_CHANGED"),
        ("ahead", "CURSOR_AHEAD"),
        ("expired", "CURSOR_EXPIRED"),
    ],
)
def test_event_stream_resets_for_non_replayable_cursors(
    cursor_kind: str,
    expected_reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_journal(monkeypatch)

    async def exercise() -> None:
        journal = _MemoryJournal()
        journal.append()
        journal.append(snapshot_id="s2")
        if cursor_kind == "expired":
            del journal.events[1]
        cursor = {
            "initial": None,
            "epoch": ChangeCursor(uuid4(), 0),
            "ahead": ChangeCursor(journal.epoch, 5),
            "expired": ChangeCursor(journal.epoch, 0),
        }[cursor_kind]
        hub = ChangeEventHub(journal, poll_seconds=0.01)
        try:
            subscriber, position = await hub.subscribe()
            stream = _stream_events(hub, subscriber, position, cursor)
            assert await anext(stream) == b"retry: 3000\n\n"
            reset_frame = await anext(stream)
            assert b"event: reset\n" in reset_frame
            payload = json.loads(
                next(
                    line[6:]
                    for line in reset_frame.splitlines()
                    if line.startswith(b"data: ")
                )
            )
            assert payload["reason"] == expected_reason
            assert payload["revision"] == 2
            assert reset_frame.startswith(f"id: {journal.epoch}:2\n".encode())
            await stream.aclose()
        finally:
            await hub.close()

    asyncio.run(exercise())


def test_slow_subscriber_gets_bounded_overflow_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_journal(monkeypatch)

    async def exercise() -> None:
        journal = _MemoryJournal()
        hub = ChangeEventHub(journal, poll_seconds=0.005, queue_size=1)
        try:
            subscriber, position = await hub.subscribe()
            stream = _stream_events(hub, subscriber, position, None)
            assert await anext(stream) == b"retry: 3000\n\n"
            assert b"INITIAL_SYNC" in await anext(stream)
            journal.append()
            journal.append(snapshot_id="s2")
            for _ in range(100):
                if subscriber.overflowed:
                    break
                await asyncio.sleep(0.005)
            assert subscriber.overflowed is True
            reset = await asyncio.wait_for(anext(stream), timeout=1.0)
            payload = json.loads(
                next(line[6:] for line in reset.splitlines() if line.startswith(b"data: "))
            )
            assert payload["reason"] == "BUFFER_OVERFLOW"
            assert payload["revision"] == 2
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
            assert hub.subscriber_count == 0
        finally:
            await hub.close()

    asyncio.run(exercise())


def test_hub_caps_total_streams_per_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_journal(monkeypatch)

    async def exercise() -> None:
        journal = _MemoryJournal()
        hub = ChangeEventHub(journal, max_subscribers=1)
        try:
            subscriber, _ = await hub.subscribe()
            with pytest.raises(LiveUpdateCapacity):
                await hub.subscribe()
            assert hub.subscriber_count == 1
            await hub.unsubscribe(subscriber)
            assert hub.subscriber_count == 0
        finally:
            await hub.close()

    asyncio.run(exercise())


def test_stream_route_has_non_buffered_headers_and_releases_subscriber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_journal(monkeypatch)

    async def exercise() -> None:
        monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "true")
        journal = _MemoryJournal()
        hub = ChangeEventHub(journal, poll_seconds=0.01)
        app = create_app(workspace=Workspace())
        app.state.live_updates_hub = hub
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/v1/events",
                "raw_path": b"/api/v1/events",
                "query_string": b"",
                "headers": [],
                "server": ("testserver", 80),
                "client": ("testclient", 1),
                "app": app,
            }
        )
        try:
            response = await stream_change_events(request, last_event_id=None)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-cache, no-transform"
            assert response.headers["x-accel-buffering"] == "no"
            assert response.headers["vary"] == "Last-Event-ID"
            assert await anext(response.body_iterator) == b"retry: 3000\n\n"
            assert b"INITIAL_SYNC" in await anext(response.body_iterator)
            await response.body_iterator.aclose()
            assert response.background is not None
            await response.background()
            assert hub.subscriber_count == 0
        finally:
            app.state.workspace.close()
            await hub.close()

    asyncio.run(exercise())


def test_events_route_is_not_bound_to_the_short_lived_snapshot_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_journal(monkeypatch)

    async def exercise() -> None:
        monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "true")
        journal = _MemoryJournal()
        hub = ChangeEventHub(journal)
        app = create_app(workspace=Workspace())
        app.state.live_updates_hub = hub

        async def finite_stream(*_args, **_kwargs):
            yield b"retry: 3000\n\n"
            yield b"event: heartbeat\ndata: {}\n\n"

        monkeypatch.setattr(live_updates, "_stream_events", finite_stream)
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get(
                    "/api/v1/events",
                    headers={
                        "x-nocpro-snapshot-id": "stale-snapshot",
                        "x-nocpro-snapshot-version": "stale-version",
                        "x-nocpro-topology-version": "stale-topology",
                    },
                )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.text == "retry: 3000\n\nevent: heartbeat\ndata: {}\n\n"
            assert hub.subscriber_count == 0
        finally:
            app.state.workspace.close()
            await hub.close()

    asyncio.run(exercise())


def test_events_endpoint_rejects_bad_cursors_and_reports_disabled_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "false")
        app = create_app(workspace=Workspace())
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                malformed = await client.get(
                    "/api/v1/events", headers={"Last-Event-ID": "not-valid"}
                )
                unavailable = await client.get("/api/v1/events")
            assert malformed.status_code == 400
            assert malformed.json()["detail"]["code"] == "INVALID_EVENT_CURSOR"
            assert unavailable.status_code == 503
            assert unavailable.json()["detail"]["code"] == "LIVE_UPDATES_UNAVAILABLE"
            monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "true")
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                no_persistence = await client.get("/api/v1/events")
            assert no_persistence.status_code == 503
            assert no_persistence.json()["detail"]["code"] == "LIVE_UPDATES_UNAVAILABLE"
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_nginx_sse_proxy_settings_are_route_scoped() -> None:
    nginx_config = (
        Path(__file__).resolve().parents[1] / "services" / "web" / "nginx.conf"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"location\s*=\s*/api/v1/events\s*\{(?P<body>[^{}]*)\}",
        nginx_config,
        flags=re.DOTALL,
    )
    assert match is not None
    location = match.group("body")
    for directive in (
        "proxy_buffering off;",
        "proxy_cache off;",
        "proxy_read_timeout 45s;",
        "gzip off;",
        "proxy_set_header Last-Event-ID $http_last_event_id;",
    ):
        assert directive in location
    generic_api = re.search(r"location\s+/api/\s*\{(?P<body>[^{}]*)\}", nginx_config)
    assert generic_api is not None
    assert "proxy_buffering off;" not in generic_api.group("body")

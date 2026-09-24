from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nocpro_api.persistence.change_journal import (
    ChangeJournalUnavailable,
    append_change,
    journal_position,
    purge_expired_events,
    read_changes_after,
    rotate_journal_epoch,
)
from nocpro_api.persistence.models import (
    Base,
    ChangeEventClockModel,
    ChangeEventModel,
)
from nocpro_api.persistence.repository import SnapshotRepository


def test_change_journal_append_replay_rollback_retention_and_epoch_rotation() -> None:
    async def exercise() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        initial_epoch = uuid4()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions.begin() as session:
                session.add(
                    ChangeEventClockModel(
                        singleton_id=1, epoch=initial_epoch, revision=0
                    )
                )

            initial = await journal_position(sessions)
            assert (initial.epoch, initial.min_revision, initial.revision) == (
                initial_epoch,
                1,
                0,
            )

            class ExpectedRollback(Exception):
                pass

            with pytest.raises(ExpectedRollback):
                async with sessions.begin() as session:
                    await append_change(
                        session,
                        event_type="snapshot.changed",
                        snapshot_id="snapshot-rollback",
                        snapshot_version="1",
                        invalidates=["chain-list", "catalog", "catalog"],
                    )
                    raise ExpectedRollback

            after_rollback = await journal_position(sessions)
            assert after_rollback.revision == 0
            assert await read_changes_after(sessions, initial_epoch, 0) == []

            async with sessions.begin() as session:
                event = await append_change(
                    session,
                    event_type="snapshot.changed",
                    snapshot_id="snapshot-1",
                    snapshot_version="2",
                    invalidates=["chain-list", "catalog", "catalog"],
                )

            assert event.revision == 1
            assert event.invalidates == ("catalog", "chain-list")
            assert event.to_payload() == {
                "schema_version": "change-event-v1",
                "event_type": "snapshot.changed",
                "snapshot_id": "snapshot-1",
                "snapshot_version": "2",
                "chain_id": None,
                "topology_version": None,
                "identity_digest": None,
                "invalidates": ["catalog", "chain-list"],
            }
            assert [item.revision for item in await read_changes_after(
                sessions, initial_epoch, 0
            )] == [1]
            assert await read_changes_after(sessions, initial_epoch, 1) == []

            old_event = ChangeEventModel(
                epoch=initial_epoch,
                revision=2,
                event_type="quality.changed",
                snapshot_id="snapshot-old",
                snapshot_version="1",
                chain_id="C-old",
                topology_version=None,
                identity_digest=None,
                invalidates=["quality-summary"],
                created_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
            async with sessions.begin() as session:
                session.add(old_event)
            deleted = await purge_expired_events(
                sessions,
                retention=timedelta(hours=24),
                limit=1,
            )
            assert deleted == 1
            assert await read_changes_after(sessions, initial_epoch, 1) == []
            # Retention only prunes events; it does not rewind the writer clock.
            assert (await journal_position(sessions)).revision == 1

            rotated = await rotate_journal_epoch(sessions)
            assert rotated.epoch != initial_epoch
            assert (rotated.min_revision, rotated.revision) == (1, 0)
            assert [item.revision for item in await read_changes_after(
                sessions, initial_epoch, 0
            )] == [1]
            assert await read_changes_after(sessions, rotated.epoch, 0) == []
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_change_journal_rejects_invalid_event_contract_before_allocating_revision() -> None:
    async def exercise() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions.begin() as session:
                session.add(
                    ChangeEventClockModel(singleton_id=1, epoch=uuid4(), revision=0)
                )

            invalid_events = [
                {
                    "event_type": "quality.progress",
                    "invalidates": ["quality-summary"],
                },
                {
                    "event_type": "quality.changed",
                    "identity_digest": "not-a-digest",
                    "invalidates": ["quality-summary"],
                },
                {
                    "event_type": "quality.changed",
                    "invalidates": ["raw-payload"],
                },
            ]
            for values in invalid_events:
                with pytest.raises(ValueError):
                    async with sessions.begin() as session:
                        await append_change(session, **values)
            assert (await journal_position(sessions)).revision == 0

            async with sessions.begin() as session:
                await session.execute(delete(ChangeEventClockModel))
            with pytest.raises(ChangeJournalUnavailable):
                async with sessions.begin() as session:
                    await append_change(
                        session,
                        event_type="quality.changed",
                        invalidates=["quality-summary"],
                    )
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_change_journal_bounds_replay_and_cleanup_batches() -> None:
    async def exercise() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions.begin() as session:
                session.add(
                    ChangeEventClockModel(singleton_id=1, epoch=uuid4(), revision=0)
                )
            for values in (
                {"limit": 0},
                {"limit": 101},
                {"limit": True},
            ):
                with pytest.raises(ValueError):
                    await read_changes_after(sessions, uuid4(), 0, **values)
            for values in (
                {"limit": 0},
                {"limit": 1001},
                {"limit": True},
            ):
                with pytest.raises(ValueError):
                    await purge_expired_events(sessions, **values)
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_live_updates_are_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from nocpro_api.persistence.change_journal import live_updates_enabled

    monkeypatch.delenv("NOCPRO_LIVE_UPDATES_ENABLED", raising=False)
    assert live_updates_enabled() is False
    monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "true")
    assert live_updates_enabled() is True
    monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "1")
    assert live_updates_enabled() is True
    monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "enabled")
    assert live_updates_enabled() is False


def test_completed_direct_snapshot_emits_one_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_api import _payload

    monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "true")

    async def exercise() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        epoch = uuid4()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions.begin() as session:
                session.add(
                    ChangeEventClockModel(singleton_id=1, epoch=epoch, revision=0)
                )

            repository = SnapshotRepository(sessions)
            payload = _payload()
            result = await repository.ingest_direct(payload)
            assert result.completed_now is True
            position = await journal_position(sessions)
            assert position.revision == 1
            events = await read_changes_after(sessions, epoch, 0)
            assert len(events) == 1
            assert events[0].event_type == "snapshot.changed"
            assert events[0].snapshot_id == payload["snapshot"]["snapshot_id"]
            assert events[0].snapshot_version == payload["snapshot"]["snapshot_version"]
            assert events[0].invalidates == (
                "catalog",
                "chain-list",
                "evolution",
                "quality-summary",
            )

            duplicate = await repository.ingest_direct(payload)
            assert duplicate.duplicate is True
            assert (await journal_position(sessions)).revision == 1
        finally:
            await engine.dispose()

    asyncio.run(exercise())

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nocpro_api.persistence.change_journal import (
    append_change,
    journal_position,
    read_changes_after,
)
from nocpro_api.persistence.models import (
    Base,
    ChainQualityAssessmentRecord,
    ChangeEventClockModel,
    ChangeEventModel,
)
from nocpro_api.persistence.repository import SnapshotRepository


pytestmark = pytest.mark.postgres
_TEST_DATABASE_ENV = "NOCPRO_CHANGE_JOURNAL_TEST_DATABASE_URL"


def _safe_test_database_url() -> str:
    value = os.environ.get(_TEST_DATABASE_ENV)
    if not value:
        pytest.skip(f"{_TEST_DATABASE_ENV} is not configured")
    parsed = make_url(value)
    if (
        parsed.get_backend_name() != "postgresql"
        or parsed.host not in {"localhost", "127.0.0.1", "::1", "postgres"}
        or "test" not in (parsed.database or "").lower()
    ):
        pytest.fail(
            f"{_TEST_DATABASE_ENV} must target a local PostgreSQL database whose name contains 'test'"
        )
    parsed = parsed.set(drivername="postgresql+asyncpg")
    return parsed.render_as_string(hide_password=False)


async def _create_test_schema(database_url: str, *, include_quality: bool = False):
    engine = create_async_engine(database_url, pool_pre_ping=True)
    schema = f"test_change_journal_{uuid4().hex}"
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        scoped_engine = engine.execution_options(
            schema_translate_map={None: schema}
        )
        tables = [
            ChangeEventClockModel.__table__,
            ChangeEventModel.__table__,
        ]
        if include_quality:
            tables.append(ChainQualityAssessmentRecord.__table__)
        async with scoped_engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection, tables=tables
                )
            )
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)
        async with sessions.begin() as session:
            session.add(
                ChangeEventClockModel(singleton_id=1, epoch=uuid4(), revision=0)
            )
        return engine, scoped_engine, sessions, schema
    except BaseException:
        if created:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()
        raise


async def _drop_test_schema(engine, schema: str) -> None:
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()


def test_postgres_clock_lock_orders_revisions_by_commit_and_rolls_back_cleanly() -> None:
    database_url = _safe_test_database_url()

    async def exercise() -> None:
        engine, _, sessions, schema = await _create_test_schema(database_url)
        first_has_lock = asyncio.Event()
        allow_first_commit = asyncio.Event()
        second_started = asyncio.Event()
        second_finished = asyncio.Event()
        tasks: list[asyncio.Task] = []
        try:
            async def first_writer():
                async with sessions.begin() as session:
                    event = await append_change(
                        session,
                        event_type="snapshot.changed",
                        snapshot_id="snapshot-first",
                        snapshot_version="1",
                        invalidates=["catalog"],
                    )
                    first_has_lock.set()
                    await allow_first_commit.wait()
                return event

            async def second_writer():
                await first_has_lock.wait()
                second_started.set()
                async with sessions.begin() as session:
                    event = await append_change(
                        session,
                        event_type="snapshot.changed",
                        snapshot_id="snapshot-second",
                        snapshot_version="1",
                        invalidates=["catalog"],
                    )
                    second_finished.set()
                return event

            first_task = asyncio.create_task(first_writer())
            tasks.append(first_task)
            await asyncio.wait_for(first_has_lock.wait(), timeout=2)
            second_task = asyncio.create_task(second_writer())
            tasks.append(second_task)
            await asyncio.wait_for(second_started.wait(), timeout=2)
            await asyncio.sleep(0.1)
            assert not second_finished.is_set(), (
                "a later journal writer must wait for the preceding transaction's clock-row lock"
            )
            allow_first_commit.set()
            first_event, second_event = await asyncio.wait_for(
                asyncio.gather(first_task, second_task), timeout=5
            )
            assert (first_event.revision, second_event.revision) == (1, 2)
            assert [item.revision for item in await read_changes_after(
                sessions, first_event.epoch, 0
            )] == [1, 2]

            class ExpectedRollback(Exception):
                pass

            with pytest.raises(ExpectedRollback):
                async with sessions.begin() as session:
                    await append_change(
                        session,
                        event_type="quality.changed",
                        snapshot_id="snapshot-rollback",
                        snapshot_version="1",
                        chain_id="C1",
                        invalidates=["quality-summary"],
                    )
                    raise ExpectedRollback
            position = await journal_position(sessions)
            assert position.revision == 2
            next_event = None
            async with sessions.begin() as session:
                next_event = await append_change(
                    session,
                    event_type="quality.changed",
                    snapshot_id="snapshot-after-rollback",
                    snapshot_version="1",
                    chain_id="C1",
                    invalidates=["quality-summary"],
                )
            assert next_event.revision == 3
            assert [item.revision for item in await read_changes_after(
                sessions, next_event.epoch, 2
            )] == [3]
        finally:
            allow_first_commit.set()
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=3)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            await _drop_test_schema(engine, schema)

    asyncio.run(exercise())


def test_postgres_quality_replay_does_not_publish_duplicate_terminal_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _safe_test_database_url()
    monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "true")

    async def exercise() -> None:
        engine, _, sessions, schema = await _create_test_schema(
            database_url, include_quality=True
        )
        repository = SnapshotRepository(sessions)
        try:
            identity = {
                "identity_version": "analysis-identity-v1",
                "snapshot_id": "journal-snapshot",
                "snapshot_version": "1",
                "chain_id": "C1",
                "topology_version": "topology-v1",
                "analysis_config_version": "analysis-v1",
                "review_config_version": "review-v1",
                "pipeline_version": "pipeline-v1",
                "input_fingerprint": "a" * 64,
            }
            payload = {
                "snapshot_id": "journal-snapshot",
                "snapshot_version": "1",
                "chain_id": "C1",
                "assessment_version": "DETERMINISTIC_QUALITY_V4",
                "input_fingerprint": "a" * 64,
                "assessment": {
                    "status": "EVALUATED",
                    "stars": 4,
                    "label": "Ổn",
                    "available_dimension_count": 2,
                    "readiness": "READY",
                },
                "overview_projection": {"analysis_identity": identity},
                "stage": "DETERMINISTIC_COMPLETE",
                "deep_dive_job_id": None,
                "counterfactual_job_id": None,
                "recommendation_status": "NO_CLEAR_ALTERNATIVE",
            }
            await repository.persist_chain_quality_assessment(payload)
            after_first = await journal_position(sessions)
            await repository.persist_chain_quality_assessment(payload)
            after_replay = await journal_position(sessions)
            assert after_first.revision == 1
            assert after_replay.revision == 1

            changed = {**payload, "assessment": {**payload["assessment"], "stars": 3, "label": "Cần xem"}}
            await repository.persist_chain_quality_assessment(changed)
            after_change = await journal_position(sessions)
            assert after_change.revision == 2
            events = await read_changes_after(sessions, after_change.epoch, 0)
            assert [event.event_type for event in events] == [
                "quality.changed",
                "quality.changed",
            ]
            assert [event.revision for event in events] == [1, 2]
            assert all(event.identity_digest == events[0].identity_digest for event in events)
        finally:
            await _drop_test_schema(engine, schema)

    asyncio.run(exercise())

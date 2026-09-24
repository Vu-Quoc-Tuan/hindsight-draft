"""Bounded persisted C4 reads and their PostgreSQL lookup DDL."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from nocpro_api.persistence.models import Membership
from nocpro_api.persistence.repository import SnapshotRepository


PARENT = ("s1", "v1", "c1")
CHILD = ("s2", "v2", "c2")


def _session_repo():
    sessions = MagicMock()
    session = sessions.return_value.__aenter__.return_value
    return SnapshotRepository(sessions), session


def test_direct_predecessors_cap_at_100_and_use_exact_child_key():
    async def exercise():
        repo, session = _session_repo()
        rows = []
        for i in range(101):
            edge = SimpleNamespace(
                parent_snapshot_id="s1", parent_snapshot_version="v1",
                parent_chain_id=f"c{i:03}", child_snapshot_id="s2",
                child_snapshot_version="v2", child_chain_id="c2",
                edge_type="MERGE", overlap_count=1,
            )
            rows.append((edge, datetime.now(timezone.utc), datetime.now(timezone.utc), "REAL", "REAL"))
        session.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
        choices, truncated = await repo.list_evolution_predecessors(child=CHILD)
        assert len(choices) == 100 and truncated
        statement = session.execute.await_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "LIMIT" in sql and "lineage_status" in sql
        assert statement.compile(dialect=postgresql.dialect()).params["child_chain_id_1"] == "c2"
        session.execute.return_value = SimpleNamespace(first=lambda: rows[0])
        selected = await repo.get_evolution_edge(child=CHILD, parent=PARENT)
        assert selected["parent_chain_id"] == "c000"
        exact = session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
        assert exact.params["parent_chain_id_1"] == "c1"
    asyncio.run(exercise())


def test_receipt_lookup_uses_jsonb_containment_and_101_row_cap():
    async def exercise():
        repo, session = _session_repo()
        rows = [SimpleNamespace(
            receipt_id=f"r{i}", identity_digest=f"d{i}", artifact_revision=f"a{i}",
            analysis_identity={"snapshot_id": "s2", "snapshot_version": "v2", "chain_id": "c2"},
            assessment={}, source_artifact_refs={}, created_at=datetime.now(timezone.utc),
        ) for i in range(101)]
        session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
        choices, truncated = await repo.list_evolution_endpoint_receipts(endpoint=CHILD)
        assert len(choices) == 100 and truncated
        compiled = session.scalars.await_args.args[0].compile(dialect=postgresql.dialect())
        assert "@>" in str(compiled) and "LIMIT" in str(compiled)
        assert {"snapshot_id": "s2", "snapshot_version": "v2", "chain_id": "c2"} in compiled.params.values()
    asyncio.run(exercise())


def test_membership_sql_counts_exact_with_100_id_response():
    async def exercise():
        repo, session = _session_repo()
        session.scalar = AsyncMock(side_effect=[105, 100, 100])
        session.scalars = AsyncMock(side_effect=[
            SimpleNamespace(all=lambda: [f"a{i:03}" for i in range(200, 301)]),
            SimpleNamespace(all=lambda: [f"a{i:03}" for i in range(100)]),
        ])
        result = await repo.evolution_membership_summary(parent=PARENT, child=CHILD)
        assert result == {
            "added_count": 105, "removed_count": 100, "retained_count": 100,
            "added_alarm_ids": [f"a{i:03}" for i in range(200, 300)],
            "removed_alarm_ids": [f"a{i:03}" for i in range(100)],
            "truncated": True,
        }
        assert session.scalar.await_count == 3
        assert session.scalars.await_count == 2
        for call in (*session.scalar.await_args_list, *session.scalars.await_args_list):
            compiled = call.args[0].compile(dialect=postgresql.dialect())
            sql = str(compiled)
            assert "snapshot_id" in sql and "snapshot_version" in sql and "chain_id" in sql
            assert "EXISTS" in sql
            assert "s1" in compiled.params.values() and "s2" in compiled.params.values()
            assert "v1" in compiled.params.values() and "v2" in compiled.params.values()
        for call in session.scalars.await_args_list:
            assert 101 in call.args[0].compile(dialect=postgresql.dialect()).params.values()
    asyncio.run(exercise())


def test_membership_set_queries_execute_against_sqlite():
    engine = create_engine("sqlite:///:memory:")
    try:
        Membership.__table__.create(engine)
        with Session(engine) as db:
            db.execute(insert(Membership), [
                {"snapshot_id": "s1", "snapshot_version": "v1", "chain_id": "c1", "alarm_id": f"a{i:03}"}
                for i in range(200)
            ] + [
                {"snapshot_id": "s2", "snapshot_version": "v2", "chain_id": "c2", "alarm_id": f"a{i:03}"}
                for i in range(100, 305)
            ] + [
                {"snapshot_id": "s1", "snapshot_version": "other", "chain_id": "c1", "alarm_id": "unrelated"},
            ])
            db.commit()
            sessions = MagicMock()
            session = sessions.return_value.__aenter__.return_value
            session.scalar = AsyncMock(side_effect=db.scalar)
            session.scalars = AsyncMock(side_effect=db.scalars)
            result = asyncio.run(SnapshotRepository(sessions).evolution_membership_summary(parent=PARENT, child=CHILD))
            assert result["added_count"] == 105
            assert result["removed_count"] == 100
            assert result["retained_count"] == 100
            assert result["added_alarm_ids"] == [f"a{i:03}" for i in range(200, 300)]
            assert result["removed_alarm_ids"] == [f"a{i:03}" for i in range(100)]
            assert result["truncated"] is True
    finally:
        engine.dispose()


def test_0023_offline_ddl_has_both_indexes_and_correct_head():
    from alembic.script import ScriptDirectory

    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    assert ScriptDirectory.from_config(config).get_heads() == ["0023"]
    command.upgrade(config, "0022:0023", sql=True)
    ddl = output.getvalue().lower()
    assert "ix_lineage_edge_child_key" in ddl
    assert "ix_quality_receipts_analysis_identity_gin" in ddl
    assert "using gin (analysis_identity jsonb_path_ops)" in ddl

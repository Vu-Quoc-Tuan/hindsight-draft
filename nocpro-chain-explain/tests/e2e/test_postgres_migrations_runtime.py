"""Runtime PostgreSQL proof for snapshot-version and Audit artifact migrations."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import asyncpg
import pytest


if os.environ.get("NOCPRO_RUN_DOCKER_E2E") != "1":
    pytest.skip(
        "set NOCPRO_RUN_DOCKER_E2E=1 to run PostgreSQL migration acceptance",
        allow_module_level=True,
    )


pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get(
    "NOCPRO_E2E_DATABASE_URL",
    "postgresql://nocpro:nocpro@127.0.0.1:55432/nocpro",
)


def _database_url(database: str) -> str:
    return DATABASE_URL.rsplit("/", 1)[0] + f"/{database}"


def _alembic_url(database: str) -> str:
    return _database_url(database).replace("postgresql://", "postgresql+asyncpg://", 1)


def _migrate(database: str, revision: str, *, check: bool = True) -> subprocess.CompletedProcess:
    environment = {**os.environ, "DATABASE_URL": _alembic_url(database)}
    return subprocess.run(
        [".venv/bin/alembic", "upgrade", revision],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=check,
    )


async def _create_database(name: str) -> None:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


async def _drop_database(name: str) -> None:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            name,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        await connection.close()


async def _insert_snapshot(connection, snapshot_id: str, version: str) -> None:
    await connection.execute(
        """
        INSERT INTO snapshots (
          snapshot_id, snapshot_version, snapshot_time, status, source,
          source_kind, produced_at, raw_payload, payload_checksum
        ) VALUES ($1, $2, '2026-09-02T10:00:00Z', 'COMPLETE', 'migration-test',
                  'SYNTHETIC_TEST', '2026-09-02T10:00:00Z', '{}'::jsonb, 'checksum')
        """,
        snapshot_id,
        version,
    )


async def _insert_legacy_lineage(connection, snapshot_id: str) -> None:
    await connection.execute(
        """
        INSERT INTO lineage_component (
          component_id, canonical_component_id, first_snapshot_time,
          last_snapshot_time, status
        ) VALUES ('lc-migration', 'lc-migration', now(), now(), 'ACTIVE')
        """
    )
    await connection.execute(
        """
        INSERT INTO lineage_node (
          snapshot_id, snapshot_chain_id, snapshot_time, component_id, branch_id
        ) VALUES ($1, 'C1', now(), 'lc-migration', 'lc-migration:b0')
        """,
        snapshot_id,
    )


def test_0005_and_0006_migrate_real_postgres_and_preserve_tuple_identity() -> None:
    async def exercise() -> None:
        database = f"nocpro_migration_ok_{uuid4().hex[:12]}"
        await _create_database(database)
        try:
            _migrate(database, "0004")
            connection = await asyncpg.connect(_database_url(database))
            try:
                await _insert_snapshot(connection, "S1", "v1")
                await _insert_legacy_lineage(connection, "S1")
            finally:
                await connection.close()

            _migrate(database, "head")
            connection = await asyncpg.connect(_database_url(database))
            try:
                assert await connection.fetchval(
                    "SELECT snapshot_version FROM lineage_node "
                    "WHERE snapshot_id = 'S1' AND snapshot_chain_id = 'C1'"
                ) == "v1"
                await _insert_snapshot(connection, "S1", "v2")
                await connection.execute(
                    """
                    INSERT INTO lineage_node (
                      snapshot_id, snapshot_version, snapshot_chain_id,
                      snapshot_time, component_id, branch_id
                    ) VALUES ('S1', 'v2', 'C1', now(), 'lc-migration', 'lc-migration:b1')
                    """
                )
                assert await connection.fetchval(
                    "SELECT count(*) FROM lineage_node "
                    "WHERE snapshot_id = 'S1' AND snapshot_chain_id = 'C1'"
                ) == 2
                await connection.execute(
                    """
                    INSERT INTO similarity_model (
                      model_version, snapshot_id, snapshot_version,
                      trained_until_exclusive, model_payload
                    ) VALUES
                      ('sim-migration-v1', 'S1', 'v1', now(), '{}'::jsonb),
                      ('sim-migration-v2', 'S1', 'v2', now(), '{}'::jsonb)
                    """
                )
                await connection.execute(
                    """
                    INSERT INTO similarity_index_entry (
                      model_version, snapshot_id, snapshot_version,
                      snapshot_chain_id, event_time, fingerprint_payload
                    ) VALUES
                      ('sim-migration-v1', 'S1', 'v1', 'C1', now(), '{}'::jsonb),
                      ('sim-migration-v2', 'S1', 'v2', 'C1', now(), '{}'::jsonb)
                    """
                )
                assert await connection.fetchval(
                    "SELECT count(*) FROM similarity_index_entry "
                    "WHERE snapshot_id = 'S1' AND snapshot_chain_id = 'C1'"
                ) == 2
                tables = await connection.fetchval(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'audit_artifact'"
                )
                assert tables == 1
            finally:
                await connection.close()
        finally:
            await _drop_database(database)

    asyncio.run(exercise())


def test_0005_rejects_ambiguous_legacy_snapshot_identity() -> None:
    async def exercise() -> None:
        database = f"nocpro_migration_ambiguous_{uuid4().hex[:12]}"
        await _create_database(database)
        try:
            _migrate(database, "0004")
            connection = await asyncpg.connect(_database_url(database))
            try:
                await _insert_snapshot(connection, "S1", "v1")
                await _insert_snapshot(connection, "S1", "v2")
                await _insert_legacy_lineage(connection, "S1")
            finally:
                await connection.close()

            result = _migrate(database, "0005", check=False)
            assert result.returncode != 0
            assert "cannot backfill snapshot_version" in (result.stdout + result.stderr)
        finally:
            await _drop_database(database)

    asyncio.run(exercise())


def test_0010_keeps_legacy_delay_models_immutable_and_allows_v2() -> None:
    async def exercise() -> None:
        database = f"nocpro_migration_delay_v2_{uuid4().hex[:12]}"
        await _create_database(database)
        try:
            _migrate(database, "0009")
            connection = await asyncpg.connect(_database_url(database))
            try:
                await connection.execute(
                    """
                    INSERT INTO temporal_delay_model (
                      model_version, snapshot_id, snapshot_version,
                      training_cutoff, model_payload, taxonomy_payload
                    ) VALUES (
                      'delay-v1', 'S-delay', 'v1', now(),
                      '{"implementation_version":"TEMPORAL_DELAY_MODEL_V1"}'::jsonb,
                      '{}'::jsonb
                    )
                    """
                )
            finally:
                await connection.close()

            _migrate(database, "head")
            connection = await asyncpg.connect(_database_url(database))
            try:
                await connection.execute(
                    """
                    INSERT INTO temporal_delay_model (
                      model_version, snapshot_id, snapshot_version,
                      training_cutoff, model_payload, taxonomy_payload
                    ) VALUES (
                      'delay-v2', 'S-delay', 'v1', now(),
                      '{"implementation_version":"TEMPORAL_DELAY_MODEL_V2"}'::jsonb,
                      '{}'::jsonb
                    )
                    """
                )
                assert await connection.fetchval(
                    "SELECT count(*) FROM temporal_delay_model "
                    "WHERE snapshot_id = 'S-delay' AND snapshot_version = 'v1'"
                ) == 2
            finally:
                await connection.close()
        finally:
            await _drop_database(database)

    asyncio.run(exercise())

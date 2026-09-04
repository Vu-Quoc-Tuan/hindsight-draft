from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from aiokafka import AIOKafkaProducer
import asyncpg
import pytest

if os.environ.get("NOCPRO_RUN_DOCKER_E2E") != "1":
    pytest.skip(
        "set NOCPRO_RUN_DOCKER_E2E=1 to run Docker acceptance failures",
        allow_module_level=True,
    )

pytest.importorskip("nocpro_mock")

from nocpro_mock.producer.kafka_snapshot import (
    KafkaSnapshotConfig,
    build_snapshot_wire_batch,
    encode_event,
    publish_snapshot,
)
from nocpro_mock.scenarios.snapshot_builder import build_synthetic_snapshot


pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
PROJECT = os.environ.get("NOCPRO_E2E_COMPOSE_PROJECT", "nocpro-acceptance")
KAFKA_BOOTSTRAP = os.environ.get("NOCPRO_E2E_KAFKA", "127.0.0.1:29092")
DATABASE_URL = os.environ.get(
    "NOCPRO_E2E_DATABASE_URL",
    "postgresql://nocpro:nocpro@127.0.0.1:55432/nocpro",
)


def compose(*args: str) -> None:
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, *args],
        cwd=ROOT,
        check=True,
    )


def package_for(case: str, minute_offset: int):
    scenario = f"SYNTH_E2E_{case}_{uuid4().hex[:10]}"
    package = build_synthetic_snapshot(
        scenario_id=scenario,
        seed=20260829,
        generator_version="docker-acceptance-v1",
        snapshot_index=0,
        chains={f"{scenario}_CHAIN": [f"{scenario}_A{i}" for i in range(1, 7)]},
    )
    # This suite is intentionally run before the real replay in the aggregate
    # harness.  Keep its recovery fixtures in a stable historical prefix so
    # the replay's default current timestamp cannot violate lineage ordering.
    logical_time = datetime.now(timezone.utc) - timedelta(hours=1) + timedelta(
        minutes=minute_offset
    )
    return replace(
        package,
        snapshot=replace(
            package.snapshot,
            snapshot_time=logical_time.isoformat(),
            produced_at=logical_time.isoformat(),
        ),
    )


async def send_events(batch, events) -> None:
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        enable_idempotence=True,
        max_request_size=8 * 1024 * 1024,
    )
    await producer.start()
    try:
        for event in events:
            await producer.send_and_wait(
                "nocpro.snapshot.v1",
                key=batch.key,
                value=encode_event(event),
            )
    finally:
        await producer.stop()


async def row_for(snapshot_id: str):
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        return await connection.fetchrow(
            """
            SELECT status, tier1a_status, lineage_status, similarity_status,
                   expected_chunk_count, received_chunk_count, attempt_count,
                   worker_id, lease_expires_at
              FROM snapshot_ingest
             WHERE snapshot_id = $1 AND snapshot_version = '1'
            """,
            snapshot_id,
        )
    finally:
        await connection.close()


async def wait_for(snapshot_id: str, predicate, *, timeout: float = 45.0):
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        last = await row_for(snapshot_id)
        if last is not None and predicate(last):
            return last
        await asyncio.sleep(0.25)
    raise AssertionError(f"snapshot {snapshot_id} did not reach expected state; last={last}")


def test_01_missing_chunk_never_triggers_analysis():
    async def exercise():
        package = package_for("MISSING", 10)
        batch = build_snapshot_wire_batch(
            package, config=KafkaSnapshotConfig(chunk_target_bytes=128)
        )
        assert len(batch.chunks) > 1
        await send_events(batch, (batch.chunks[0], batch.complete))
        row = await wait_for(
            package.snapshot.snapshot_id,
            lambda value: value["expected_chunk_count"] == len(batch.chunks),
        )
        await asyncio.sleep(1)
        row = await row_for(package.snapshot.snapshot_id)
        assert row["status"] == "RECEIVING"
        assert row["received_chunk_count"] == 1
        assert row["tier1a_status"] is None

    asyncio.run(exercise())


def test_02_consumer_restart_resumes_persisted_chunks():
    async def exercise():
        package = package_for("RESTART", 11)
        batch = build_snapshot_wire_batch(
            package, config=KafkaSnapshotConfig(chunk_target_bytes=128)
        )
        assert len(batch.chunks) > 1
        await send_events(batch, (batch.chunks[0],))
        await wait_for(
            package.snapshot.snapshot_id,
            lambda value: value["received_chunk_count"] == 1,
        )
        compose("stop", "api")
        await send_events(batch, (*batch.chunks[1:], batch.complete))
        compose("start", "api")
        row = await wait_for(
            package.snapshot.snapshot_id,
            lambda value: value["tier1a_status"] == "READY",
            timeout=60,
        )
        assert row["status"] == "COMPLETE"
        assert row["received_chunk_count"] == len(batch.chunks)

    asyncio.run(exercise())


def test_03_duplicate_snapshot_is_idempotent():
    async def exercise():
        package = package_for("DUPLICATE", 12)
        first = await publish_snapshot(
            package,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            config=KafkaSnapshotConfig(chunk_target_bytes=128),
        )
        await publish_snapshot(
            package,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            config=KafkaSnapshotConfig(chunk_target_bytes=128),
        )
        row = await wait_for(
            package.snapshot.snapshot_id,
            lambda value: value["similarity_status"] == "READY",
            timeout=60,
        )
        assert row["status"] == "COMPLETE"
        assert row["received_chunk_count"] == len(first.chunks)
        assert row["attempt_count"] == 1

    asyncio.run(exercise())


def test_04_expired_running_lease_is_reclaimed():
    async def exercise():
        package = package_for("STALE_LEASE", 13)
        await publish_snapshot(
            package,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            config=KafkaSnapshotConfig(chunk_target_bytes=128),
        )
        await wait_for(
            package.snapshot.snapshot_id,
            lambda value: value["tier1a_status"] == "READY",
            timeout=60,
        )
        compose("stop", "api")
        connection = await asyncpg.connect(DATABASE_URL)
        try:
            await connection.execute(
                """
                UPDATE snapshot_ingest
                   SET tier1a_status = 'RUNNING', worker_id = 'dead-worker',
                       lease_expires_at = now() - interval '1 second',
                       heartbeat_at = now() - interval '2 minutes'
                 WHERE snapshot_id = $1 AND snapshot_version = '1'
                """,
                package.snapshot.snapshot_id,
            )
        finally:
            await connection.close()
        compose("start", "api")
        row = await wait_for(
            package.snapshot.snapshot_id,
            lambda value: value["tier1a_status"] == "READY"
            and value["attempt_count"] == 2
            and value["similarity_status"] == "READY",
            timeout=60,
        )
        # Lease fields are shared by Tier-1A, lineage, and Similarity.  A
        # subsequent lineage claim may therefore legitimately own them after
        # Tier-1A is READY; the reclaimed stale owner must never survive.
        assert row["worker_id"] != "dead-worker"

    asyncio.run(exercise())

from __future__ import annotations

import json
import asyncio
import hashlib
import base64
from types import SimpleNamespace

import pytest

from nocpro_api.kafka_consumer import KafkaSnapshotConsumer
from nocpro_api.persistence import IngestResult


class FakeConsumer:
    def __init__(self) -> None:
        self.commits: list[dict] = []

    async def commit(self, offsets: dict) -> None:
        self.commits.append(offsets)


class FakeDlq:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_and_wait(self, topic: str, *, key: bytes, value: bytes) -> None:
        self.messages.append({"topic": topic, "key": key, "value": value})


class FakeRepository:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.invalidations: list[tuple[str, str, str]] = []

    async def record_kafka_event(self, *args, **kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def invalidate(self, snapshot_id: str, version: str, reason: str) -> None:
        self.invalidations.append((snapshot_id, version, reason))


class FakeCoordinator:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def run(self, snapshot_id: str, version: str):
        self.calls.append((snapshot_id, version))
        if self.error:
            raise self.error
        return object()


def _message(value: dict | bytes, *, offset: int = 7):
    encoded = value if isinstance(value, bytes) else json.dumps(value).encode()
    return SimpleNamespace(
        topic="nocpro.snapshot.v1",
        partition=1,
        offset=offset,
        key=b"s1",
        value=encoded,
    )


def _chunk() -> dict:
    return {
        "schema_version": "v1",
        "event_type": "SNAPSHOT_CHUNK",
        "snapshot_id": "s1",
        "snapshot_version": "1",
        "chunk_index": 0,
        "chunk_count": 1,
        "payload_format": "json",
        "compression": "zstd",
        "chunk_checksum": hashlib.sha256(b"x").hexdigest(),
        "snapshot_checksum": "1" * 64,
        "payload": base64.b64encode(b"x").decode(),
    }


def _service(repository, coordinator=None) -> KafkaSnapshotConsumer:
    service = object.__new__(KafkaSnapshotConsumer)
    service.repository = repository
    service.coordinator = coordinator or FakeCoordinator()
    service.consumer = FakeConsumer()
    service.dlq = FakeDlq()
    service.config = SimpleNamespace(
        dlq_topic="nocpro.snapshot.v1.dlq",
        max_chunks=1024,
        max_chunk_bytes=4 * 1024 * 1024,
        max_uncompressed_bytes=256 * 1024 * 1024,
    )
    return service


def test_permanent_wire_error_is_dlqed_then_committed():
    repository = FakeRepository(None)
    service = _service(repository)

    asyncio.run(service.process_message(_message(b"not-json")))

    assert len(service.dlq.messages) == 1
    assert len(service.consumer.commits) == 1


def test_transient_repository_error_is_not_invalidated_dlqed_or_committed():
    repository = FakeRepository(ConnectionError("postgres unavailable"))
    service = _service(repository)

    with pytest.raises(ConnectionError, match="postgres unavailable"):
        asyncio.run(service.process_message(_message(_chunk())))

    assert repository.invalidations == []
    assert service.dlq.messages == []
    assert service.consumer.commits == []


def test_complete_snapshot_commits_for_logical_ordered_recovery_worker():
    result = IngestResult("s1", "1", "COMPLETE", duplicate=True)
    coordinator = FakeCoordinator(ConnectionError("worker unavailable"))
    service = _service(FakeRepository(result), coordinator)

    asyncio.run(service.process_message(_message(_chunk())))

    assert coordinator.calls == []
    assert len(service.consumer.commits) == 1

"""Unit tests for KafkaTopologyConsumer logic and DLQ forwarding."""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nocpro_api.kafka_topology_consumer import KafkaTopologyConsumer
from nocpro_api.ingest.topology_wire import TopologyWireEventError, parse_topology_wire_event


class FakeConsumer:
    def __init__(self) -> None:
        self.commits: list[dict] = []

    async def commit(self, offsets: dict) -> None:
        self.commits.append(offsets)


class FakeDlq:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_and_wait(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        self.messages.append({"topic": topic, "key": key, "value": value})


def _message(key: bytes | None, value: dict | bytes, *, offset: int = 10):
    encoded = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
    return SimpleNamespace(
        topic="nocpro.topology.v1",
        partition=0,
        offset=offset,
        key=key,
        value=encoded,
    )


def _service(repo=None, coordinator=None) -> tuple[KafkaTopologyConsumer, FakeConsumer, FakeDlq]:
    consumer = FakeConsumer()
    dlq = FakeDlq()
    service = object.__new__(KafkaTopologyConsumer)
    service.repository = repo or MagicMock()
    service.coordinator = coordinator
    service.consumer = consumer
    service.dlq = dlq
    service.config = SimpleNamespace(
        topic="nocpro.topology.v1",
        dlq_topic="nocpro.topology.v1.dlq",
        retry_backoff_seconds=0.01,
    )
    return service, consumer, dlq


def test_malformed_json_routes_to_dlq():
    repo = MagicMock()
    service, consumer, dlq = _service(repo)

    msg = _message(b"IT_SERVICES", b"invalid json content")
    asyncio.run(service.process_message(msg))

    assert len(dlq.messages) == 1
    assert dlq.messages[0]["topic"] == "nocpro.topology.v1.dlq"
    assert len(consumer.commits) == 1


def test_key_mismatch_routes_to_dlq():
    repo = MagicMock()
    service, consumer, dlq = _service(repo)

    payload = {
        "schema_version": "v1",
        "event_type": "TOPOLOGY_CHUNK",
        "profile_id": "IT_SERVICES",
        "topology_version": "it-v1",
        "chunk_index": 0,
        "chunk_count": 1,
        "chunk_checksum": "a" * 64,
        "payload_checksum": "b" * 64,
        "payload": base64.b64encode(b"test").decode("ascii"),
    }
    msg = _message(b"MISMATCH_KEY", payload)
    asyncio.run(service.process_message(msg))

    assert len(dlq.messages) == 1
    assert len(consumer.commits) == 1


def test_chunk_event_processes_atomically():
    import hashlib
    raw_chunk = b"compressed-chunk-data"
    chunk_cksum = hashlib.sha256(raw_chunk).hexdigest()
    payload_cksum = "c" * 64

    repo = MagicMock()
    repo.process_kafka_event = AsyncMock(return_value=None)
    service, consumer, dlq = _service(repo)

    payload = {
        "schema_version": "v1",
        "event_type": "TOPOLOGY_CHUNK",
        "event_id": "chunk-1",
        "profile_id": "IT_SERVICES",
        "topology_version": "it-v1",
        "chunk_index": 0,
        "chunk_count": 1,
        "chunk_checksum": chunk_cksum,
        "payload_checksum": payload_cksum,
        "payload": base64.b64encode(raw_chunk).decode("ascii"),
    }
    msg = _message(b"IT_SERVICES", payload)
    asyncio.run(service.process_message(msg))

    repo.process_kafka_event.assert_awaited_once()
    assert len(consumer.commits) == 1
    assert len(dlq.messages) == 0


def test_complete_event_commits_and_wakes_coordinator():
    repo = MagicMock()
    repo.process_kafka_event = AsyncMock(return_value=("IT_SERVICES", "it-v1"))
    coordinator = MagicMock()
    coordinator.wake_pending_topology = AsyncMock()
    service, consumer, dlq = _service(repo, coordinator)

    payload = {
        "schema_version": "v1",
        "event_type": "TOPOLOGY_COMPLETE",
        "event_id": "comp-1",
        "profile_id": "IT_SERVICES",
        "topology_version": "it-v1",
        "source_version": "sha256:abc",
        "chunk_count": 1,
        "payload_checksum": "d" * 64,
        "node_count": 10,
        "edge_count": 5,
        "alias_count": 0,
        "relation_model": "DIRECTED_SOURCE_RELATIONS",
        "direction_kind": "SOURCE_RELATION",
        "dependency_semantics": "UNVERIFIED",
        "navigation_eligible": True,
        "p2_eligible": False,
    }
    msg = _message(b"IT_SERVICES", payload)
    asyncio.run(service.process_message(msg))

    repo.process_kafka_event.assert_awaited_once()
    coordinator.wake_pending_topology.assert_awaited_once_with("IT_SERVICES", "it-v1")
    assert len(consumer.commits) == 1
    assert len(dlq.messages) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("p2_eligible", "false"), ("navigation_eligible", "false")],
)
def test_topology_capability_flags_require_json_booleans(field, value):
    event = {
        "schema_version": "v1",
        "event_type": "TOPOLOGY_COMPLETE",
        "profile_id": "IT_SERVICES",
        "topology_version": "it-v1",
        "source_version": "sha256:source",
        "chunk_count": 1,
        "payload_checksum": "d" * 64,
        "node_count": 1,
        "edge_count": 0,
        "alias_count": 0,
        "relation_model": "DIRECTED_SOURCE_RELATIONS",
        "direction_kind": "SOURCE_RELATION",
        "dependency_semantics": "VERIFIED_DEPENDENCY",
        "navigation_eligible": True,
        "p2_eligible": False,
        field: value,
    }

    with pytest.raises(TopologyWireEventError, match=f"{field} must be a boolean"):
        parse_topology_wire_event(event)


def test_transient_db_error_raises_for_retry():
    import hashlib
    raw_chunk = b"compressed-chunk-data"
    chunk_cksum = hashlib.sha256(raw_chunk).hexdigest()

    repo = MagicMock()
    repo.process_kafka_event = AsyncMock(side_effect=ConnectionError("Database timeout"))
    service, consumer, dlq = _service(repo)

    payload = {
        "schema_version": "v1",
        "event_type": "TOPOLOGY_CHUNK",
        "profile_id": "IT_SERVICES",
        "topology_version": "it-v1",
        "chunk_index": 0,
        "chunk_count": 1,
        "chunk_checksum": chunk_cksum,
        "payload_checksum": "e" * 64,
        "payload": base64.b64encode(raw_chunk).decode("ascii"),
    }
    msg = _message(b"IT_SERVICES", payload)

    with pytest.raises(ConnectionError):
        asyncio.run(service.process_message(msg))

    # Crucial: Must NOT commit and must NOT send transient DB error to DLQ!
    assert len(consumer.commits) == 0
    assert len(dlq.messages) == 0

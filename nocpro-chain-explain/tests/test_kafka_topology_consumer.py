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
    def __init__(self, actions: list[str] | None = None) -> None:
        self.commits: list[dict] = []
        self.actions = actions

    async def commit(self, offsets: dict) -> None:
        self.commits.append(offsets)
        if self.actions is not None:
            self.actions.append("commit")


class FakeDlq:
    def __init__(self, actions: list[str] | None = None) -> None:
        self.messages: list[dict] = []
        self.actions = actions
        self.raise_on_send: Exception | None = None

    async def send_and_wait(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        if self.actions is not None:
            self.actions.append("dlq_attempt")
        if self.raise_on_send is not None:
            raise self.raise_on_send
        self.messages.append({"topic": topic, "key": key, "value": value})
        if self.actions is not None:
            self.actions.append("dlq_ack")


def _message(key: bytes | None, value: dict | bytes, *, offset: int = 10):
    encoded = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
    return SimpleNamespace(
        topic="nocpro.topology.v1",
        partition=0,
        offset=offset,
        key=key,
        value=encoded,
    )


def _service(
    repo=None,
    coordinator=None,
    *,
    actions: list[str] | None = None,
) -> tuple[KafkaTopologyConsumer, FakeConsumer, FakeDlq]:
    consumer = FakeConsumer(actions)
    dlq = FakeDlq(actions)
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


def _valid_chunk_payload() -> dict:
    import hashlib

    raw_chunk = b"compressed-chunk-data"
    return {
        "schema_version": "v1",
        "event_type": "TOPOLOGY_CHUNK",
        "event_id": "chunk-1",
        "profile_id": "IT_SERVICES",
        "topology_version": "it-v1",
        "chunk_index": 0,
        "chunk_count": 1,
        "chunk_checksum": hashlib.sha256(raw_chunk).hexdigest(),
        "payload_checksum": "b" * 64,
        "payload": base64.b64encode(raw_chunk).decode("ascii"),
    }


def test_invalid_utf8_key_routes_to_dlq_before_commit():
    actions: list[str] = []
    service, consumer, dlq = _service(actions=actions)

    asyncio.run(service.process_message(_message(b"\xff", b"{}")))

    assert len(dlq.messages) == 1
    diagnostic = json.loads(dlq.messages[0]["value"])
    assert diagnostic["error"] == "Invalid UTF-8 message key"
    assert diagnostic["raw_key"] == "\ufffd"
    assert diagnostic["raw_key_base64"] == "/w=="
    assert diagnostic["raw_key_truncated"] is False
    assert len(consumer.commits) == 1
    assert actions == ["dlq_attempt", "dlq_ack", "commit"]


def test_dlq_failure_does_not_commit_invalid_utf8_key():
    service, consumer, dlq = _service()
    dlq.raise_on_send = RuntimeError("DLQ unavailable")

    with pytest.raises(RuntimeError, match="DLQ unavailable"):
        asyncio.run(service.process_message(_message(b"\xff", b"{}")))

    assert dlq.messages == []
    assert consumer.commits == []


def test_invalid_utf8_key_diagnostic_is_bounded():
    service, _, dlq = _service()

    asyncio.run(service.process_message(_message(b"\xff" * 1024, b"{}")))

    diagnostic = json.loads(dlq.messages[0]["value"])
    assert len(diagnostic["raw_key"]) <= 256
    assert len(diagnostic["raw_key_base64"]) <= 4 * ((256 + 2) // 3)
    assert diagnostic["raw_key_truncated"] is True


def test_dlq_outage_can_retry_invalid_utf8_key_without_losing_offset():
    service, consumer, dlq = _service()
    message = _message(b"\xff", b"{}")
    dlq.raise_on_send = RuntimeError("DLQ unavailable")

    with pytest.raises(RuntimeError, match="DLQ unavailable"):
        asyncio.run(service.process_message(message))
    assert consumer.commits == []

    dlq.raise_on_send = None
    asyncio.run(service.process_message(message))

    assert len(dlq.messages) == 1
    assert len(consumer.commits) == 1


def test_partition_continues_after_poison_record_is_dead_lettered():
    repo = MagicMock()
    repo.process_kafka_event = AsyncMock(return_value=None)
    service, consumer, dlq = _service(repo)
    service._running = True
    poison = _message(b"\xff", b"{}", offset=10)
    valid = _message(b"IT_SERVICES", _valid_chunk_payload(), offset=11)

    asyncio.run(service._process_partition([poison, valid]))

    assert len(dlq.messages) == 1
    assert len(consumer.commits) == 2
    assert repo.process_kafka_event.await_count == 1


def test_partition_retries_transient_failure_before_committing():
    repo = MagicMock()
    repo.process_kafka_event = AsyncMock(
        side_effect=[ConnectionError("Database timeout"), None]
    )
    service, consumer, dlq = _service(repo)
    service._running = True
    message = _message(b"IT_SERVICES", _valid_chunk_payload())

    asyncio.run(service._process_partition([message]))

    assert repo.process_kafka_event.await_count == 2
    assert len(consumer.commits) == 1
    assert dlq.messages == []


def test_replayed_chunk_uses_repository_deduplication_result():
    repo = MagicMock()
    # The repository atomically returns None when this already-committed Kafka
    # offset is replayed after a database commit but before the offset commit.
    repo.process_kafka_event = AsyncMock(return_value=None)
    service, consumer, dlq = _service(repo)
    message = _message(b"IT_SERVICES", _valid_chunk_payload(), offset=10)

    asyncio.run(service.process_message(message))
    asyncio.run(service.process_message(message))

    assert repo.process_kafka_event.await_count == 2
    assert len(consumer.commits) == 2
    assert dlq.messages == []


def test_partition_propagates_cancellation_without_retrying_or_committing():
    service, consumer, dlq = _service()
    service._running = True
    service.process_message = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service._process_partition([_message(b"IT_SERVICES", {})]))

    assert consumer.commits == []
    assert dlq.messages == []


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

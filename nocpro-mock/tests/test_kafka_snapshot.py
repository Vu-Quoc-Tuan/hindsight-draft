from __future__ import annotations

import base64
import json

import zstandard

from nocpro_mock.contract import package_to_dict
from nocpro_mock.producer.kafka_snapshot import (
    SNAPSHOT_CHUNK,
    SNAPSHOT_COMPLETE,
    KafkaSnapshotConfig,
    build_snapshot_wire_batch,
    encode_event,
    sha256_hex,
)
from nocpro_mock.replay import build_golden_snapshot


def test_chunked_wire_round_trips_to_canonical_snapshot(config):
    package = build_golden_snapshot(
        config=config,
        snapshot_id="kafka-snapshot",
        snapshot_version="42",
    )
    batch = build_snapshot_wire_batch(
        package, config=KafkaSnapshotConfig(chunk_target_bytes=128)
    )

    assert len(batch.chunks) > 1
    assert {chunk["event_type"] for chunk in batch.chunks} == {SNAPSHOT_CHUNK}
    assert batch.complete["event_type"] == SNAPSHOT_COMPLETE
    assert batch.complete["snapshot_version"] == "42"
    assert all(batch.key == b"kafka-snapshot" for _ in batch.events)

    compressed = b"".join(
        base64.b64decode(chunk["payload"]) for chunk in batch.chunks
    )
    canonical = zstandard.ZstdDecompressor().decompress(compressed)
    assert sha256_hex(canonical) == batch.complete["snapshot_checksum"]
    assert json.loads(canonical) == package_to_dict(package)


def test_each_chunk_has_an_independent_checksum(config):
    package = build_golden_snapshot(config=config, snapshot_version="7")
    batch = build_snapshot_wire_batch(
        package, config=KafkaSnapshotConfig(chunk_target_bytes=96)
    )

    for index, chunk in enumerate(batch.chunks):
        payload = base64.b64decode(chunk["payload"])
        assert chunk["chunk_index"] == index
        assert chunk["chunk_count"] == len(batch.chunks)
        assert chunk["chunk_checksum"] == sha256_hex(payload)


def test_event_encoding_is_compact_json(config):
    package = build_golden_snapshot(config=config, snapshot_version="1")
    event = build_snapshot_wire_batch(package).complete
    encoded = encode_event(event)
    assert b"\n" not in encoded
    assert json.loads(encoded) == event

from __future__ import annotations

import base64
import hashlib

import pytest

from nocpro_api.ingest.wire import (
    SnapshotChunkEvent,
    SnapshotCompleteEvent,
    SnapshotEventError,
    parse_snapshot_event,
)


def _chunk(payload: bytes = b"compressed") -> dict:
    return {
        "schema_version": "v1",
        "event_type": "SNAPSHOT_CHUNK",
        "snapshot_id": "s1",
        "snapshot_version": "7",
        "chunk_index": 0,
        "chunk_count": 1,
        "payload_format": "json",
        "compression": "zstd",
        "chunk_checksum": hashlib.sha256(payload).hexdigest(),
        "snapshot_checksum": "a" * 64,
        "payload": base64.b64encode(payload).decode("ascii"),
    }


def test_chunk_parser_verifies_checksum_and_decodes_payload():
    event = parse_snapshot_event(_chunk())
    assert isinstance(event, SnapshotChunkEvent)
    assert event.payload == b"compressed"
    assert event.snapshot_version == "7"


def test_bad_chunk_checksum_is_rejected():
    raw = _chunk()
    raw["chunk_checksum"] = "0" * 64
    with pytest.raises(SnapshotEventError, match="checksum mismatch"):
        parse_snapshot_event(raw)


def test_chunk_index_must_fit_declared_count():
    raw = _chunk()
    raw["chunk_index"] = 1
    with pytest.raises(SnapshotEventError, match="inconsistent"):
        parse_snapshot_event(raw)


def test_complete_barrier_keeps_explicit_identity_and_counts():
    event = parse_snapshot_event(
        {
            "schema_version": "v1",
            "event_type": "SNAPSHOT_COMPLETE",
            "snapshot_id": "s1",
            "snapshot_version": "7",
            "expected_chunk_count": 3,
            "total_uncompressed_bytes": 42,
            "snapshot_checksum": "a" * 64,
            "produced_at": "2026-08-29T00:00:00Z",
            "source": "nocpro-mock",
            "source_kind": "REAL_EXPORT_REPLAY",
        }
    )
    assert isinstance(event, SnapshotCompleteEvent)
    assert event.expected_chunk_count == 3
    assert event.total_uncompressed_bytes == 42


def test_unknown_wire_schema_fails_closed():
    raw = _chunk()
    raw["schema_version"] = "v2"
    with pytest.raises(SnapshotEventError, match="unsupported"):
        parse_snapshot_event(raw)

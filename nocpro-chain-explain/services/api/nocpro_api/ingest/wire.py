"""Validation for the versioned Kafka snapshot envelope."""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from typing import Any, Literal


DEFAULT_MAX_CHUNKS = 1024
DEFAULT_MAX_CHUNK_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


class SnapshotEventError(ValueError):
    pass


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_text(event: dict[str, Any], field: str) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value:
        raise SnapshotEventError(f"{field} must be a non-empty string")
    return value


def _required_nonnegative_int(event: dict[str, Any], field: str) -> int:
    value = event.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SnapshotEventError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class SnapshotChunkEvent:
    event_type: Literal["SNAPSHOT_CHUNK"]
    snapshot_id: str
    snapshot_version: str
    chunk_index: int
    chunk_count: int
    chunk_checksum: str
    snapshot_checksum: str
    payload: bytes
    payload_format: Literal["json"] = "json"
    compression: Literal["zstd"] = "zstd"
    schema_version: Literal["v1"] = "v1"


@dataclass(frozen=True)
class SnapshotCompleteEvent:
    event_type: Literal["SNAPSHOT_COMPLETE"]
    snapshot_id: str
    snapshot_version: str
    expected_chunk_count: int
    total_uncompressed_bytes: int
    snapshot_checksum: str
    produced_at: str
    source: str
    source_kind: str
    schema_version: Literal["v1"] = "v1"


SnapshotWireEvent = SnapshotChunkEvent | SnapshotCompleteEvent


def parse_snapshot_event(
    event: dict[str, Any],
    *,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    max_chunk_bytes: int = DEFAULT_MAX_CHUNK_BYTES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> SnapshotWireEvent:
    if not isinstance(event, dict):
        raise SnapshotEventError("Kafka event must be a JSON object")
    if event.get("schema_version") != "v1":
        raise SnapshotEventError("unsupported Kafka envelope schema_version")

    event_type = event.get("event_type")
    common = {
        "snapshot_id": _required_text(event, "snapshot_id"),
        "snapshot_version": _required_text(event, "snapshot_version"),
    }
    if event_type == "SNAPSHOT_CHUNK":
        if event.get("payload_format") != "json":
            raise SnapshotEventError("payload_format must be json")
        if event.get("compression") != "zstd":
            raise SnapshotEventError("compression must be zstd")
        chunk_count = _required_nonnegative_int(event, "chunk_count")
        chunk_index = _required_nonnegative_int(event, "chunk_index")
        if chunk_count == 0 or chunk_index >= chunk_count:
            raise SnapshotEventError("chunk index/count are inconsistent")
        if chunk_count > max_chunks:
            raise SnapshotEventError(f"chunk_count exceeds configured limit {max_chunks}")
        encoded_payload = _required_text(event, "payload")
        if len(encoded_payload) > ((max_chunk_bytes + 2) // 3) * 4:
            raise SnapshotEventError(
                f"chunk payload exceeds configured limit {max_chunk_bytes} bytes"
            )
        try:
            payload = base64.b64decode(
                encoded_payload, validate=True
            )
        except (binascii.Error, ValueError) as exc:
            raise SnapshotEventError("payload is not valid base64") from exc
        checksum = _required_text(event, "chunk_checksum")
        if len(payload) > max_chunk_bytes:
            raise SnapshotEventError(
                f"chunk payload exceeds configured limit {max_chunk_bytes} bytes"
            )
        if sha256_hex(payload) != checksum:
            raise SnapshotEventError("chunk checksum mismatch")
        return SnapshotChunkEvent(
            event_type="SNAPSHOT_CHUNK",
            **common,
            chunk_index=chunk_index,
            chunk_count=chunk_count,
            chunk_checksum=checksum,
            snapshot_checksum=_required_text(event, "snapshot_checksum"),
            payload=payload,
        )
    if event_type == "SNAPSHOT_COMPLETE":
        expected = _required_nonnegative_int(event, "expected_chunk_count")
        if expected == 0:
            raise SnapshotEventError("expected_chunk_count must be positive")
        if expected > max_chunks:
            raise SnapshotEventError(
                f"expected_chunk_count exceeds configured limit {max_chunks}"
            )
        total = _required_nonnegative_int(event, "total_uncompressed_bytes")
        if total > max_uncompressed_bytes:
            raise SnapshotEventError(
                "total_uncompressed_bytes exceeds configured limit "
                f"{max_uncompressed_bytes}"
            )
        return SnapshotCompleteEvent(
            event_type="SNAPSHOT_COMPLETE",
            **common,
            expected_chunk_count=expected,
            total_uncompressed_bytes=total,
            snapshot_checksum=_required_text(event, "snapshot_checksum"),
            produced_at=_required_text(event, "produced_at"),
            source=_required_text(event, "source"),
            source_kind=_required_text(event, "source_kind"),
        )
    raise SnapshotEventError(f"unsupported event_type {event_type!r}")

"""Validation for the versioned Kafka snapshot envelope."""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from typing import Any, Literal


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


def parse_snapshot_event(event: dict[str, Any]) -> SnapshotWireEvent:
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
        try:
            payload = base64.b64decode(
                _required_text(event, "payload"), validate=True
            )
        except (binascii.Error, ValueError) as exc:
            raise SnapshotEventError("payload is not valid base64") from exc
        checksum = _required_text(event, "chunk_checksum")
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
        return SnapshotCompleteEvent(
            event_type="SNAPSHOT_COMPLETE",
            **common,
            expected_chunk_count=expected,
            total_uncompressed_bytes=_required_nonnegative_int(
                event, "total_uncompressed_bytes"
            ),
            snapshot_checksum=_required_text(event, "snapshot_checksum"),
            produced_at=_required_text(event, "produced_at"),
            source=_required_text(event, "source"),
            source_kind=_required_text(event, "source_kind"),
        )
    raise SnapshotEventError(f"unsupported event_type {event_type!r}")

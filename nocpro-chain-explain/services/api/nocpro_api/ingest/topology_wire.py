"""Canonical Input Contract v1 wire envelope validation for Kafka topology events (ADR-0002)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_MAX_CHUNKS = 1024
DEFAULT_MAX_CHUNK_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


class TopologyWireEventError(ValueError):
    """Raised when a Kafka topology message violates the canonical wire contract."""


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_text(event: dict[str, Any], field: str) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TopologyWireEventError(f"{field} must be a non-empty string")
    return value.strip()


def _required_nonnegative_int(event: dict[str, Any], field: str) -> int:
    value = event.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TopologyWireEventError(f"{field} must be a non-negative integer")
    return value


def _validate_checksum(checksum: str, context: str) -> str:
    if not isinstance(checksum, str) or not SHA256_PATTERN.match(checksum):
        raise TopologyWireEventError(f"{context} must be a valid 64-hex lowercase SHA-256 digest")
    return checksum


@dataclass(frozen=True)
class TopologyChunkEvent:
    event_type: Literal["TOPOLOGY_CHUNK"]
    event_id: str
    profile_id: str
    topology_version: str
    chunk_index: int
    chunk_count: int
    chunk_checksum: str
    payload_checksum: str
    payload: bytes
    schema_version: str = "v1"
    source: str = "nocpro-mock"
    source_kind: str = "SIMULATOR"
    produced_at: str | None = None
    payload_format: str = "json"
    compression: str = "zstd"


@dataclass(frozen=True)
class TopologyCompleteEvent:
    event_type: Literal["TOPOLOGY_COMPLETE"]
    event_id: str
    profile_id: str
    topology_version: str
    source_version: str
    chunk_count: int
    payload_checksum: str
    node_count: int
    edge_count: int
    alias_count: int
    relation_model: str
    direction_kind: str
    dependency_semantics: str
    navigation_eligible: bool
    p2_eligible: bool
    schema_version: str = "v1"
    source: str = "nocpro-mock"
    source_kind: str = "SIMULATOR"
    produced_at: str | None = None


TopologyWireEvent = TopologyChunkEvent | TopologyCompleteEvent


def parse_topology_wire_event(
    event: dict[str, Any],
    *,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    max_chunk_bytes: int = DEFAULT_MAX_CHUNK_BYTES,
) -> TopologyWireEvent:
    if not isinstance(event, dict):
        raise TopologyWireEventError("Topology event payload must be a JSON object")

    schema_version = _required_text(event, "schema_version")
    if schema_version != "v1":
        raise TopologyWireEventError(f"Unsupported schema_version {schema_version!r}; only 'v1' supported")

    event_type = _required_text(event, "event_type")
    event_id = _required_text(event, "event_id") if "event_id" in event else f"gen-{sha256_hex(str(event).encode())[:16]}"
    profile_id = _required_text(event, "profile_id")
    topology_version = _required_text(event, "topology_version")
    source = event.get("source", "nocpro-mock")
    source_kind = event.get("source_kind", "SIMULATOR")
    produced_at = event.get("produced_at")

    if event_type == "TOPOLOGY_CHUNK":
        chunk_index = _required_nonnegative_int(event, "chunk_index")
        chunk_count = _required_nonnegative_int(event, "chunk_count")
        if chunk_count <= 0 or chunk_count > max_chunks:
            raise TopologyWireEventError(f"chunk_count {chunk_count} must be between 1 and {max_chunks}")
        if chunk_index >= chunk_count:
            raise TopologyWireEventError(f"chunk_index {chunk_index} out of range for chunk_count {chunk_count}")

        chunk_checksum = _validate_checksum(event.get("chunk_checksum", ""), "chunk_checksum")
        payload_checksum = _validate_checksum(event.get("payload_checksum", ""), "payload_checksum")

        raw_payload = event.get("payload")
        if isinstance(raw_payload, str):
            try:
                payload_bytes = base64.b64decode(raw_payload.encode("ascii"), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise TopologyWireEventError(f"Invalid base64 payload: {exc}") from exc
        elif isinstance(raw_payload, (bytes, bytearray)):
            payload_bytes = bytes(raw_payload)
        else:
            raise TopologyWireEventError("payload must be base64-encoded string or bytes")

        if len(payload_bytes) > max_chunk_bytes:
            raise TopologyWireEventError(
                f"Chunk byte size {len(payload_bytes)} exceeds maximum {max_chunk_bytes}"
            )

        actual_checksum = sha256_hex(payload_bytes)
        if actual_checksum != chunk_checksum:
            raise TopologyWireEventError(
                f"Chunk checksum mismatch: expected {chunk_checksum}, computed {actual_checksum}"
            )

        return TopologyChunkEvent(
            event_type="TOPOLOGY_CHUNK",
            event_id=event_id,
            profile_id=profile_id,
            topology_version=topology_version,
            chunk_index=chunk_index,
            chunk_count=chunk_count,
            chunk_checksum=chunk_checksum,
            payload_checksum=payload_checksum,
            payload=payload_bytes,
            schema_version=schema_version,
            source=source,
            source_kind=source_kind,
            produced_at=produced_at,
            payload_format=event.get("payload_format", "json"),
            compression=event.get("compression", "zstd"),
        )

    if event_type == "TOPOLOGY_COMPLETE":
        chunk_count = _required_nonnegative_int(event, "chunk_count")
        if chunk_count <= 0 or chunk_count > max_chunks:
            raise TopologyWireEventError(f"chunk_count {chunk_count} must be between 1 and {max_chunks}")

        payload_checksum = _validate_checksum(event.get("payload_checksum", ""), "payload_checksum")
        source_version = _required_text(event, "source_version")
        node_count = _required_nonnegative_int(event, "node_count")
        edge_count = _required_nonnegative_int(event, "edge_count")
        alias_count = _required_nonnegative_int(event, "alias_count")

        relation_model = _required_text(event, "relation_model")
        direction_kind = _required_text(event, "direction_kind")
        dependency_semantics = _required_text(event, "dependency_semantics")
        navigation_eligible = event.get("navigation_eligible", True)
        p2_eligible = event.get("p2_eligible", False)
        if not isinstance(navigation_eligible, bool):
            raise TopologyWireEventError("navigation_eligible must be a boolean")
        if not isinstance(p2_eligible, bool):
            raise TopologyWireEventError("p2_eligible must be a boolean")

        return TopologyCompleteEvent(
            event_type="TOPOLOGY_COMPLETE",
            event_id=event_id,
            profile_id=profile_id,
            topology_version=topology_version,
            source_version=source_version,
            chunk_count=chunk_count,
            payload_checksum=payload_checksum,
            node_count=node_count,
            edge_count=edge_count,
            alias_count=alias_count,
            relation_model=relation_model,
            direction_kind=direction_kind,
            dependency_semantics=dependency_semantics,
            navigation_eligible=navigation_eligible,
            p2_eligible=p2_eligible,
            schema_version=schema_version,
            source=source,
            source_kind=source_kind,
            produced_at=produced_at,
        )

    raise TopologyWireEventError(f"Unknown topology event_type: {event_type!r}")

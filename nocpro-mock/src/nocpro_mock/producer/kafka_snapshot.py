"""Chunked Kafka transport for canonical snapshot packages.

The canonical JSON is compressed once, then split.  Kafka is transport only:
the consumer reconstructs exactly the same bytes accepted by Direct Snapshot.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import zstandard
from aiokafka import AIOKafkaProducer

from ..contract import MockSnapshotPackage, package_to_json, validate_package


SNAPSHOT_TOPIC = "nocpro.snapshot.v1"
SNAPSHOT_CHUNK = "SNAPSHOT_CHUNK"
SNAPSHOT_COMPLETE = "SNAPSHOT_COMPLETE"


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class KafkaSnapshotConfig:
    topic: str = SNAPSHOT_TOPIC
    chunk_target_bytes: int = 2 * 1024 * 1024
    compression_level: int = 3

    def __post_init__(self) -> None:
        if self.chunk_target_bytes <= 0:
            raise ValueError("chunk_target_bytes must be positive")


@dataclass(frozen=True)
class SnapshotWireBatch:
    key: bytes
    chunks: tuple[dict[str, Any], ...]
    complete: dict[str, Any]
    canonical_bytes: bytes
    compressed_bytes: bytes

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return (*self.chunks, self.complete)


def encode_event(event: dict[str, Any]) -> bytes:
    return json.dumps(
        event, ensure_ascii=False, separators=(",", ":"), sort_keys=False
    ).encode("utf-8")


def build_snapshot_wire_batch(
    package: MockSnapshotPackage,
    *,
    config: KafkaSnapshotConfig = KafkaSnapshotConfig(),
) -> SnapshotWireBatch:
    """Validate, deterministically serialize, compress and chunk a snapshot."""
    validate_package(package).raise_if_failed()
    canonical = package_to_json(package, indent=None).encode("utf-8")
    compressed = zstandard.ZstdCompressor(level=config.compression_level).compress(
        canonical
    )
    snapshot_checksum = sha256_hex(canonical)
    parts = tuple(
        compressed[offset : offset + config.chunk_target_bytes]
        for offset in range(0, len(compressed), config.chunk_target_bytes)
    )
    if not parts:
        parts = (b"",)

    snapshot = package.snapshot
    chunks = tuple(
        {
            "schema_version": "v1",
            "event_type": SNAPSHOT_CHUNK,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_version": snapshot.snapshot_version,
            "chunk_index": index,
            "chunk_count": len(parts),
            "payload_format": "json",
            "compression": "zstd",
            "chunk_checksum": sha256_hex(part),
            "snapshot_checksum": snapshot_checksum,
            "payload": base64.b64encode(part).decode("ascii"),
        }
        for index, part in enumerate(parts)
    )
    complete = {
        "schema_version": "v1",
        "event_type": SNAPSHOT_COMPLETE,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "expected_chunk_count": len(parts),
        "total_uncompressed_bytes": len(canonical),
        "snapshot_checksum": snapshot_checksum,
        "produced_at": snapshot.produced_at,
        "source": "nocpro-mock",
        "source_kind": snapshot.source_kind.value,
    }
    return SnapshotWireBatch(
        key=snapshot.snapshot_id.encode("utf-8"),
        chunks=chunks,
        complete=complete,
        canonical_bytes=canonical,
        compressed_bytes=compressed,
    )


async def publish_snapshot(
    package: MockSnapshotPackage,
    *,
    bootstrap_servers: str,
    config: KafkaSnapshotConfig = KafkaSnapshotConfig(),
) -> SnapshotWireBatch:
    """Publish every chunk and the final barrier under one snapshot key."""
    batch = build_snapshot_wire_batch(package, config=config)
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        enable_idempotence=True,
        max_request_size=max(4 * 1024 * 1024, config.chunk_target_bytes * 2),
    )
    try:
        await producer.start()
        for event in batch.events:
            await producer.send_and_wait(
                config.topic,
                key=batch.key,
                value=encode_event(event),
            )
    finally:
        await producer.stop()
    return batch

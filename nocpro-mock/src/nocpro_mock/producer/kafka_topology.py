"""Chunked, compressed Kafka transport for versioned topology graphs.

Strictly preserves the methodology invariant:
- IT topology carries relation_model="SOURCE_RELATION", p2_eligible=False.
- IP topology carries relation_model="PHYSICAL_ADJACENCY", p2_eligible=False.
Navigation graphs are never promoted to operational P2 dependency evidence.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import zstandard
from aiokafka import AIOKafkaProducer

from ..contract import canonical_topology_version
from ..loaders.topology_ip_csv import TopoIPLoader
from ..loaders.topology_it_csv import ITTopologyLoader

LOGGER = logging.getLogger(__name__)

TOPOLOGY_TOPIC = "nocpro.topology.v1"
TOPOLOGY_CHUNK = "TOPOLOGY_CHUNK"
TOPOLOGY_COMPLETE = "TOPOLOGY_COMPLETE"


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class KafkaTopologyConfig:
    topic: str = TOPOLOGY_TOPIC
    chunk_target_bytes: int = 2 * 1024 * 1024  # 2MB
    compression_level: int = 3

    def __post_init__(self) -> None:
        if self.chunk_target_bytes <= 0:
            raise ValueError("chunk_target_bytes must be positive")


@dataclass(frozen=True)
class TopologyWireBatch:
    key: bytes
    profile_id: str
    topology_version: str
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


def _content_version(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def build_ip_topology_payload(topo_ip_csv: Path) -> dict[str, Any]:
    """Build IP network topology package from topoIP.csv with strict capability metadata."""
    if not topo_ip_csv.is_file():
        raise FileNotFoundError(f"topoIP.csv not found at: {topo_ip_csv}")

    relations = TopoIPLoader(topo_ip_csv).load()
    source_ver = _content_version(topo_ip_csv)
    topology_ver = canonical_topology_version("IP_NETWORK", source_ver)

    labels: dict[str, str] = {}
    edges: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for r in relations:
        if not r.device_code or not r.device_code_relation or r.device_code == r.device_code_relation:
            continue
        pair = tuple(sorted((r.device_code, r.device_code_relation)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        labels.setdefault(r.device_code, r.device_code)
        labels.setdefault(r.device_code_relation, r.device_code_relation)
        edges.append({
            "source_id": r.device_code,
            "target_id": r.device_code_relation,
            "relation_type": "ADJACENT_TO",
            "direction_kind": "NONE",
            "dependency_semantics": "UNAVAILABLE",
            "source_table": "topoIP.csv",
            "source_version": source_ver,
        })

    nodes = [
        {
            "resource_id": dev,
            "resource_type": "DEVICE",
            "display_name": label,
            "source_tables": ["topoIP.csv"],
            "attributes": {},
        }
        for dev, label in sorted(labels.items())
    ]

    return {
        "profile_id": "IP_NETWORK",
        "topology_version": topology_ver,
        "source_version": source_ver,
        "relation_model": "PHYSICAL_ADJACENCY",
        "direction_kind": "NONE",
        "dependency_semantics": "UNAVAILABLE",
        "navigation_eligible": True,
        "p2_eligible": False,  # Strict invariant: undirected hop distance only
        "nodes": nodes,
        "edges": edges,
        "alias_resolution": [],
    }


def build_it_topology_payload(topo_it_dir: Path) -> dict[str, Any]:
    """Build IT services topology package from topoIT/ archive with strict capability metadata."""
    if not topo_it_dir.is_dir():
        raise FileNotFoundError(f"topoIT directory not found at: {topo_it_dir}")

    loader = ITTopologyLoader(topo_it_dir)
    graph = loader.load_graph()
    aliases, ambiguous = loader.load_aliases()
    topology_ver = canonical_topology_version("IT_SERVICES", graph.source_version)

    nodes = [
        {
            "resource_id": node.resource_id,
            "resource_type": node.resource_type,
            "display_name": node.display_name,
            "source_tables": list(node.source_tables),
            "attributes": {},
        }
        for node in graph.nodes
    ]

    edges = [
        {
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "relation_type": edge.relation_type,
            "direction_kind": "SOURCE_RELATION",
            "dependency_semantics": "UNVERIFIED",
            "source_table": edge.source_table,
            "source_version": edge.source_version,
        }
        for edge in graph.edges
    ]

    alias_res: list[dict[str, Any]] = []
    # Unique aliases
    for key, target in sorted(aliases.items()):
        alias_res.append({
            "alias_key": key,
            "status": "UNIQUE",
            "unique_resource_id": target.resource_id,
            "verified_by": target.verified_by,
        })
    # Ambiguous aliases
    for key in sorted(ambiguous):
        alias_res.append({
            "alias_key": key,
            "status": "AMBIGUOUS",
            "unique_resource_id": None,
            "verified_by": "ambiguous_match",
        })

    return {
        "profile_id": "IT_SERVICES",
        "topology_version": topology_ver,
        "source_version": graph.source_version,
        "relation_model": "SOURCE_RELATION",
        "direction_kind": "SOURCE_RELATION",
        "dependency_semantics": "UNVERIFIED",
        "navigation_eligible": True,
        "p2_eligible": False,  # Strict invariant: source relation, never operational dependency
        "nodes": nodes,
        "edges": edges,
        "alias_resolution": alias_res,
    }


def build_topology_wire_batch(
    payload: dict[str, Any],
    *,
    config: KafkaTopologyConfig = KafkaTopologyConfig(),
) -> TopologyWireBatch:
    """Deterministically serialize, compress and chunk a topology package."""
    profile_id = payload["profile_id"]
    topology_version = payload["topology_version"]

    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    compressed = zstandard.ZstdCompressor(level=config.compression_level).compress(
        canonical
    )
    payload_checksum = sha256_hex(canonical)

    parts = tuple(
        compressed[offset : offset + config.chunk_target_bytes]
        for offset in range(0, len(compressed), config.chunk_target_bytes)
    )
    if not parts:
        parts = (b"",)

    now_iso = datetime.now(timezone.utc).isoformat()
    chunks = tuple(
        {
            "schema_version": "v1",
            "event_type": TOPOLOGY_CHUNK,
            "event_id": f"{profile_id}-{topology_version}-chunk-{index}",
            "profile_id": profile_id,
            "topology_version": topology_version,
            "chunk_index": index,
            "chunk_count": len(parts),
            "payload_format": "json",
            "compression": "zstd",
            "chunk_checksum": sha256_hex(part),
            "payload_checksum": payload_checksum,
            "payload": base64.b64encode(part).decode("ascii"),
            "source": "nocpro-mock",
            "source_kind": "SIMULATOR",
            "produced_at": now_iso,
        }
        for index, part in enumerate(parts)
    )

    complete = {
        "schema_version": "v1",
        "event_type": TOPOLOGY_COMPLETE,
        "event_id": f"{profile_id}-{topology_version}-complete",
        "profile_id": profile_id,
        "topology_version": topology_version,
        "source_version": payload["source_version"],
        "chunk_count": len(parts),
        "payload_checksum": payload_checksum,
        "node_count": len(payload.get("nodes", [])),
        "edge_count": len(payload.get("edges", [])),
        "alias_count": len(payload.get("alias_resolution", [])),
        "relation_model": payload["relation_model"],
        "direction_kind": payload["direction_kind"],
        "dependency_semantics": payload["dependency_semantics"],
        "navigation_eligible": payload["navigation_eligible"],
        "p2_eligible": payload["p2_eligible"],
        "source": "nocpro-mock",
        "source_kind": "SIMULATOR",
        "produced_at": now_iso,
    }

    return TopologyWireBatch(
        key=profile_id.encode("utf-8"),
        profile_id=profile_id,
        topology_version=topology_version,
        chunks=chunks,
        complete=complete,
        canonical_bytes=canonical,
        compressed_bytes=compressed,
    )


async def publish_topology_batch(
    producer: AIOKafkaProducer,
    batch: TopologyWireBatch,
    topic: str = TOPOLOGY_TOPIC,
) -> None:
    """Send all chunk events and complete barrier sequentially to ensure partition order."""
    for event in batch.events:
        await producer.send_and_wait(
            topic,
            key=batch.key,
            value=encode_event(event),
        )

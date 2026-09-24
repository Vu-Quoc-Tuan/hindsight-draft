"""Persistent repository for materialized topology navigation graphs and Kafka streaming."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import io
import json
import logging
import time
from typing import Any

import zstandard
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from contracts.v1.enums import MappingMethod, MappingStatus
from contracts.v1.models import AlarmEntityResolution
from ..entity_resolver import ModuleCandidate, extract_base_module_token

from ..ingest.topology_wire import (
    TopologyChunkEvent,
    TopologyCompleteEvent,
    TopologyWireEvent,
    sha256_hex,
)
from ..topology.engine import (
    NavigationRelationEdge,
    TopologyNodeItem,
    project_adjacency_tree,
    project_relation_tree,
)
from .models import (
    AlarmEntityResolutionRecord,
    TopologyActiveVersionRecord,
    TopologyAliasResolutionRecord,
    TopologyChunk,
    TopologyEdgeRecord,
    TopologyIngest,
    TopologyKafkaInbox,
    TopologyNodeRecord,
    TopologySubgraphCache,
    TopologyVersionRecord,
)

LOGGER = logging.getLogger(__name__)


def _insert_stmt(table, session):
    try:
        bind = session.get_bind()
        if bind is not None and getattr(bind.dialect, "name", None) == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            return sqlite_insert(table)
    except Exception:
        pass
    return pg_insert(table)

MAX_TOPOLOGY_UNCOMPRESSED_BYTES = 256 * 1024 * 1024  # 256MB safety decompression limit
MAX_QUERY_DEPTH = 10
MAX_QUERY_CHILDREN = 200
MAX_ANALYSIS_HYDRATION_HOPS = 3
MAX_HOST_MODULE_MAP_CACHE_ENTRIES = 2


def _canonical_relation_type(raw_type: str | None, profile: str) -> str:
    if raw_type in ("ADJACENT_TO", "IP_ADJACENCY"):
        return "IP_ADJACENCY"
    if isinstance(raw_type, str) and raw_type:
        return raw_type
    return "IP_ADJACENCY" if profile == "IP_NETWORK" else "UNKNOWN"


class TopologyRepository:
    """PostgreSQL storage and query engine for materialized topology graphs."""

    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions
        self._subgraph_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._host_modules_cache: OrderedDict[
            tuple[str, str],
            tuple[dict[str, list[ModuleCandidate]], dict[str, str]],
        ] = OrderedDict()
        self._host_modules_cache_lock = asyncio.Lock()

    async def record_inbox(
        self,
        topic: str,
        partition: int,
        offset: int,
        message_key: str | None,
    ) -> bool:
        """Record a Kafka message in deduplication inbox (legacy standalone path)."""
        async with self.sessions.begin() as session:
            # 1. Atomic deduplication inbox record
            inbox_stmt = (
                _insert_stmt(TopologyKafkaInbox, session)
                .values(
                    topic=topic,
                    partition=partition,
                    offset=offset,
                    message_key=message_key,
                )
                .on_conflict_do_nothing(index_elements=["topic", "partition", "offset"])
            )
            result = await session.execute(inbox_stmt)
            return bool(result.rowcount > 0)

    async def process_kafka_event(
        self,
        event: TopologyWireEvent,
        *,
        topic: str,
        partition: int,
        offset: int,
        message_key: str | None,
    ) -> tuple[str, str] | None:
        """Atomic deduplication and ingestion of a topology wire event in one transaction.

        Returns (profile_id, topology_version) if a version was finalized to READY, else None.
        """
        invalid_reason: str | None = None
        committed: tuple[str, str] | None = None
        async with self.sessions.begin() as session:
            # 1. Atomic Inbox Check
            seen = await session.scalar(
                select(TopologyKafkaInbox).where(
                    TopologyKafkaInbox.topic == topic,
                    TopologyKafkaInbox.partition == partition,
                    TopologyKafkaInbox.offset == offset,
                )
            )
            if seen is not None:
                LOGGER.debug("Duplicate topology message at %s/%s/%s; skipping", topic, partition, offset)
                version = await session.get(
                    TopologyVersionRecord,
                    (event.profile_id, event.topology_version),
                )
                if version is not None and version.status == "READY":
                    return event.profile_id, event.topology_version
                return None

            session.add(TopologyKafkaInbox(
                topic=topic,
                partition=partition,
                offset=offset,
                message_key=message_key,
            ))

            # 2. Dispatch to Chunk or Complete.  Expected payload corruption is
            # committed as INVALID state before it is surfaced to the consumer
            # for DLQ publication; raising inside the transaction would roll
            # back the very state that explains why this version was rejected.
            try:
                if isinstance(event, TopologyChunkEvent):
                    committed = await self._process_chunk_within_session(session, event)
                elif isinstance(event, TopologyCompleteEvent):
                    committed = await self._process_complete_within_session(session, event)
            except ValueError as exc:
                invalid_reason = str(exc)
                await self._mark_invalid(
                    session,
                    event.profile_id,
                    event.topology_version,
                    invalid_reason,
                )
                # A failed DLQ write must be retryable. Do not leave this
                # offset deduplicated until the consumer has published it.
                await session.execute(
                    delete(TopologyKafkaInbox).where(
                        TopologyKafkaInbox.topic == topic,
                        TopologyKafkaInbox.partition == partition,
                        TopologyKafkaInbox.offset == offset,
                    )
                )

        if invalid_reason is not None:
            raise ValueError(invalid_reason)
        return committed

    async def _process_chunk_within_session(
        self,
        session: Any,
        event: TopologyChunkEvent,
    ) -> tuple[str, str] | None:
        profile_id = event.profile_id
        topology_version = event.topology_version
        chunk_index = event.chunk_index
        chunk_count = event.chunk_count
        chunk_checksum = event.chunk_checksum
        payload_checksum = event.payload_checksum
        payload_bytes = event.payload

        # Detect chunk checksum collisions on the same index
        existing_chunk = await session.get(TopologyChunk, (profile_id, topology_version, chunk_index))
        if existing_chunk is not None and existing_chunk.chunk_checksum != chunk_checksum:
            reason = f"Chunk checksum conflict for {profile_id}:{topology_version}:{chunk_index}"
            LOGGER.error(reason)
            await self._mark_invalid(session, profile_id, topology_version, reason)
            raise ValueError(reason)

        # Upsert topology_ingest record
        ingest_stmt = (
            _insert_stmt(TopologyIngest, session)
            .values(
                profile_id=profile_id,
                topology_version=topology_version,
                status="RECEIVING",
                total_chunks=chunk_count,
                payload_checksum=payload_checksum,
            )
            .on_conflict_do_update(
                index_elements=["profile_id", "topology_version"],
                set_={"total_chunks": chunk_count, "payload_checksum": payload_checksum, "updated_at": func.now()},
            )
        )
        await session.execute(ingest_stmt)

        # Upsert chunk
        chunk_stmt = (
            _insert_stmt(TopologyChunk, session)
            .values(
                profile_id=profile_id,
                topology_version=topology_version,
                chunk_index=chunk_index,
                chunk_checksum=chunk_checksum,
                payload_compressed=payload_bytes,
            )
            .on_conflict_do_nothing(
                index_elements=["profile_id", "topology_version", "chunk_index"]
            )
        )
        await session.execute(chunk_stmt)

        # Recount received chunks
        count_stmt = (
            select(func.count())
            .select_from(TopologyChunk)
            .where(
                TopologyChunk.profile_id == profile_id,
                TopologyChunk.topology_version == topology_version,
            )
        )
        cnt = await session.scalar(count_stmt) or 0
        await session.execute(
            update(TopologyIngest)
            .where(
                TopologyIngest.profile_id == profile_id,
                TopologyIngest.topology_version == topology_version,
            )
            .values(received_chunks=cnt, updated_at=func.now())
        )

        # Dual-path finalization: check if COMPLETE barrier was already stored and all chunks are ready
        ver_row = await session.get(TopologyVersionRecord, (profile_id, topology_version))
        if ver_row is not None and ver_row.status == "RECEIVING" and cnt == chunk_count:
            LOGGER.info(
                "All %d chunks received after barrier for %s:%s; triggering finalization",
                chunk_count, profile_id, topology_version
            )
            return await self._finalize_materialization(session, profile_id, topology_version, ver_row)

        return None

    async def _process_complete_within_session(
        self,
        session: Any,
        event: TopologyCompleteEvent,
    ) -> tuple[str, str] | None:
        profile_id = event.profile_id
        topology_version = event.topology_version
        expected_chunk_count = event.chunk_count
        payload_checksum = event.payload_checksum

        # Check if version is already READY
        existing_ver = await session.get(TopologyVersionRecord, (profile_id, topology_version))
        if existing_ver is not None and existing_ver.status == "READY":
            LOGGER.info("Topology %s:%s already committed and READY; skipping", profile_id, topology_version)
            return profile_id, topology_version

        # Ensure/update ingest metadata
        ingest_stmt = (
            _insert_stmt(TopologyIngest, session)
            .values(
                profile_id=profile_id,
                topology_version=topology_version,
                status="RECEIVING",
                total_chunks=expected_chunk_count,
                payload_checksum=payload_checksum,
            )
            .on_conflict_do_update(
                index_elements=["profile_id", "topology_version"],
                set_={
                    "total_chunks": expected_chunk_count,
                    "payload_checksum": payload_checksum,
                    "updated_at": func.now(),
                },
            )
        )
        await session.execute(ingest_stmt)

        # Staging barrier record in TopologyVersionRecord
        produced_dt = datetime.fromisoformat(event.produced_at) if event.produced_at else datetime.now(timezone.utc)
        ver_stmt = (
            _insert_stmt(TopologyVersionRecord, session)
            .values(
                profile_id=profile_id,
                topology_version=topology_version,
                source_version=event.source_version,
                status="RECEIVING",
                relation_model=event.relation_model,
                direction_kind=event.direction_kind,
                dependency_semantics=event.dependency_semantics,
                navigation_eligible=event.navigation_eligible,
                p2_eligible=event.p2_eligible,
                node_count=event.node_count,
                edge_count=event.edge_count,
                alias_count=event.alias_count,
                payload_checksum=payload_checksum,
                produced_at=produced_dt,
            )
            .on_conflict_do_update(
                index_elements=["profile_id", "topology_version"],
                set_={
                    "source_version": event.source_version,
                    "relation_model": event.relation_model,
                    "direction_kind": event.direction_kind,
                    "dependency_semantics": event.dependency_semantics,
                    "navigation_eligible": event.navigation_eligible,
                    "p2_eligible": event.p2_eligible,
                    "node_count": event.node_count,
                    "edge_count": event.edge_count,
                    "alias_count": event.alias_count,
                    "payload_checksum": payload_checksum,
                },
            )
        )
        await session.execute(ver_stmt)

        # Check if all chunks are present
        chunks = (
            await session.scalars(
                select(TopologyChunk)
                .where(
                    TopologyChunk.profile_id == profile_id,
                    TopologyChunk.topology_version == topology_version,
                )
                .order_by(TopologyChunk.chunk_index)
            )
        ).all()

        if len(chunks) != expected_chunk_count or [c.chunk_index for c in chunks] != list(range(expected_chunk_count)):
            LOGGER.warning(
                "Incomplete chunks for %s:%s on COMPLETE: got %d, expected %d. Barrier preserved for later arrival.",
                profile_id, topology_version, len(chunks), expected_chunk_count
            )
            return None

        # Chunks are complete, finalize now
        ver_rec = await session.get(TopologyVersionRecord, (profile_id, topology_version))
        return await self._finalize_materialization(session, profile_id, topology_version, ver_rec)

    async def _finalize_materialization(
        self,
        session: Any,
        profile_id: str,
        topology_version: str,
        ver_meta: Any,
    ) -> tuple[str, str]:
        """Assemble chunks, decompress, validate barrier counts, and populate graph tables."""
        chunks = (
            await session.scalars(
                select(TopologyChunk)
                .where(
                    TopologyChunk.profile_id == profile_id,
                    TopologyChunk.topology_version == topology_version,
                )
                .order_by(TopologyChunk.chunk_index)
            )
        ).all()

        compressed = b"".join(c.payload_compressed for c in chunks)
        stream = io.BytesIO(compressed)
        decompressor = zstandard.ZstdDecompressor()
        try:
            with decompressor.stream_reader(stream) as reader:
                canonical = reader.read(MAX_TOPOLOGY_UNCOMPRESSED_BYTES + 1)
        except Exception as exc:
            reason = f"zstd decompression error: {exc}"
            await self._mark_invalid(session, profile_id, topology_version, reason)
            raise ValueError(reason) from exc

        if len(canonical) > MAX_TOPOLOGY_UNCOMPRESSED_BYTES:
            reason = f"Decompressed size {len(canonical)} exceeded safety limit ({MAX_TOPOLOGY_UNCOMPRESSED_BYTES})"
            await self._mark_invalid(session, profile_id, topology_version, reason)
            raise ValueError(reason)

        computed_checksum = sha256_hex(canonical)
        if computed_checksum != ver_meta.payload_checksum:
            reason = (
                f"Payload SHA-256 mismatch for {profile_id}:{topology_version}: "
                f"expected {ver_meta.payload_checksum}, computed {computed_checksum}"
            )
            await self._mark_invalid(session, profile_id, topology_version, reason)
            raise ValueError(reason)

        try:
            payload = json.loads(canonical.decode("utf-8"))
        except Exception as exc:
            reason = f"Canonical JSON decode error: {exc}"
            await self._mark_invalid(session, profile_id, topology_version, reason)
            raise ValueError(reason) from exc

        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        aliases = payload.get("alias_resolution", [])

        # Cross-validate barrier counts against payload contents
        if len(nodes) != ver_meta.node_count:
            reason = f"Node count mismatch: barrier declared {ver_meta.node_count}, found {len(nodes)}"
            await self._mark_invalid(session, profile_id, topology_version, reason)
            raise ValueError(reason)

        if len(edges) != ver_meta.edge_count:
            reason = f"Edge count mismatch: barrier declared {ver_meta.edge_count}, found {len(edges)}"
            await self._mark_invalid(session, profile_id, topology_version, reason)
            raise ValueError(reason)

        if len(aliases) != ver_meta.alias_count:
            reason = f"Alias count mismatch: barrier declared {ver_meta.alias_count}, found {len(aliases)}"
            await self._mark_invalid(session, profile_id, topology_version, reason)
            raise ValueError(reason)

        # Clean prior rows if re-materializing
        await session.execute(
            delete(TopologyNodeRecord).where(
                TopologyNodeRecord.profile_id == profile_id,
                TopologyNodeRecord.topology_version == topology_version,
            )
        )
        await session.execute(
            delete(TopologyEdgeRecord).where(
                TopologyEdgeRecord.profile_id == profile_id,
                TopologyEdgeRecord.topology_version == topology_version,
            )
        )
        await session.execute(
            delete(TopologyAliasResolutionRecord).where(
                TopologyAliasResolutionRecord.profile_id == profile_id,
                TopologyAliasResolutionRecord.topology_version == topology_version,
            )
        )

        # Bulk insert nodes
        if nodes:
            node_mappings = [
                {
                    "profile_id": profile_id,
                    "topology_version": topology_version,
                    "resource_id": n["resource_id"],
                    "resource_type": n.get("resource_type", "UNKNOWN"),
                    "display_name": n.get("display_name", n["resource_id"]),
                    "source_tables": n.get("source_tables"),
                    "attributes": n.get("attributes"),
                }
                for n in nodes
            ]
            await session.run_sync(
                lambda s: s.bulk_insert_mappings(TopologyNodeRecord, node_mappings)
            )

        # Bulk insert edges
        if edges:
            edge_mappings = [
                {
                    "profile_id": profile_id,
                    "topology_version": topology_version,
                    "source_id": e["source_id"],
                    "target_id": e["target_id"],
                    "relation_type": e["relation_type"],
                    "direction_kind": e.get("direction_kind"),
                    "dependency_semantics": e.get("dependency_semantics"),
                    "source_table": e.get("source_table"),
                    "source_version": e.get("source_version"),
                }
                for e in edges
            ]
            await session.run_sync(
                lambda s: s.bulk_insert_mappings(TopologyEdgeRecord, edge_mappings)
            )

        # Bulk insert aliases
        if aliases:
            alias_mappings = [
                {
                    "profile_id": profile_id,
                    "topology_version": topology_version,
                    "alias_key": a["alias_key"],
                    "status": a.get("status", "UNMAPPED"),
                    "unique_resource_id": a.get("unique_resource_id"),
                    "verified_by": a.get("verified_by"),
                }
                for a in aliases
            ]
            await session.run_sync(
                lambda s: s.bulk_insert_mappings(TopologyAliasResolutionRecord, alias_mappings)
            )

        # Mark TopologyVersionRecord READY
        await session.execute(
            update(TopologyVersionRecord)
            .where(
                TopologyVersionRecord.profile_id == profile_id,
                TopologyVersionRecord.topology_version == topology_version,
            )
            .values(status="READY", committed_at=func.now())
        )

        # Check monotonic ordering before switching active version pointer
        current_active = await session.get(TopologyActiveVersionRecord, profile_id)
        should_update_active = True
        if current_active is not None:
            current_ver_rec = await session.get(
                TopologyVersionRecord, (profile_id, current_active.topology_version)
            )
            if current_ver_rec is not None and ver_meta.produced_at < current_ver_rec.produced_at:
                should_update_active = False
                LOGGER.info(
                    "Topology %s:%s was produced earlier than active %s (%s < %s); not setting active pointer",
                    profile_id, topology_version, current_active.topology_version,
                    ver_meta.produced_at, current_ver_rec.produced_at
                )

        if should_update_active:
            active_stmt = (
                _insert_stmt(TopologyActiveVersionRecord, session)
                .values(
                    profile_id=profile_id,
                    topology_version=topology_version,
                    updated_at=func.now(),
                )
                .on_conflict_do_update(
                    index_elements=["profile_id"],
                    set_={
                        "topology_version": topology_version,
                        "updated_at": func.now(),
                    },
                )
            )
            await session.execute(active_stmt)

        # Mark ingest READY
        await session.execute(
            update(TopologyIngest)
            .where(
                TopologyIngest.profile_id == profile_id,
                TopologyIngest.topology_version == topology_version,
            )
            .values(
                status="READY",
                completed_at=func.now(),
                updated_at=func.now(),
            )
        )

        LOGGER.info(
            "Topology %s:%s successfully materialized: %d nodes, %d edges, %d aliases (active=%s)",
            profile_id, topology_version, len(nodes), len(edges), len(aliases), should_update_active
        )
        return profile_id, topology_version

    async def _mark_invalid(
        self,
        session: Any,
        profile_id: str,
        topology_version: str,
        reason: str,
    ) -> None:
        await session.execute(
            update(TopologyIngest)
            .where(
                TopologyIngest.profile_id == profile_id,
                TopologyIngest.topology_version == topology_version,
            )
            .values(status="INVALID", invalid_reason=reason, updated_at=func.now())
        )
        await session.execute(
            update(TopologyVersionRecord)
            .where(
                TopologyVersionRecord.profile_id == profile_id,
                TopologyVersionRecord.topology_version == topology_version,
            )
            .values(status="INVALID")
        )

    # Standalone backward-compatible helpers
    async def record_chunk(self, event: dict[str, Any]) -> bool:
        """Standalone chunk insert for testing."""
        from ..ingest.topology_wire import parse_topology_wire_event
        wire_ev = parse_topology_wire_event(event) if not isinstance(event, TopologyChunkEvent) else event
        async with self.sessions.begin() as session:
            await self._process_chunk_within_session(session, wire_ev)
            return True

    async def record_complete(self, event: dict[str, Any]) -> tuple[str, str] | None:
        """Standalone complete for testing."""
        from ..ingest.topology_wire import parse_topology_wire_event
        wire_ev = parse_topology_wire_event(event) if not isinstance(event, TopologyCompleteEvent) else event
        async with self.sessions.begin() as session:
            return await self._process_complete_within_session(session, wire_ev)

    async def get_active_version(self, profile_id: str) -> TopologyActiveVersionRecord | None:
        async with self.sessions() as session:
            return await session.get(TopologyActiveVersionRecord, profile_id)

    async def is_topology_ready(
        self, profile_id: str, topology_version: str | None = None
    ) -> bool:
        async with self.sessions() as session:
            target_version = topology_version
            if target_version is None:
                active = await session.get(TopologyActiveVersionRecord, profile_id)
                if not active:
                    return False
                target_version = active.topology_version
            version_rec = await session.get(
                TopologyVersionRecord, (profile_id, target_version)
            )
            return bool(version_rec and version_rec.status == "READY")

    async def list_profiles(self) -> list[str]:
        """List all available profiles that have an active READY version."""
        profiles = ["ALARM_ONLY"]
        async with self.sessions() as session:
            actives = (
                await session.scalars(select(TopologyActiveVersionRecord))
            ).all()
            for active in actives:
                if active.profile_id not in profiles:
                    profiles.append(active.profile_id)
        return sorted(profiles)

    async def search_nodes(
        self,
        profile_id: str,
        query: str,
        *,
        topology_version: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search nodes in the normalized navigation graph with prefix and token matching."""
        if profile_id == "ALARM_ONLY":
            return {
                "status": "UNAVAILABLE",
                "reason": "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE",
                "dataset_profile": profile_id,
                "results": [],
            }

        target_version = topology_version
        if target_version is None:
            active = await self.get_active_version(profile_id)
            if active is None:
                return {
                    "status": "UNAVAILABLE",
                    "reason": "TOPOLOGY_NOT_ACTIVE",
                    "dataset_profile": profile_id,
                    "results": [],
                }
            target_version = active.topology_version

        normalized = query.strip()
        if not normalized:
            return {
                "status": "AVAILABLE",
                "dataset_profile": profile_id,
                "results": [],
            }

        like_pattern = f"%{normalized}%"
        limit_val = min(max(1, limit), 100)
        async with self.sessions() as session:
            nodes = (
                await session.scalars(
                    select(TopologyNodeRecord)
                    .where(
                        TopologyNodeRecord.profile_id == profile_id,
                        TopologyNodeRecord.topology_version == target_version,
                        or_(
                            TopologyNodeRecord.display_name.ilike(like_pattern),
                            TopologyNodeRecord.resource_id.ilike(like_pattern),
                        ),
                    )
                    .order_by(
                        # Exact match first, then prefix match, then fallback
                        TopologyNodeRecord.display_name == normalized,
                        TopologyNodeRecord.display_name.ilike(f"{normalized}%"),
                    )
                    .limit(limit_val)
                )
            ).all()

            results = [
                {
                    "resource_id": n.resource_id,
                    "resource_type": n.resource_type,
                    "display_name": n.display_name,
                    "source_tables": n.source_tables,
                    "attributes": n.attributes,
                }
                for n in nodes
            ]
            return {
                "status": "AVAILABLE",
                "dataset_profile": profile_id,
                "results": results,
            }

    async def resolve_identifier(
        self,
        profile_id: str,
        identifier: str,
        *,
        topology_version: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a raw device code, host, or service name to a canonical resource_id."""
        if profile_id == "ALARM_ONLY":
            return {
                "status": "UNAVAILABLE",
                "dataset_profile": profile_id,
                "identifier": identifier,
                "resource_id": None,
                "mapping_status": "UNMAPPED",
                "navigation_eligible": False,
                "p2_mapping_eligible": False,
                "dependency_semantics": "UNAVAILABLE",
            }

        target_version = topology_version
        if target_version is None:
            active = await self.get_active_version(profile_id)
            if active is None:
                return {
                    "status": "UNAVAILABLE",
                    "reason": "TOPOLOGY_NOT_ACTIVE",
                    "dataset_profile": profile_id,
                    "identifier": identifier,
                    "resource_id": None,
                    "mapping_status": "UNMAPPED",
                    "navigation_eligible": False,
                    "p2_mapping_eligible": False,
                    "dependency_semantics": "UNAVAILABLE",
                }
            target_version = active.topology_version

        raw_id = identifier.strip()
        if not raw_id:
            return {
                "status": "AVAILABLE",
                "dataset_profile": profile_id,
                "identifier": identifier,
                "resource_id": None,
                "mapping_status": "UNMAPPED",
                "source_field": None,
                "navigation_eligible": False,
                "p2_mapping_eligible": False,
                "dependency_semantics": "UNAVAILABLE",
            }

        async with self.sessions() as session:
            # 1. Exact resource_id check
            exact_node = await session.get(
                TopologyNodeRecord, (profile_id, target_version, raw_id)
            )
            if exact_node is not None:
                return {
                    "status": "AVAILABLE",
                    "dataset_profile": profile_id,
                    "identifier": raw_id,
                    "resource_id": exact_node.resource_id,
                    "mapping_status": "EXACT_RESOURCE_ID",
                    "source_field": "canonical_resource_id",
                    "navigation_eligible": True,
                    "p2_mapping_eligible": False,
                    "dependency_semantics": "UNAVAILABLE" if profile_id == "IP_NETWORK" else "UNVERIFIED",
                }

            # 2. Case-insensitive exact display_name match
            match_node = await session.scalar(
                select(TopologyNodeRecord).where(
                    TopologyNodeRecord.profile_id == profile_id,
                    TopologyNodeRecord.topology_version == target_version,
                    TopologyNodeRecord.display_name.ilike(raw_id),
                )
            )
            if match_node is not None:
                return {
                    "status": "AVAILABLE",
                    "dataset_profile": profile_id,
                    "identifier": raw_id,
                    "resource_id": match_node.resource_id,
                    "mapping_status": "UNIQUE_SOURCE_FIELD_MATCH",
                    "source_field": "device_code" if profile_id == "IP_NETWORK" else "service_name",
                    "navigation_eligible": True,
                    "p2_mapping_eligible": False,
                    "dependency_semantics": "UNAVAILABLE" if profile_id == "IP_NETWORK" else "UNVERIFIED",
                }

            # 3. Verified alias resolution check (status UNIQUE or VERIFIED)
            alias_row = await session.get(
                TopologyAliasResolutionRecord, (profile_id, target_version, raw_id)
            )
            if alias_row is not None and alias_row.status in ("UNIQUE", "VERIFIED") and alias_row.unique_resource_id:
                return {
                    "status": "AVAILABLE",
                    "dataset_profile": profile_id,
                    "identifier": raw_id,
                    "resource_id": alias_row.unique_resource_id,
                    "mapping_status": "VERIFIED_ALIAS",
                    "source_field": "alias_table",
                    "navigation_eligible": True,
                    "p2_mapping_eligible": False,
                    "dependency_semantics": "UNAVAILABLE" if profile_id == "IP_NETWORK" else "UNVERIFIED",
                }

            return {
                "status": "AVAILABLE",
                "dataset_profile": profile_id,
                "identifier": raw_id,
                "resource_id": None,
                "mapping_status": "UNMAPPED",
                "source_field": None,
                "navigation_eligible": False,
                "p2_mapping_eligible": False,
                "dependency_semantics": "UNAVAILABLE",
            }

    async def get_projection(
        self,
        profile_id: str,
        *,
        root_id: str | None = None,
        max_depth: int = 3,
        max_children: int = 50,
        topology_version: str | None = None,
    ) -> dict[str, Any]:
        """Project the materialized graph into a BFS navigation tree."""
        if profile_id == "ALARM_ONLY":
            return {
                "status": "UNAVAILABLE",
                "reason": "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE",
                "profile": profile_id,
                "dataset_profile": profile_id,
                "topology_kind": "ALARM_ONLY",
                "topology": {
                    "availability": "UNAVAILABLE",
                    "reason": "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE",
                    "navigation_mapping": "UNAVAILABLE",
                    "alarm_resource_mapping": "UNAVAILABLE",
                },
                "semantic_notice": "Alarm-only profile has no physical or IT topology.",
            }

        safe_depth = min(max(1, max_depth), MAX_QUERY_DEPTH)
        safe_children = min(max(1, max_children), MAX_QUERY_CHILDREN)

        async with self.sessions() as session:
            target_version = topology_version
            if target_version is None:
                active = await session.get(TopologyActiveVersionRecord, profile_id)
                if active is None:
                    return {
                        "status": "UNAVAILABLE",
                        "reason": "TOPOLOGY_NOT_ACTIVE",
                        "profile": profile_id,
                        "dataset_profile": profile_id,
                        "topology_kind": (
                            "UNDIRECTED_ADJACENCY"
                            if profile_id == "IP_NETWORK"
                            else "DIRECTED_SOURCE_RELATIONS"
                        ),
                        "topology": {"availability": "UNAVAILABLE"},
                        "semantic_notice": "No active topology version found for this profile.",
                    }
                target_version = active.topology_version

            version_rec = await session.get(
                TopologyVersionRecord, (profile_id, target_version)
            )
            if version_rec is None:
                return {
                    "status": "UNAVAILABLE",
                    "reason": "VERSION_NOT_FOUND",
                    "profile": profile_id,
                    "dataset_profile": profile_id,
                    "topology_kind": "UNKNOWN",
                    "topology": {"availability": "UNAVAILABLE"},
                }

            resolved_root = root_id
            if not resolved_root:
                first_node = await session.scalar(
                    select(TopologyNodeRecord.resource_id)
                    .where(
                        TopologyNodeRecord.profile_id == profile_id,
                        TopologyNodeRecord.topology_version == target_version,
                    )
                    .limit(1)
                )
                resolved_root = first_node

            if resolved_root is None:
                return {
                    "status": "UNAVAILABLE",
                    "reason": "TOPOLOGY_EMPTY",
                    "profile": profile_id,
                    "dataset_profile": profile_id,
                    "topology_kind": (
                        "UNDIRECTED_ADJACENCY"
                        if profile_id == "IP_NETWORK"
                        else "DIRECTED_SOURCE_RELATIONS"
                    ),
                    "topology": {"availability": "UNAVAILABLE"},
                }

            # Collect reachable nodes and edges up to max_depth using BFS with safety bounds
            visited_node_ids = {resolved_root}
            current_frontier = {resolved_root}
            collected_edges: list[NavigationRelationEdge] = []
            seen_edge_ids: set[Any] = set()

            for _ in range(safe_depth):
                if not current_frontier or len(collected_edges) >= 2000:
                    break
                if profile_id == "IP_NETWORK":
                    stmt = (
                        select(TopologyEdgeRecord)
                        .where(
                            TopologyEdgeRecord.profile_id == profile_id,
                            TopologyEdgeRecord.topology_version == target_version,
                            or_(
                                TopologyEdgeRecord.source_id.in_(current_frontier),
                                TopologyEdgeRecord.target_id.in_(current_frontier),
                            ),
                        )
                        .limit(1000)
                    )
                else:
                    stmt = (
                        select(TopologyEdgeRecord)
                        .where(
                            TopologyEdgeRecord.profile_id == profile_id,
                            TopologyEdgeRecord.topology_version == target_version,
                            TopologyEdgeRecord.source_id.in_(current_frontier),
                        )
                        .limit(1000)
                    )
                edges = (await session.scalars(stmt)).all()
                next_frontier = set()
                for edge in edges:
                    if edge.id in seen_edge_ids:
                        continue
                    seen_edge_ids.add(edge.id)
                    collected_edges.append(
                        NavigationRelationEdge(
                            source_id=edge.source_id,
                            target_id=edge.target_id,
                            relation_type=edge.relation_type,
                            direction_kind=edge.direction_kind or "NONE",
                            dependency_semantics=edge.dependency_semantics or "UNVERIFIED",
                            source_table=edge.source_table,
                            source_version=edge.source_version,
                        )
                    )
                    if edge.source_id not in visited_node_ids:
                        next_frontier.add(edge.source_id)
                        visited_node_ids.add(edge.source_id)
                    if edge.target_id not in visited_node_ids:
                        next_frontier.add(edge.target_id)
                        visited_node_ids.add(edge.target_id)
                current_frontier = next_frontier

            node_records = (
                await session.scalars(
                    select(TopologyNodeRecord).where(
                        TopologyNodeRecord.profile_id == profile_id,
                        TopologyNodeRecord.topology_version == target_version,
                        TopologyNodeRecord.resource_id.in_(visited_node_ids),
                    )
                )
            ).all()
            nodes = [
                TopologyNodeItem(
                    resource_id=n.resource_id,
                    resource_type=n.resource_type,
                    display_name=n.display_name,
                )
                for n in node_records
            ]

            if profile_id == "IP_NETWORK":
                tree_proj = project_adjacency_tree(
                    nodes,
                    collected_edges,
                    root_id=resolved_root,
                    max_depth=safe_depth,
                    max_children=safe_children,
                )
            else:
                tree_proj = project_relation_tree(
                    nodes,
                    collected_edges,
                    root_id=resolved_root,
                    max_depth=safe_depth,
                    max_children=safe_children,
                )

            semantic_notice = (
                "Undirected physical adjacency only. Not an operational dependency relation."
                if profile_id == "IP_NETWORK"
                else "Directed IT service source relation. Dependency semantics unverified."
            )

            return {
                "status": "AVAILABLE",
                "profile": profile_id,
                "dataset_profile": profile_id,
                "topology_kind": (
                    "UNDIRECTED_ADJACENCY"
                    if profile_id == "IP_NETWORK"
                    else "DIRECTED_SOURCE_RELATIONS"
                ),
                "direction_kind": version_rec.direction_kind,
                "dependency_semantics": version_rec.dependency_semantics,
                "topology": {
                    "availability": "AVAILABLE",
                    "relation_model": version_rec.relation_model,
                    "direction_kind": version_rec.direction_kind,
                    "dependency_semantics": version_rec.dependency_semantics,
                    "navigation_mapping": "PARTIAL_SOURCE_FIELD_EXACT",
                    "alarm_resource_mapping": "UNAVAILABLE",
                },
                "semantic_notice": semantic_notice,
                "source_version": version_rec.source_version,
                "tree": tree_proj.root.to_dict(),
            }

    async def hydrate_graph_for_analysis(
        self,
        profile_id: str,
        topology_version: str,
        resource_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Hydrate topology dictionary from PostgreSQL for Analysis Worker."""
        async with self.sessions() as session:
            version_record = await session.get(
                TopologyVersionRecord,
                (profile_id, topology_version),
            )
            # Query edges
            stmt = select(TopologyEdgeRecord).where(
                TopologyEdgeRecord.profile_id == profile_id,
                TopologyEdgeRecord.topology_version == topology_version,
            )
            if resource_ids:
                # Analysis must receive complete paths between snapshot seeds, not
                # merely direct seed edges.  Treat IT source relations as
                # traversable in either direction here: alarms land on leaf
                # resources while evidence can originate at a service ancestor.
                all_edge_rows = (await session.scalars(stmt)).all()
                adjacency: dict[str, list[TopologyEdgeRecord]] = {}
                for edge in all_edge_rows:
                    adjacency.setdefault(edge.source_id, []).append(edge)
                    adjacency.setdefault(edge.target_id, []).append(edge)

                visited_node_ids = set(resource_ids)
                frontier = set(resource_ids)
                for _ in range(MAX_ANALYSIS_HYDRATION_HOPS):
                    if not frontier:
                        break
                    next_frontier: set[str] = set()
                    for resource_id in sorted(frontier):
                        for edge in adjacency.get(resource_id, []):
                            for endpoint in (edge.source_id, edge.target_id):
                                if endpoint not in visited_node_ids:
                                    visited_node_ids.add(endpoint)
                                    next_frontier.add(endpoint)
                    frontier = next_frontier

                # An induced neighborhood keeps intermediate cross-edges such
                # as A-X-Y-B intact, and retains every service branch reaching a
                # snapshot resource rather than picking a presentation winner.
                edge_rows = [
                    edge for edge in all_edge_rows
                    if edge.source_id in visited_node_ids and edge.target_id in visited_node_ids
                ]
            else:
                edge_rows = (await session.scalars(stmt)).all()

            edges = [
                {
                    "edge_id": f"{e.source_id}->{e.target_id}",
                    "source_resource_id": e.source_id,
                    "target_resource_id": e.target_id,
                    "relation_type": _canonical_relation_type(e.relation_type, profile_id),
                    "directed": e.direction_kind in ("SOURCE_RELATION", "DIRECTED"),
                    "source_id": e.source_table or e.source_id or ("topoIT" if profile_id == "IT_SERVICES" else "topoIP"),
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "source_version": e.source_version,
                    "dependency_semantics": (
                        e.dependency_semantics
                        or getattr(version_record, "dependency_semantics", None)
                    ),
                    "p2_eligible": getattr(version_record, "p2_eligible", False) is True,
                    "provenance_class": "EXTERNAL_OPERATIONAL",
                    "provenance_subtype": "TOPOLOGY_EXTERNAL",
                    "quality_status": "UNKNOWN",
                }
                for e in edge_rows
            ]

            # Query nodes
            if resource_ids and edge_rows:
                connected_node_ids = {e.source_id for e in edge_rows} | {e.target_id for e in edge_rows} | set(resource_ids)
                node_stmt = select(TopologyNodeRecord).where(
                    TopologyNodeRecord.profile_id == profile_id,
                    TopologyNodeRecord.topology_version == topology_version,
                    TopologyNodeRecord.resource_id.in_(connected_node_ids),
                )
            else:
                node_stmt = select(TopologyNodeRecord).where(
                    TopologyNodeRecord.profile_id == profile_id,
                    TopologyNodeRecord.topology_version == topology_version,
                )
            node_rows = (await session.scalars(node_stmt)).all()
            topo_layer = "IP" if profile_id == "IP_NETWORK" else ("IT" if profile_id == "IT_SERVICES" else None)
            nodes = [
                {
                    "resource_id": n.resource_id,
                    "source_id": (n.source_tables[0] if n.source_tables else n.resource_id),
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "topology_layer": topo_layer,
                    "network_class": (n.attributes or {}).get("network_class") if n.attributes else None,
                    "source_version": topology_version,
                }
                for n in node_rows
            ]

            # Query alias resolutions
            alias_rows = (
                await session.scalars(
                    select(TopologyAliasResolutionRecord).where(
                        TopologyAliasResolutionRecord.profile_id == profile_id,
                        TopologyAliasResolutionRecord.topology_version == topology_version,
                    )
                )
            ).all()
            aliases = [
                {
                    "alias_key": a.alias_key,
                    "status": a.status,
                    "unique_resource_id": a.unique_resource_id,
                    "verified_by": a.verified_by,
                }
                for a in alias_rows
            ]

            return {
                "edges": edges,
                "nodes": nodes,
                "profile_id": profile_id,
                "topology_version": topology_version,
                "relation_model": getattr(version_record, "relation_model", None),
                "direction_kind": getattr(version_record, "direction_kind", None),
                "dependency_semantics": getattr(version_record, "dependency_semantics", None),
                "p2_eligible": getattr(version_record, "p2_eligible", False) is True,
                "alias_resolution": aliases,
                "mappings": [],
                "failure_domains": [],
                "active_paths": [],
            }

    async def hydrate_graph_edges(
        self,
        profile_id: str,
        topology_version: str,
        resource_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Hydrate edges subset for analysis worker."""
        async with self.sessions() as session:
            stmt = select(TopologyEdgeRecord).where(
                TopologyEdgeRecord.profile_id == profile_id,
                TopologyEdgeRecord.topology_version == topology_version,
            )
            if resource_ids:
                stmt = stmt.where(
                    or_(
                        TopologyEdgeRecord.source_id.in_(resource_ids),
                        TopologyEdgeRecord.target_id.in_(resource_ids),
                    )
                )
            edges = (await session.scalars(stmt)).all()
            return [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "relation_type": e.relation_type,
                    "direction_kind": e.direction_kind,
                    "dependency_semantics": e.dependency_semantics,
                    "source_table": e.source_table,
                    "source_version": e.source_version,
                }
                for e in edges
            ]

    async def get_subgraph(
        self,
        profile_id: str,
        *,
        seeds: list[str],
        max_hops: int = 2,
        max_nodes: int = 150,
        topology_version: str | None = None,
    ) -> dict[str, Any]:
        """Extract k-hop induced neighborhood subgraph around seed identifiers."""
        if max_hops not in (1, 2, 3, 4):
            raise ValueError("max_hops must be between 1 and 4")

        cleaned_seeds = sorted({s.strip() for s in seeds if s and s.strip()})
        empty_metadata = {
            "requested_seed_count": len(cleaned_seeds),
            "resolved_seed_count": 0,
            "retained_seed_count": 0,
            "dropped_seed_count": 0,
            "truncated": False,
            "truncation_reasons": [],
        }
        if profile_id == "ALARM_ONLY":
            return {
                "status": "UNAVAILABLE",
                "reason": "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE",
                "profile_id": profile_id,
                "nodes": [],
                "edges": [],
                **empty_metadata,
            }

        async with self.sessions() as session:
            target_version = topology_version
            if target_version is None:
                active = await session.get(TopologyActiveVersionRecord, profile_id)
                if active is None:
                    return {
                        "status": "UNAVAILABLE",
                        "reason": "TOPOLOGY_NOT_ACTIVE",
                        "profile_id": profile_id,
                        "nodes": [],
                        "edges": [],
                        **empty_metadata,
                    }
                target_version = active.topology_version

            if not cleaned_seeds:
                return {
                    "status": "AVAILABLE",
                    "profile_id": profile_id,
                    "topology_version": target_version,
                    "nodes": [],
                    "edges": [],
                    **empty_metadata,
                }

            safe_hops = max_hops
            cache_key = f"subgraph-v3:{profile_id}:{target_version}:{','.join(cleaned_seeds)}:{safe_hops}:{max_nodes}"
            cached = getattr(self, "_subgraph_cache", {}).get(cache_key)
            if cached is not None:
                ts, val = cached
                if time.time() - ts < 600:
                    return val

            try:
                db_cache_stmt = select(TopologySubgraphCache).where(
                    TopologySubgraphCache.cache_key == cache_key
                )
                db_cached = (await session.scalars(db_cache_stmt)).first()
                if db_cached is not None and db_cached.subgraph_payload:
                    val = db_cached.subgraph_payload
                    if hasattr(self, "_subgraph_cache"):
                        self._subgraph_cache[cache_key] = (time.time(), val)
                    return val
            except Exception:
                LOGGER.debug("Topology subgraph DB cache lookup failed", exc_info=True)

            # 1. Resolve seeds to resource_ids
            alias_stmt = select(TopologyAliasResolutionRecord).where(
                TopologyAliasResolutionRecord.profile_id == profile_id,
                TopologyAliasResolutionRecord.topology_version == target_version,
                TopologyAliasResolutionRecord.alias_key.in_(cleaned_seeds),
            )
            alias_rows = (await session.scalars(alias_stmt)).all()
            seed_to_resource_ids: dict[str, set[str]] = {seed: set() for seed in cleaned_seeds}
            for alias in alias_rows:
                if alias.unique_resource_id and alias.alias_key in seed_to_resource_ids:
                    seed_to_resource_ids[alias.alias_key].add(alias.unique_resource_id)

            node_seed_stmt = select(TopologyNodeRecord).where(
                TopologyNodeRecord.profile_id == profile_id,
                TopologyNodeRecord.topology_version == target_version,
                or_(
                    TopologyNodeRecord.resource_id.in_(cleaned_seeds),
                    TopologyNodeRecord.display_name.in_(cleaned_seeds),
                ),
            )
            node_seed_rows = (await session.scalars(node_seed_stmt)).all()
            for nr in node_seed_rows:
                for seed in cleaned_seeds:
                    if seed == nr.resource_id or seed == nr.display_name:
                        seed_to_resource_ids[seed].add(nr.resource_id)

            # Match IP prefixes if display_name has CIDR mask e.g. 10.210.48.136 matching 10.210.48.136/22
            # Match IP prefixes for all seeds across all source tables (server, storage, db)
            for s in cleaned_seeds:
                like_stmt = select(TopologyNodeRecord.resource_id).where(
                    TopologyNodeRecord.profile_id == profile_id,
                    TopologyNodeRecord.topology_version == target_version,
                    TopologyNodeRecord.display_name.like(f"{s}%"),
                ).limit(10)
                matched = (await session.scalars(like_stmt)).all()
                seed_to_resource_ids[s].update(matched)

            seed_resource_ids = {
                resource_id
                for resource_ids in seed_to_resource_ids.values()
                for resource_id in resource_ids
            }
            resolved_seed_count = sum(bool(resource_ids) for resource_ids in seed_to_resource_ids.values())

            if not seed_resource_ids:
                return {
                    "status": "AVAILABLE",
                    "profile_id": profile_id,
                    "topology_version": target_version,
                    "nodes": [],
                    "edges": [],
                    **{
                        **empty_metadata,
                        "resolved_seed_count": resolved_seed_count,
                    },
                }

            # 2. BFS k-hop expansion (both source and target directions)
            safe_max_nodes = max(0, max_nodes)
            admitted_seed_ids = sorted(seed_resource_ids)[:safe_max_nodes]
            admitted_seed_id_set = set(admitted_seed_ids)
            retained_seed_count = sum(
                bool(resource_ids & admitted_seed_id_set)
                for resource_ids in seed_to_resource_ids.values()
            )
            dropped_seed_count = resolved_seed_count - retained_seed_count
            truncation_reasons: set[str] = set()
            if dropped_seed_count:
                truncation_reasons.add("SEED_NODE_LIMIT")
            visited_node_ids = set(admitted_seed_ids)
            current_frontier = set(admitted_seed_ids)
            collected_edges: list[TopologyEdgeRecord] = []
            seen_edge_ids: set[Any] = set()

            for _ in range(safe_hops):
                if not current_frontier:
                    break

                edge_stmt = select(TopologyEdgeRecord).where(
                    TopologyEdgeRecord.profile_id == profile_id,
                    TopologyEdgeRecord.topology_version == target_version,
                    or_(
                        TopologyEdgeRecord.source_id.in_(current_frontier),
                        TopologyEdgeRecord.target_id.in_(current_frontier),
                    ),
                ).order_by(TopologyEdgeRecord.id).limit(501)

                edges = (await session.scalars(edge_stmt)).all()
                if len(edges) > 500:
                    truncation_reasons.add("EDGE_QUERY_LIMIT")
                    edges = edges[:500]
                next_frontier = set()

                for edge in edges:
                    if edge.id in seen_edge_ids:
                        continue
                    new_node_ids = {
                        nid for nid in (edge.source_id, edge.target_id)
                        if nid not in visited_node_ids
                    }
                    if len(visited_node_ids) + len(new_node_ids) > safe_max_nodes:
                        truncation_reasons.add("NODE_LIMIT")
                        continue
                    seen_edge_ids.add(edge.id)
                    collected_edges.append(edge)
                    for nid in new_node_ids:
                        if nid not in visited_node_ids:
                            visited_node_ids.add(nid)
                            next_frontier.add(nid)

                current_frontier = next_frontier

            # Also collect remaining cross-edges among all visited_node_ids
            if len(visited_node_ids) > 1:
                cross_stmt = select(TopologyEdgeRecord).where(
                    TopologyEdgeRecord.profile_id == profile_id,
                    TopologyEdgeRecord.topology_version == target_version,
                    TopologyEdgeRecord.source_id.in_(visited_node_ids),
                    TopologyEdgeRecord.target_id.in_(visited_node_ids),
                ).order_by(TopologyEdgeRecord.id).limit(1001)
                cross_edges = (await session.scalars(cross_stmt)).all()
                if len(cross_edges) > 1000:
                    truncation_reasons.add("CROSS_EDGE_QUERY_LIMIT")
                    cross_edges = cross_edges[:1000]
                for ce in cross_edges:
                    if (
                        ce.id not in seen_edge_ids
                        and ce.source_id in visited_node_ids
                        and ce.target_id in visited_node_ids
                    ):
                        seen_edge_ids.add(ce.id)
                        collected_edges.append(ce)

            # 3. Retrieve node metadata
            node_records = (
                await session.scalars(
                    select(TopologyNodeRecord).where(
                        TopologyNodeRecord.profile_id == profile_id,
                        TopologyNodeRecord.topology_version == target_version,
                        TopologyNodeRecord.resource_id.in_(visited_node_ids),
                    )
                )
            ).all()

            nodes_out = [
                {
                    "id": n.resource_id,
                    "name": n.display_name or n.resource_id,
                    "type": n.resource_type,
                    "is_seed": n.resource_id in visited_node_ids and n.resource_id in seed_resource_ids,
                    "source_tables": n.source_tables or [],
                    "attributes": n.attributes or {},
                }
                for n in node_records
            ]

            edges_out = [
                {
                    "id": f"edge-{e.source_id}-{e.target_id}",
                    "source": e.source_id,
                    "target": e.target_id,
                    "relation": _canonical_relation_type(e.relation_type, profile_id),
                    "direction_kind": e.direction_kind or "NONE",
                    "dependency_semantics": e.dependency_semantics or "UNVERIFIED",
                }
                for e in collected_edges
                if e.source_id in visited_node_ids and e.target_id in visited_node_ids
            ]

            result = {
                "status": "AVAILABLE",
                "profile_id": profile_id,
                "topology_version": target_version,
                "nodes": nodes_out,
                "edges": edges_out,
                "requested_seed_count": len(cleaned_seeds),
                "resolved_seed_count": resolved_seed_count,
                "retained_seed_count": retained_seed_count,
                "dropped_seed_count": dropped_seed_count,
                "truncated": bool(truncation_reasons),
                "truncation_reasons": sorted(truncation_reasons),
            }
            if hasattr(self, "_subgraph_cache"):
                if len(self._subgraph_cache) > 200:
                    self._subgraph_cache.clear()
                self._subgraph_cache[cache_key] = (time.time(), result)
            try:
                subgraph_record = TopologySubgraphCache(
                    cache_key=cache_key,
                    profile_id=profile_id,
                    topology_version=target_version,
                    subgraph_payload=result,
                )
                await session.merge(subgraph_record)
                await session.commit()
            except Exception:
                LOGGER.debug("Failed to persist topology subgraph to DB cache", exc_info=True)
                await session.rollback()
            return result

    async def get_host_modules_map(
        self,
        profile_id: str,
        *,
        topology_version: str | None = None,
    ) -> tuple[dict[str, list[ModuleCandidate]], dict[str, str]]:
        """Retrieve host IP -> list of ModuleCandidates and IP -> canonical instance resource_id."""
        target_version = topology_version
        if target_version is None:
            active = await self.get_active_version(profile_id)
            if active is not None:
                target_version = active.topology_version

        if not target_version:
            return {}, {}

        cache_key = (profile_id, target_version)
        cached = self._host_modules_cache.get(cache_key)
        if cached is not None:
            self._host_modules_cache.move_to_end(cache_key)
            return cached

        # Serialize cache misses so concurrent chain-detail requests for the
        # same topology version share a single full-map database read.
        async with self._host_modules_cache_lock:
            cached = self._host_modules_cache.get(cache_key)
            if cached is not None:
                self._host_modules_cache.move_to_end(cache_key)
                return cached

            maps = await self._load_host_modules_map(profile_id, target_version)
            self._host_modules_cache[cache_key] = maps
            self._host_modules_cache.move_to_end(cache_key)
            while len(self._host_modules_cache) > MAX_HOST_MODULE_MAP_CACHE_ENTRIES:
                self._host_modules_cache.popitem(last=False)
            return maps

    async def _load_host_modules_map(
        self,
        profile_id: str,
        topology_version: str,
    ) -> tuple[dict[str, list[ModuleCandidate]], dict[str, str]]:
        """Build the resolver map once for an exact, finalized version key."""
        async with self.sessions() as session:
            # 1. Fetch all INSTANCE nodes for this profile and version
            inst_stmt = select(TopologyNodeRecord).where(
                TopologyNodeRecord.profile_id == profile_id,
                TopologyNodeRecord.topology_version == topology_version,
                TopologyNodeRecord.resource_type == "INSTANCE",
            )
            inst_rows = (await session.scalars(inst_stmt)).all()
            host_canonical_id_map: dict[str, str] = {}
            id_to_ip: dict[str, str] = {}
            for row in inst_rows:
                clean_ip = (row.display_name or "").split("/")[0].strip()
                if clean_ip:
                    host_canonical_id_map[clean_ip] = row.resource_id
                    id_to_ip[row.resource_id] = clean_ip

            # 2. Fetch MODULE_HAS_INSTANCE edges and joining MODULE nodes
            edge_stmt = (
                select(
                    TopologyEdgeRecord.source_id,
                    TopologyEdgeRecord.target_id,
                    TopologyNodeRecord.display_name,
                )
                .join(
                    TopologyNodeRecord,
                    and_(
                        TopologyNodeRecord.profile_id == profile_id,
                        TopologyNodeRecord.topology_version == topology_version,
                        TopologyNodeRecord.resource_id == TopologyEdgeRecord.source_id,
                    ),
                )
                .where(
                    TopologyEdgeRecord.profile_id == profile_id,
                    TopologyEdgeRecord.topology_version == topology_version,
                    TopologyEdgeRecord.relation_type == "MODULE_HAS_INSTANCE",
                )
            )
            rows = (await session.execute(edge_stmt)).all()
            host_modules_map: dict[str, list[ModuleCandidate]] = {}
            for mod_res_id, inst_res_id, mod_name in rows:
                base_token = extract_base_module_token(mod_name or "")
                cand = ModuleCandidate(
                    resource_id=mod_res_id,
                    display_name=mod_name or mod_res_id,
                    base_token=base_token,
                    host_ip=id_to_ip.get(inst_res_id),
                )
                host_modules_map.setdefault(inst_res_id, []).append(cand)
                if inst_res_id in id_to_ip:
                    ip = id_to_ip[inst_res_id]
                    host_modules_map.setdefault(ip, []).append(cand)

            return host_modules_map, host_canonical_id_map

    async def get_alarm_entity_resolutions(
        self,
        alarm_ids: list[str],
        profile_id: str,
        topology_version: str,
    ) -> list[AlarmEntityResolution]:
        """Retrieve persisted entity resolutions for alarms."""
        if not alarm_ids:
            return []
        async with self.sessions() as session:
            stmt = select(AlarmEntityResolutionRecord).where(
                AlarmEntityResolutionRecord.profile_id == profile_id,
                AlarmEntityResolutionRecord.topology_version == topology_version,
                AlarmEntityResolutionRecord.alarm_id.in_(alarm_ids),
            )
            rows = (await session.scalars(stmt)).all()
            return [
                AlarmEntityResolution(
                    alarm_id=r.alarm_id,
                    entity_role=r.entity_role,
                    raw_value=r.raw_value,
                    resource_id=r.resource_id,
                    status=MappingStatus(r.status),
                    method=MappingMethod(r.method),
                    source_field=r.source_field,
                    confidence=r.confidence,
                    topology_profile_id=r.profile_id,
                    topology_version=r.topology_version,
                    candidate_resource_ids=tuple(r.candidate_resource_ids or ()),
                    matched_text=r.matched_text,
                    resolver_version=r.resolver_version,
                )
                for r in rows
            ]

    async def save_alarm_entity_resolutions(
        self,
        resolutions: Sequence[AlarmEntityResolution],
    ) -> None:
        """Persist alarm entity resolutions to database."""
        if not resolutions:
            return
        if any(
            not r.topology_profile_id or not r.topology_version
            for r in resolutions
        ):
            raise ValueError(
                "Alarm entity resolutions require an explicit topology profile and version"
            )

        async with self.sessions() as session:
            for r in resolutions:
                res_id = f"{r.alarm_id}:{r.entity_role}:{r.source_field or ''}:{r.topology_profile_id}:{r.topology_version}:{r.resolver_version or ''}"
                existing = await session.get(AlarmEntityResolutionRecord, res_id)
                if existing is None:
                    rec = AlarmEntityResolutionRecord(
                        resolution_id=res_id,
                        alarm_id=r.alarm_id,
                        profile_id=r.topology_profile_id,
                        topology_version=r.topology_version,
                        resolver_version=r.resolver_version or "v1",
                        entity_role=r.entity_role,
                        raw_value=r.raw_value,
                        resource_id=r.resource_id,
                        status=r.status.value if hasattr(r.status, "value") else str(r.status),
                        method=r.method.value if hasattr(r.method, "value") else str(r.method),
                        source_field=r.source_field,
                        confidence=r.confidence,
                        candidate_resource_ids=list(r.candidate_resource_ids),
                        matched_text=r.matched_text,
                    )
                    session.add(rec)
                else:
                    existing.profile_id = r.topology_profile_id
                    existing.topology_version = r.topology_version
                    existing.resolver_version = r.resolver_version or "v1"
                    existing.raw_value = r.raw_value
                    existing.resource_id = r.resource_id
                    existing.status = r.status.value if hasattr(r.status, "value") else str(r.status)
                    existing.method = r.method.value if hasattr(r.method, "value") else str(r.method)
                    existing.source_field = r.source_field
                    existing.confidence = r.confidence
                    existing.candidate_resource_ids = list(r.candidate_resource_ids)
                    existing.matched_text = r.matched_text
            await session.commit()

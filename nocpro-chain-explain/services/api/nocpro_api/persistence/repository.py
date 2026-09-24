from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import replace
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from typing import Any, Mapping, Sequence
import uuid

import zstandard
from sqlalchemy import and_, case, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from libs.contracts import IngestedPackage, load_validated_package
from libs.contracts.analysis_identity import analysis_identity_from_projection
from evolution import (
    GlobalEpisodeDag,
    GlobalLineageComponent as DomainLineageComponent,
    GlobalLineageEdge as DomainLineageEdge,
    GlobalLineageNode as DomainLineageNode,
    LineageNodeKey,
)
from similar_chains import (
    TimedChainFingerprint,
    VersionedSimilarityIndex,
    fingerprint_from_dict,
    fingerprint_to_dict,
    model_from_dict,
    model_to_dict,
)
from history import (
    HistoricalEvidenceModel,
    HistoricalTaxonomy,
    model_from_dict as historical_model_from_dict,
    model_to_dict as historical_model_to_dict,
    taxonomy_from_dict as historical_taxonomy_from_dict,
    taxonomy_to_dict as historical_taxonomy_to_dict,
)
from ..observability import active_observability
from temporal_delay import (
    CURRENT_DELAY_MODEL_IMPLEMENTATION_VERSION,
    FrozenDelayModel,
    model_from_dict as delay_model_from_dict,
    model_to_dict as delay_model_to_dict,
)

from .change_journal import append_change_if_enabled


from tier2.audit_artifact import (
    AUDIT_ANALYSIS_VERSION,
    ReviewAuditArtifact,
    audit_artifact_from_dict,
    audit_artifact_to_dict,
)

from ..ingest.wire import SnapshotChunkEvent, SnapshotCompleteEvent, SnapshotWireEvent
from .models import (
    Alarm,
    AuditArtifactRecord,
    Chain,
    ChainQualityAssessmentRecord,
    QualityEvaluationReceiptRecord,
    CounterfactualJobRecord,
    DeepDiveJobRecord,
    KafkaInbox,
    LineageComponent,
    LineageEdge,
    LineageNode,
    Membership,
    Snapshot,
    SnapshotChunk,
    SnapshotIngest,
    SimilarityFingerprint,
    SimilarityIndexEntry,
    SimilarityModelRecord,
    HistoricalEvidenceModelRecord,
    TemporalDelayModelRecord,
    OperatorFeedbackRecord,
    TopologyVersionRecord,
    CandidateDisplayEventModel,
    CandidateExposureModel,
    FeedbackLifecycleEventModel,
    ManualCorrectionModel,
    ReviewCaseModel,
    ReviewFeedbackModel,
    ReviewSessionModel,
)
from review_learning.contracts import (
    CandidateDisplayEvent,
    CandidateExposure,
    FeedbackLifecycleType,
    ManualCorrection,
    ReviewCase,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _assert_succeeded_result_replay(existing: Any, values: dict[str, Any], kind: str) -> None:
    """A successful source job can be replayed, but its result cannot change."""
    if existing.status == "SUCCEEDED" and values["status"] == "SUCCEEDED":
        if (
            existing.result_payload is None
            or values["result_payload"] is None
            or _canonical_sha256(existing.result_payload)
            != _canonical_sha256(values["result_payload"])
        ):
            raise ValueError(f"{kind} result integrity conflict after SUCCEEDED")


def _receipt_revision(assessment: dict[str, Any], source_refs: dict[str, Any]) -> str:
    """Hash stable assessment facts and exact sources, never publication metadata."""
    def stable(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items()
                    if key not in {"created_at", "updated_at", "progress", "progress_percent"}}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    return _canonical_sha256({
        "assessment": stable(assessment),
        "source_artifact_fingerprints": {
            key: value for key, value in source_refs.items() if key.endswith("fingerprint")
        },
        "policy_version": assessment["readiness_policy_version"],
    })


def _record_db_read(stage: str, started: float) -> None:
    observability = active_observability()
    if observability is not None:
        observability.record_duration(
            "db.read.duration",
            max(0.0, time.perf_counter() - started),
            {"stage": stage},
        )


@dataclass(frozen=True)
class IngestResult:
    snapshot_id: str
    snapshot_version: str
    status: str
    duplicate: bool = False
    completed_now: bool = False
    invalid_reason: str | None = None
    canonical_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class Tier1AClaim:
    snapshot_id: str
    snapshot_version: str
    payload: dict[str, Any]
    worker_id: str
    attempt_count: int


@dataclass(frozen=True)
class LineageClaim:
    snapshot_id: str
    snapshot_version: str
    payload: dict[str, Any]
    previous_payload: dict[str, Any] | None
    previous_lineage_status: str | None
    worker_id: str


@dataclass(frozen=True)
class SimilarityClaim:
    snapshot_id: str
    snapshot_version: str
    payload: dict[str, Any]
    worker_id: str


@dataclass(frozen=True)
class StoredCounterfactualJob:
    job_id: str
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    cache_fingerprint: str
    status: str
    progress_percent: int
    cache_hit: bool
    identity: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredDeepDiveJob:
    job_id: str
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    cache_fingerprint: str
    analysis_config_version: str | None
    topology_version: str | None
    status: str
    progress_percent: int
    cache_hit: bool
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredChainQualityAssessment:
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    assessment_version: str
    input_fingerprint: str
    status: str
    stars: int | None
    label: str
    available_dimension_count: int
    stage: str
    deep_dive_job_id: str | None
    counterfactual_job_id: str | None
    recommendation_status: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredQualityEvaluationReceipt:
    receipt_id: str
    identity_digest: str
    artifact_revision: str
    analysis_identity: dict[str, Any]
    assessment: dict[str, Any]
    source_artifact_refs: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class StoredOperatorFeedback:
    feedback_id: str
    job_id: str
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    candidate_id: str
    operation: str
    decision: str
    operator_id: str
    reason: str | None
    partition_delta: dict[str, Any]
    mutation_dispatched: bool
    mutation_dispatch_result: dict[str, Any] | None
    created_at: datetime


@dataclass(frozen=True)
class StoredEvolutionNode:
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    snapshot_time: datetime
    lineage_component_id: str
    branch_id: str
    source_kind: str | None


@dataclass(frozen=True)
class StoredEvolutionEdge:
    parent_snapshot_id: str
    parent_snapshot_version: str
    parent_chain_id: str
    child_snapshot_id: str
    child_snapshot_version: str
    child_chain_id: str
    event_type: str
    overlap_count: int
    contain_parent: float
    contain_child: float


@dataclass(frozen=True)
class StoredEvolution:
    status: str
    reason: str | None
    source_kind: str | None
    sequence_status: str
    production_validation: str
    lineage_component_id: str | None
    branch_id: str | None
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    nodes: tuple[StoredEvolutionNode, ...] = ()
    edges: tuple[StoredEvolutionEdge, ...] = ()


DERIVED_REPLAY_SNAPSHOT_SOURCES = frozenset({
    "nocpro-mock-derived-replay-slicer",
})


def _sequence_production_validation(snapshot_rows) -> str:
    """Return production eligibility without promoting derived replay windows.

    ``REAL_EXPORT_REPLAY`` records may be real observations, but time windows
    derived locally from one export are not verified sequential upstream
    snapshots.  The source marker is persisted with each snapshot so a restart
    cannot silently promote the derived sequence later.
    """
    source_kinds = {row.source_kind for row in snapshot_rows}
    sources = {row.source for row in snapshot_rows}
    if (
        source_kinds <= {"REAL_LIVE", "REAL_EXPORT_REPLAY"}
        and not sources.intersection(DERIVED_REPLAY_SNAPSHOT_SOURCES)
    ):
        return "ELIGIBLE"
    return "NOT_ESTABLISHED"


def _logical_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class SnapshotRepository:
    """Transactional chunk assembly and relational snapshot persistence."""

    def __init__(
        self,
        sessions: async_sessionmaker,
        *,
        max_compressed_snapshot_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self.sessions = sessions
        self.max_compressed_snapshot_bytes = max_compressed_snapshot_bytes

    async def load_evolution(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        chain_id: str,
    ) -> StoredEvolution:
        """Project only the verified, persisted episode-DAG artifact.

        This deliberately does not load snapshots or re-run the evolution
        algorithm at request time.  A lineage node without an edge is one
        snapshot of state, not a verified sequence.
        """
        unavailable = lambda reason, source_kind=None: StoredEvolution(
            status="UNAVAILABLE",
            reason=reason,
            source_kind=source_kind,
            sequence_status="UNAVAILABLE",
            production_validation="NOT_ESTABLISHED",
            lineage_component_id=None,
            branch_id=None,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            chain_id=chain_id,
        )
        async with self.sessions() as session:
            snapshot = await session.get(
                SnapshotIngest, (snapshot_id, snapshot_version)
            )
            if snapshot is None:
                return unavailable("SNAPSHOT_NOT_PERSISTED")
            if snapshot.lineage_status != "READY":
                return unavailable(
                    "SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE", snapshot.source_kind
                )
            current = await session.get(
                LineageNode, (snapshot_id, snapshot_version, chain_id)
            )
            if current is None:
                return unavailable(
                    "SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE", snapshot.source_kind
                )
            component = await session.get(LineageComponent, current.component_id)
            if component is None:
                raise ValueError("persisted lineage node has no component")
            canonical_component_id = component.canonical_component_id
            component_ids = list(
                (
                    await session.scalars(
                        select(LineageComponent.component_id).where(
                            LineageComponent.canonical_component_id
                            == canonical_component_id
                        )
                    )
                ).all()
            )
            node_rows = list(
                (
                    await session.scalars(
                        select(LineageNode)
                        .where(LineageNode.component_id.in_(component_ids))
                        .order_by(
                            LineageNode.snapshot_time.asc(),
                            LineageNode.snapshot_id.asc(),
                            LineageNode.snapshot_version.asc(),
                            LineageNode.snapshot_chain_id.asc(),
                        )
                    )
                ).all()
            )
            keys = [
                (row.snapshot_id, row.snapshot_version, row.snapshot_chain_id)
                for row in node_rows
            ]
            edge_rows = list(
                (
                    await session.scalars(
                        select(LineageEdge)
                        .where(
                            tuple_(
                                LineageEdge.parent_snapshot_id,
                                LineageEdge.parent_snapshot_version,
                                LineageEdge.parent_chain_id,
                            ).in_(keys),
                            tuple_(
                                LineageEdge.child_snapshot_id,
                                LineageEdge.child_snapshot_version,
                                LineageEdge.child_chain_id,
                            ).in_(keys),
                        )
                        .order_by(
                            LineageEdge.parent_snapshot_id.asc(),
                            LineageEdge.parent_snapshot_version.asc(),
                            LineageEdge.parent_chain_id.asc(),
                            LineageEdge.child_snapshot_id.asc(),
                            LineageEdge.child_snapshot_version.asc(),
                            LineageEdge.child_chain_id.asc(),
                        )
                    )
                ).all()
            )
            node_time_by_key = {
                (row.snapshot_id, row.snapshot_version, row.snapshot_chain_id): row.snapshot_time
                for row in node_rows
            }
            edge_rows.sort(
                key=lambda row: (
                    node_time_by_key[
                        (
                            row.parent_snapshot_id,
                            row.parent_snapshot_version,
                            row.parent_chain_id,
                        )
                    ],
                    node_time_by_key[
                        (
                            row.child_snapshot_id,
                            row.child_snapshot_version,
                            row.child_chain_id,
                        )
                    ],
                    row.parent_chain_id,
                    row.child_chain_id,
                )
            )
            if not edge_rows:
                return unavailable(
                    "SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE", snapshot.source_kind
                )
            snapshot_rows = list(
                (
                    await session.scalars(
                        select(SnapshotIngest).where(
                            tuple_(
                                SnapshotIngest.snapshot_id,
                                SnapshotIngest.snapshot_version,
                            ).in_([(row.snapshot_id, row.snapshot_version) for row in node_rows])
                        )
                    )
                ).all()
            )
        source_by_snapshot = {
            (row.snapshot_id, row.snapshot_version): row.source_kind
            for row in snapshot_rows
        }
        production_validation = _sequence_production_validation(snapshot_rows)
        return StoredEvolution(
            status="AVAILABLE",
            reason=None,
            source_kind=snapshot.source_kind,
            sequence_status="VERIFIED",
            production_validation=production_validation,
            lineage_component_id=canonical_component_id,
            branch_id=current.branch_id,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            chain_id=chain_id,
            nodes=tuple(
                StoredEvolutionNode(
                    snapshot_id=row.snapshot_id,
                    snapshot_version=row.snapshot_version,
                    chain_id=row.snapshot_chain_id,
                    snapshot_time=row.snapshot_time,
                    lineage_component_id=canonical_component_id,
                    branch_id=row.branch_id,
                    source_kind=source_by_snapshot.get(
                        (row.snapshot_id, row.snapshot_version)
                    ),
                )
                for row in node_rows
            ),
            edges=tuple(
                StoredEvolutionEdge(
                    parent_snapshot_id=row.parent_snapshot_id,
                    parent_snapshot_version=row.parent_snapshot_version,
                    parent_chain_id=row.parent_chain_id,
                    child_snapshot_id=row.child_snapshot_id,
                    child_snapshot_version=row.child_snapshot_version,
                    child_chain_id=row.child_chain_id,
                    event_type=row.edge_type,
                    overlap_count=row.overlap_count,
                    contain_parent=row.contain_parent,
                    contain_child=row.contain_child,
                )
                for row in edge_rows
            ),
        )

    async def persist_audit_artifact(
        self, artifact: ReviewAuditArtifact
    ) -> ReviewAuditArtifact:
        """Insert one immutable exact artifact; never update an existing run."""
        payload = audit_artifact_to_dict(artifact)
        validated = audit_artifact_from_dict(payload)
        values = {
            "artifact_id": validated.artifact_id,
            "artifact_version": validated.artifact_version,
            "artifact_fingerprint": validated.artifact_fingerprint,
            "snapshot_id": validated.snapshot_id,
            "snapshot_version": validated.snapshot_version,
            "chain_id": validated.chain_id,
            "chain_fingerprint": validated.chain_fingerprint,
            "analysis_version": validated.analysis_version,
            "analysis_config_version": validated.analysis_config_version,
            "status": validated.status,
            "mode": validated.mode,
            "payload": payload,
            "created_at": _logical_time(validated.created_at),
        }
        async with self.sessions.begin() as session:
            existing = await session.get(AuditArtifactRecord, validated.artifact_id)
            if existing is not None:
                if existing.payload != payload:
                    raise ValueError("Audit artifact identity is immutable")
                return audit_artifact_from_dict(existing.payload)
            await session.execute(pg_insert(AuditArtifactRecord).values(**values))
        return validated

    async def latest_compatible_audit_artifact(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        chain_id: str,
        chain_fingerprint: str,
        analysis_version: str,
        analysis_config_version: str,
        topology_version: str | None = None,
    ) -> ReviewAuditArtifact | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(AuditArtifactRecord)
                .where(
                    AuditArtifactRecord.snapshot_id == snapshot_id,
                    AuditArtifactRecord.snapshot_version == snapshot_version,
                    AuditArtifactRecord.chain_id == chain_id,
                    AuditArtifactRecord.chain_fingerprint == chain_fingerprint,
                    AuditArtifactRecord.analysis_version == analysis_version,
                    AuditArtifactRecord.analysis_config_version
                    == analysis_config_version,
                    AuditArtifactRecord.status == "AVAILABLE",
                    AuditArtifactRecord.mode == "EXACT",
                )
                .order_by(AuditArtifactRecord.created_at.desc())
                .limit(1)
            )
        if row is None:
            return None
        artifact = audit_artifact_from_dict(row.payload)
        if (
            artifact.artifact_id != row.artifact_id
            or artifact.artifact_fingerprint != row.artifact_fingerprint
        ):
            raise ValueError("persisted Audit artifact columns do not match payload")
        if artifact.topology_version != topology_version:
            return None
        return artifact

    async def persist_counterfactual_job(
        self, payload: dict[str, Any]
    ) -> StoredCounterfactualJob:
        """Upsert one immutable-identity Review lifecycle snapshot."""
        status_rank = {"QUEUED": 0, "RUNNING": 1, "SUCCEEDED": 2, "FAILED": 2}
        if payload["status"] not in status_rank:
            raise ValueError("unknown counterfactual job status")
        if payload["status"] == "SUCCEEDED" and payload.get("result") is None:
            raise ValueError("successful counterfactual job must persist a result")
        values = {
            "job_id": payload["job_id"],
            "snapshot_id": payload["snapshot_id"],
            "snapshot_version": payload["snapshot_version"],
            "chain_id": payload["chain_id"],
            "cache_fingerprint": payload["cache_fingerprint"],
            "status": payload["status"],
            "progress_percent": payload["progress_percent"],
            "cache_hit": payload["cache_hit"],
            "identity_payload": payload["identity"],
            "result_payload": payload.get("result"),
            "error": payload.get("error"),
        }
        async with self.sessions.begin() as session:
            existing = await session.get(
                CounterfactualJobRecord, payload["job_id"], with_for_update=True
            )
            if existing is not None:
                immutable = (
                    existing.snapshot_id,
                    existing.snapshot_version,
                    existing.chain_id,
                    existing.cache_fingerprint,
                    existing.identity_payload,
                )
                proposed = (
                    values["snapshot_id"],
                    values["snapshot_version"],
                    values["chain_id"],
                    values["cache_fingerprint"],
                    values["identity_payload"],
                )
                if immutable != proposed:
                    raise ValueError("counterfactual job identity is immutable")
                _assert_succeeded_result_replay(existing, values, "counterfactual job")
                if existing.status == "SUCCEEDED" and values["status"] == "SUCCEEDED":
                    return self._stored_counterfactual(existing)
                if status_rank[existing.status] > status_rank[values["status"]]:
                    return self._stored_counterfactual(existing)
                if (
                    status_rank[existing.status] == 2
                    and existing.status != values["status"]
                ):
                    raise ValueError("counterfactual terminal status is immutable")
            statement = pg_insert(CounterfactualJobRecord).values(**values)
            existing_rank = case(
                (CounterfactualJobRecord.status == "QUEUED", 0),
                (CounterfactualJobRecord.status == "RUNNING", 1),
                (CounterfactualJobRecord.status.in_(("SUCCEEDED", "FAILED")), 2),
                else_=-1,
            )
            incoming_rank = case(
                (statement.excluded.status == "QUEUED", 0),
                (statement.excluded.status == "RUNNING", 1),
                (statement.excluded.status.in_(("SUCCEEDED", "FAILED")), 2),
                else_=-1,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[CounterfactualJobRecord.job_id],
                set_={
                    "status": statement.excluded.status,
                    "progress_percent": statement.excluded.progress_percent,
                    "cache_hit": statement.excluded.cache_hit,
                    "result_payload": statement.excluded.result_payload,
                    "error": statement.excluded.error,
                    "updated_at": func.now(),
                },
                where=and_(
                    CounterfactualJobRecord.status != "SUCCEEDED",
                    or_(
                        incoming_rank > existing_rank,
                        and_(
                            incoming_rank == existing_rank,
                            CounterfactualJobRecord.status == statement.excluded.status,
                        ),
                    ),
                ),
            ).returning(CounterfactualJobRecord.job_id)
            written = (await session.execute(statement)).scalar_one_or_none()
            if written is None:
                current = await session.get(
                    CounterfactualJobRecord, payload["job_id"], with_for_update=True
                )
                if current is None:
                    raise RuntimeError("counterfactual job upsert conflict without source row")
                if (
                    current.snapshot_id, current.snapshot_version, current.chain_id,
                    current.cache_fingerprint, current.identity_payload,
                ) != (
                    values["snapshot_id"], values["snapshot_version"], values["chain_id"],
                    values["cache_fingerprint"], values["identity_payload"],
                ):
                    raise ValueError("counterfactual job identity is immutable")
                _assert_succeeded_result_replay(current, values, "counterfactual job")
        stored = await self.counterfactual_job(payload["job_id"])
        if stored is None:
            raise RuntimeError("persisted counterfactual job is unavailable")
        return stored

    async def persist_deep_dive_job(
        self, payload: dict[str, Any]
    ) -> StoredDeepDiveJob:
        """Upsert one immutable-identity Deep Dive lifecycle snapshot."""
        status_rank = {
            "QUEUED": 0,
            "RUNNING": 1,
            "SUCCEEDED": 2,
            "FAILED": 2,
            "INTERRUPTED": 2,
        }
        if payload["status"] not in status_rank:
            raise ValueError("unknown Deep Dive job status")
        progress = int(payload["progress_percent"])
        if not 0 <= progress <= 100:
            raise ValueError("Deep Dive progress must be between 0 and 100")
        if payload["status"] == "SUCCEEDED" and payload.get("result") is None:
            raise ValueError("successful Deep Dive must persist a result")
        values = {
            "job_id": payload["job_id"],
            "snapshot_id": payload["snapshot_id"],
            "snapshot_version": payload["snapshot_version"],
            "chain_id": payload["chain_id"],
            "cache_fingerprint": payload["cache_fingerprint"],
            "analysis_config_version": payload.get("analysis_config_version"),
            "topology_version": payload.get("topology_version"),
            "status": payload["status"],
            "progress_percent": progress,
            "cache_hit": payload["cache_hit"],
            "result_payload": payload.get("result"),
            "error": payload.get("error"),
        }
        async with self.sessions.begin() as session:
            existing = await session.get(
                DeepDiveJobRecord, payload["job_id"], with_for_update=True
            )
            if existing is not None:
                immutable = (
                    existing.snapshot_id,
                    existing.snapshot_version,
                    existing.chain_id,
                    existing.cache_fingerprint,
                    existing.analysis_config_version,
                    existing.topology_version,
                )
                proposed = (
                    values["snapshot_id"],
                    values["snapshot_version"],
                    values["chain_id"],
                    values["cache_fingerprint"],
                    values["analysis_config_version"],
                    values["topology_version"],
                )
                if immutable != proposed:
                    raise ValueError("Deep Dive job identity is immutable")
                _assert_succeeded_result_replay(existing, values, "Deep Dive job")
                if existing.status == "SUCCEEDED" and values["status"] == "SUCCEEDED":
                    return self._stored_deep_dive(existing)
                if status_rank[existing.status] > status_rank[values["status"]]:
                    return self._stored_deep_dive(existing)
                if (
                    status_rank[existing.status] == 2
                    and existing.status != values["status"]
                ):
                    raise ValueError("Deep Dive terminal status is immutable")
            statement = pg_insert(DeepDiveJobRecord).values(**values)
            existing_rank = case(
                (DeepDiveJobRecord.status == "QUEUED", 0),
                (DeepDiveJobRecord.status == "RUNNING", 1),
                (
                    DeepDiveJobRecord.status.in_(
                        ("SUCCEEDED", "FAILED", "INTERRUPTED")
                    ),
                    2,
                ),
                else_=-1,
            )
            incoming_rank = case(
                (statement.excluded.status == "QUEUED", 0),
                (statement.excluded.status == "RUNNING", 1),
                (
                    statement.excluded.status.in_(
                        ("SUCCEEDED", "FAILED", "INTERRUPTED")
                    ),
                    2,
                ),
                else_=-1,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[DeepDiveJobRecord.job_id],
                set_={
                    "status": statement.excluded.status,
                    "progress_percent": statement.excluded.progress_percent,
                    "cache_hit": statement.excluded.cache_hit,
                    "result_payload": statement.excluded.result_payload,
                    "error": statement.excluded.error,
                    "updated_at": func.now(),
                },
                where=and_(
                    DeepDiveJobRecord.status != "SUCCEEDED",
                    or_(
                        incoming_rank > existing_rank,
                        and_(
                            incoming_rank == existing_rank,
                            DeepDiveJobRecord.status == statement.excluded.status,
                        ),
                    ),
                ),
            ).returning(DeepDiveJobRecord.job_id)
            written = (await session.execute(statement)).scalar_one_or_none()
            if written is None:
                current = await session.get(
                    DeepDiveJobRecord, payload["job_id"], with_for_update=True
                )
                if current is None:
                    raise RuntimeError("Deep Dive job upsert conflict without source row")
                if (
                    current.snapshot_id, current.snapshot_version, current.chain_id,
                    current.cache_fingerprint, current.analysis_config_version,
                    current.topology_version,
                ) != (
                    values["snapshot_id"], values["snapshot_version"], values["chain_id"],
                    values["cache_fingerprint"], values["analysis_config_version"],
                    values["topology_version"],
                ):
                    raise ValueError("Deep Dive job identity is immutable")
                _assert_succeeded_result_replay(current, values, "Deep Dive job")
        stored = await self.deep_dive_job(payload["job_id"])
        if stored is None:
            raise RuntimeError("persisted Deep Dive job is unavailable")
        return stored

    async def deep_dive_job(
        self, job_id: str, *, interrupt_active: bool = False
    ) -> StoredDeepDiveJob | None:
        async with self.sessions.begin() as session:
            row = await session.get(DeepDiveJobRecord, job_id)
            if row is None:
                return None
            if interrupt_active and row.status in {"QUEUED", "RUNNING"}:
                row.status = "INTERRUPTED"
                row.progress_percent = 100
                row.error = "API_RESTART_INTERRUPTED"
                await session.flush()
                await session.refresh(row)
            return self._stored_deep_dive(row)

    async def latest_compatible_deep_dive_job(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        chain_id: str,
        cache_fingerprint: str,
        interrupt_active: bool = False,
    ) -> StoredDeepDiveJob | None:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(DeepDiveJobRecord)
                .where(
                    DeepDiveJobRecord.snapshot_id == snapshot_id,
                    DeepDiveJobRecord.snapshot_version == snapshot_version,
                    DeepDiveJobRecord.chain_id == chain_id,
                    DeepDiveJobRecord.cache_fingerprint == cache_fingerprint,
                )
                .order_by(DeepDiveJobRecord.updated_at.desc())
                .limit(1)
            )
            if row is None:
                return None
            if interrupt_active and row.status in {"QUEUED", "RUNNING"}:
                row.status = "INTERRUPTED"
                row.progress_percent = 100
                row.error = "API_RESTART_INTERRUPTED"
                await session.flush()
                await session.refresh(row)
            return self._stored_deep_dive(row)

    async def counterfactual_job(
        self, job_id: str
    ) -> StoredCounterfactualJob | None:
        started = time.perf_counter()
        try:
            async with self.sessions() as session:
                row = await session.get(CounterfactualJobRecord, job_id)
                return self._stored_counterfactual(row) if row is not None else None
        finally:
            _record_db_read("review-by-id", started)

    async def latest_compatible_counterfactual_job(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        chain_id: str,
        cache_fingerprint: str,
    ) -> StoredCounterfactualJob | None:
        started = time.perf_counter()
        try:
            async with self.sessions() as session:
                row = await session.scalar(
                    select(CounterfactualJobRecord)
                    .where(
                        CounterfactualJobRecord.snapshot_id == snapshot_id,
                        CounterfactualJobRecord.snapshot_version == snapshot_version,
                        CounterfactualJobRecord.chain_id == chain_id,
                        CounterfactualJobRecord.cache_fingerprint == cache_fingerprint,
                        CounterfactualJobRecord.status == "SUCCEEDED",
                    )
                    .order_by(CounterfactualJobRecord.updated_at.desc())
                    .limit(1)
                )
                return self._stored_counterfactual(row) if row is not None else None
        finally:
            _record_db_read("review-compatible-latest", started)

    async def latest_counterfactual_job_for_identity(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        chain_id: str,
        cache_fingerprint: str,
    ) -> StoredCounterfactualJob | None:
        """Return any lifecycle state for one exact Review identity.

        Unlike ``latest_compatible_counterfactual_job``, this includes queued
        and running rows so a process restart cannot submit duplicate current
        work while an older-config job is also present for the same chain.
        """
        started = time.perf_counter()
        try:
            async with self.sessions() as session:
                row = await session.scalar(
                    select(CounterfactualJobRecord)
                    .where(
                        CounterfactualJobRecord.snapshot_id == snapshot_id,
                        CounterfactualJobRecord.snapshot_version == snapshot_version,
                        CounterfactualJobRecord.chain_id == chain_id,
                        CounterfactualJobRecord.cache_fingerprint == cache_fingerprint,
                    )
                    .order_by(CounterfactualJobRecord.updated_at.desc())
                    .limit(1)
                )
                return self._stored_counterfactual(row) if row is not None else None
        finally:
            _record_db_read("review-identity-latest", started)

    async def latest_counterfactual_job(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        chain_id: str,
    ) -> StoredCounterfactualJob | None:
        started = time.perf_counter()
        try:
            async with self.sessions() as session:
                row = await session.scalar(
                    select(CounterfactualJobRecord)
                    .where(
                        CounterfactualJobRecord.snapshot_id == snapshot_id,
                        CounterfactualJobRecord.snapshot_version == snapshot_version,
                        CounterfactualJobRecord.chain_id == chain_id,
                        CounterfactualJobRecord.status == "SUCCEEDED",
                    )
                    .order_by(CounterfactualJobRecord.updated_at.desc())
                    .limit(1)
                )
                return self._stored_counterfactual(row) if row is not None else None
        finally:
            _record_db_read("review-latest", started)

    async def persist_chain_quality_assessment(
        self, payload: dict[str, Any]
    ) -> StoredChainQualityAssessment:
        """Upsert the deterministic assessment for one exact snapshot chain."""
        assessment = payload["assessment"]
        persisted_payload = dict(assessment)
        overview_projection = payload.get("overview_projection")
        if isinstance(overview_projection, dict):
            persisted_payload["overview_projection"] = overview_projection
        values = {
            "snapshot_id": payload["snapshot_id"],
            "snapshot_version": payload["snapshot_version"],
            "chain_id": payload["chain_id"],
            "assessment_version": payload.get("assessment_version", "HEURISTIC_V1"),
            "input_fingerprint": payload["input_fingerprint"],
            "status": str(assessment.get("status", "UNAVAILABLE")),
            "stars": assessment.get("stars"),
            "label": str(assessment.get("label") or "Chưa thể chấm"),
            "available_dimension_count": int(
                assessment.get("available_dimension_count") or 0
            ),
            "stage": payload.get("stage", "DETERMINISTIC_COMPLETE"),
            "deep_dive_job_id": payload.get("deep_dive_job_id"),
            "counterfactual_job_id": payload.get("counterfactual_job_id"),
            "recommendation_status": payload.get(
                "recommendation_status", "NOT_EVALUATED"
            ),
            "payload": persisted_payload,
        }
        statement = pg_insert(ChainQualityAssessmentRecord).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                ChainQualityAssessmentRecord.snapshot_id,
                ChainQualityAssessmentRecord.snapshot_version,
                ChainQualityAssessmentRecord.chain_id,
            ],
            set_={
                "assessment_version": statement.excluded.assessment_version,
                "input_fingerprint": statement.excluded.input_fingerprint,
                "status": statement.excluded.status,
                "stars": statement.excluded.stars,
                "label": statement.excluded.label,
                "available_dimension_count": statement.excluded.available_dimension_count,
                "stage": statement.excluded.stage,
                "deep_dive_job_id": statement.excluded.deep_dive_job_id,
                "counterfactual_job_id": statement.excluded.counterfactual_job_id,
                "recommendation_status": statement.excluded.recommendation_status,
                "payload": statement.excluded.payload,
                "updated_at": func.now(),
            },
            where=or_(
                ChainQualityAssessmentRecord.assessment_version.is_distinct_from(
                    statement.excluded.assessment_version
                ),
                ChainQualityAssessmentRecord.input_fingerprint.is_distinct_from(
                    statement.excluded.input_fingerprint
                ),
                ChainQualityAssessmentRecord.status.is_distinct_from(
                    statement.excluded.status
                ),
                ChainQualityAssessmentRecord.stars.is_distinct_from(
                    statement.excluded.stars
                ),
                ChainQualityAssessmentRecord.label.is_distinct_from(
                    statement.excluded.label
                ),
                ChainQualityAssessmentRecord.available_dimension_count.is_distinct_from(
                    statement.excluded.available_dimension_count
                ),
                ChainQualityAssessmentRecord.stage.is_distinct_from(
                    statement.excluded.stage
                ),
                ChainQualityAssessmentRecord.deep_dive_job_id.is_distinct_from(
                    statement.excluded.deep_dive_job_id
                ),
                ChainQualityAssessmentRecord.counterfactual_job_id.is_distinct_from(
                    statement.excluded.counterfactual_job_id
                ),
                ChainQualityAssessmentRecord.recommendation_status.is_distinct_from(
                    statement.excluded.recommendation_status
                ),
                ChainQualityAssessmentRecord.payload.is_distinct_from(
                    statement.excluded.payload
                ),
            ),
        )
        async with self.sessions.begin() as session:
            receipt_values = await self._verified_quality_receipt_values(session, payload)
            if receipt_values is None:
                raise RuntimeError("quality receipt provenance unavailable")
            changed_chain_id = (
                await session.execute(
                    statement.returning(ChainQualityAssessmentRecord.chain_id)
                )
            ).scalar_one_or_none()
            receipt_insert = pg_insert(QualityEvaluationReceiptRecord).values(**receipt_values)
            inserted = (await session.execute(
                receipt_insert.on_conflict_do_nothing(
                    index_elements=[
                        QualityEvaluationReceiptRecord.identity_digest,
                        QualityEvaluationReceiptRecord.artifact_revision,
                    ]
                ).returning(QualityEvaluationReceiptRecord.receipt_id)
            )).scalar_one_or_none()
            if inserted is None:
                existing = (await session.execute(
                    select(QualityEvaluationReceiptRecord).where(
                        QualityEvaluationReceiptRecord.identity_digest == receipt_values["identity_digest"],
                        QualityEvaluationReceiptRecord.artifact_revision == receipt_values["artifact_revision"],
                    )
                )).scalar_one()
                if any(getattr(existing, key) != receipt_values[key] for key in (
                    "analysis_identity", "assessment", "source_artifact_refs"
                )):
                    raise RuntimeError("quality receipt integrity conflict")
            if changed_chain_id is not None:
                projection = persisted_payload.get("overview_projection")
                adapted = analysis_identity_from_projection(projection)
                identity = adapted.identity if adapted.available else None
                identity_digest = (
                    hashlib.sha256(
                        json.dumps(
                            identity.to_payload(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest()
                    if identity is not None
                    else None
                )
                await append_change_if_enabled(
                    session,
                    event_type="quality.changed",
                    snapshot_id=values["snapshot_id"],
                    snapshot_version=values["snapshot_version"],
                    chain_id=values["chain_id"],
                    topology_version=(
                        identity.topology_version if identity is not None else None
                    ),
                    identity_digest=identity_digest,
                    invalidates=[
                        "quality-summary",
                        "chain-list",
                        "chain-detail",
                        "evolution",
                    ],
                )
        stored = await self.chain_quality_assessment(
            snapshot_id=values["snapshot_id"],
            snapshot_version=values["snapshot_version"],
            chain_id=values["chain_id"],
        )
        if stored is None:
            raise RuntimeError("persisted chain quality assessment is unavailable")
        return stored

    async def _verified_quality_receipt_values(self, session, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Admit only a current, source-backed deterministic quality result."""
        from ..quality_freshness import projection_staleness_reason
        from ..quality_readiness import quality_assessment_contract_is_valid
        from libs.contracts.analysis_identity import analysis_identity_from_review

        assessment = payload.get("assessment")
        projection = payload.get("overview_projection")
        if not quality_assessment_contract_is_valid(assessment) or not isinstance(projection, dict):
            return None
        if assessment.get("status") not in {"EVALUATED", "UNAVAILABLE"}:
            return None
        dimensions = assessment.get("dimensions")
        score = assessment.get("score")
        if assessment["status"] == "EVALUATED":
            if (
                type(score) not in {int, float} or not math.isfinite(score)
                or not 0.0 <= score <= 1.0
                or not isinstance(dimensions, list) or not dimensions
                or len(dimensions) != assessment.get("available_dimension_count")
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("name"), str)
                    or type(item.get("value")) not in {int, float}
                    or not math.isfinite(item["value"])
                    or not 0.0 <= item["value"] <= 1.0
                    or type(item.get("weight")) not in {int, float}
                    or not math.isfinite(item["weight"])
                    or item["weight"] <= 0
                    for item in dimensions
                )
            ):
                return None
        elif score is not None or dimensions != []:
            return None
        adapted = analysis_identity_from_projection(projection)
        if not adapted.available or adapted.identity is None:
            return None
        identity = adapted.identity
        if projection_staleness_reason(
            projection,
            snapshot_id=payload["snapshot_id"],
            snapshot_version=payload["snapshot_version"],
            chain_id=payload["chain_id"],
            input_fingerprint=payload["input_fingerprint"],
        ) is not None:
            return None
        if assessment.get("method") != payload.get("assessment_version"):
            return None
        job_id = payload.get("counterfactual_job_id")
        revision_ref = projection.get("review_artifact_revision")
        if not isinstance(job_id, str) or not isinstance(revision_ref, dict):
            return None
        review = await session.get(CounterfactualJobRecord, job_id)
        if (
            review is None or review.status != "SUCCEEDED" or review.result_payload is None
            or (review.snapshot_id, review.snapshot_version, review.chain_id)
            != (identity.snapshot_id, identity.snapshot_version, identity.chain_id)
            or revision_ref.get("resource_kind") != "counterfactual_review"
            or revision_ref.get("fingerprint") != review.cache_fingerprint
        ):
            return None
        review_result = payload.get("review_result")
        if not isinstance(review_result, dict):
            return None
        try:
            review_result_fingerprint = _canonical_sha256(review.result_payload)
            if _canonical_sha256(review_result) != review_result_fingerprint:
                return None
        except (TypeError, ValueError):
            return None
        review_identity = analysis_identity_from_review(
            review.identity_payload,
            pipeline_version=str(review.identity_payload.get("engine_version") or ""),
            input_fingerprint=str(review.identity_payload.get("tier1b_artifact_fingerprint") or ""),
        )
        if (
            not review_identity.available or review_identity.identity is None
            or projection.get("review_analysis_identity") != review_identity.identity.to_payload()
            or review_identity.identity.snapshot_id != identity.snapshot_id
            or review_identity.identity.snapshot_version != identity.snapshot_version
            or review_identity.identity.chain_id != identity.chain_id
            or review_identity.identity.topology_version != identity.topology_version
            or review_identity.identity.analysis_config_version != identity.analysis_config_version
            or review_identity.identity.review_config_version != identity.review_config_version
        ):
            return None
        deep_id = payload.get("deep_dive_job_id")
        deep_fingerprint = None
        deep_result_fingerprint = None
        if deep_id is not None:
            deep = await session.get(DeepDiveJobRecord, deep_id)
            if (
                deep is None or deep.status != "SUCCEEDED" or deep.result_payload is None
                or (deep.snapshot_id, deep.snapshot_version, deep.chain_id)
                != (identity.snapshot_id, identity.snapshot_version, identity.chain_id)
                or deep.analysis_config_version != identity.analysis_config_version
                or deep.topology_version != identity.topology_version
            ):
                return None
            deep_fingerprint = deep.cache_fingerprint
            deep_result = payload.get("deep_dive_result")
            if not isinstance(deep_result, dict):
                return None
            try:
                deep_result_fingerprint = _canonical_sha256(deep.result_payload)
                if _canonical_sha256(deep_result) != deep_result_fingerprint:
                    return None
            except (TypeError, ValueError):
                return None
        elif payload.get("deep_dive_result") is not None:
            return None
        fingerprint_payload = {
            "pipeline_version": identity.pipeline_version,
            "config_version": identity.analysis_config_version,
            "review_config_version": identity.review_config_version,
            "snapshot_id": identity.snapshot_id,
            "snapshot_version": identity.snapshot_version,
            "topology_version": identity.topology_version,
            "chain_id": identity.chain_id,
            "deep_dive_job_id": deep_id,
            "deep_dive_cache_fingerprint": deep_fingerprint,
            "counterfactual_job_id": job_id,
            "counterfactual_cache_fingerprint": review.cache_fingerprint,
        }
        if _canonical_sha256(fingerprint_payload) != identity.input_fingerprint:
            return None
        audit_coverage = assessment.get("evidence_coverage", {}).get("audit")
        audit_used = (
            isinstance(audit_coverage, dict) and audit_coverage.get("complete") is True
        ) or (
            isinstance(dimensions, list) and any(
                isinstance(item, dict) and item.get("name") in {"structural_audit", "over_merge"}
                for item in dimensions
            )
        )
        audit_ref = payload.get("audit_artifact_ref")
        audit_id = None
        audit_fingerprint = None
        if audit_ref is None:
            if audit_used:
                return None
        else:
            if not isinstance(audit_ref, dict):
                return None
            audit_id = audit_ref.get("artifact_id")
            audit_fingerprint = audit_ref.get("artifact_fingerprint")
            membership_fingerprint = payload.get("chain_membership_fingerprint")
            if not all(
                isinstance(value, str) and value
                for value in (audit_id, audit_fingerprint, membership_fingerprint)
            ):
                return None
            audit_row = await session.get(AuditArtifactRecord, audit_id)
            if audit_row is None:
                return None
            try:
                audit = audit_artifact_from_dict(audit_row.payload)
            except (AttributeError, KeyError, TypeError, ValueError, IndexError):
                return None
            membership_coverage = assessment["evidence_coverage"].get("membership")
            member_total = (
                membership_coverage.get("total")
                if isinstance(membership_coverage, dict) else None
            )
            if (
                audit_row.artifact_id != audit_id
                or audit_row.artifact_fingerprint != audit_fingerprint
                or audit.artifact_id != audit_id
                or audit.artifact_fingerprint != audit_fingerprint
                or audit_row.artifact_version != audit.artifact_version
                or audit_row.status != "AVAILABLE" or audit_row.mode != "EXACT"
                or audit_row.snapshot_id != identity.snapshot_id
                or audit_row.snapshot_version != identity.snapshot_version
                or audit_row.chain_id != identity.chain_id
                or audit_row.chain_fingerprint != membership_fingerprint
                or audit_row.analysis_version != AUDIT_ANALYSIS_VERSION
                or audit_row.analysis_config_version != identity.analysis_config_version
                or audit.snapshot_id != audit_row.snapshot_id
                or audit.snapshot_version != audit_row.snapshot_version
                or audit.chain_id != audit_row.chain_id
                or audit.chain_fingerprint != audit_row.chain_fingerprint
                or audit.analysis_version != audit_row.analysis_version
                or audit.analysis_config_version != audit_row.analysis_config_version
                or audit.topology_version != identity.topology_version
                or audit.status != audit_row.status or audit.mode != audit_row.mode
                or audit.chain_size != member_total
            ):
                return None
            if audit_used and (
                audit.verdict not in {"NO_LOW_CONDUCTANCE_CUT", "CANDIDATE_SPLIT"}
                or not isinstance(audit_coverage, dict)
                or audit_coverage.get("status") != "EVALUATED"
                or audit_coverage.get("complete") is not True
                or any(
                    item["value"] != (1.0 if audit.verdict == "NO_LOW_CONDUCTANCE_CUT" else 0.0)
                    for item in dimensions if item["name"] == "structural_audit"
                )
            ):
                return None
        source_refs = {
            "quality_input_fingerprint": identity.input_fingerprint,
            "review_job_id": job_id,
            "review_artifact_fingerprint": review.cache_fingerprint,
            "review_result_fingerprint": review_result_fingerprint,
            "tier1b_artifact_fingerprint": review_identity.identity.input_fingerprint,
            "deep_dive_job_id": deep_id,
            "deep_dive_cache_fingerprint": deep_fingerprint,
            "deep_dive_result_fingerprint": deep_result_fingerprint,
            "audit_artifact_id": audit_id,
            "audit_artifact_fingerprint": audit_fingerprint,
        }
        identity_payload = identity.to_payload()
        return {
            "receipt_id": uuid.uuid4().hex,
            "identity_digest": _canonical_sha256(identity_payload),
            "artifact_revision": _receipt_revision(assessment, source_refs),
            "analysis_identity": identity_payload,
            "assessment": assessment,
            "source_artifact_refs": source_refs,
        }

    async def chain_quality_assessment(
        self, *, snapshot_id: str, snapshot_version: str, chain_id: str
    ) -> StoredChainQualityAssessment | None:
        started = time.perf_counter()
        try:
            async with self.sessions() as session:
                row = await session.get(
                    ChainQualityAssessmentRecord,
                    (snapshot_id, snapshot_version, chain_id),
                )
                return self._stored_chain_quality(row) if row is not None else None
        finally:
            _record_db_read("quality-assessment", started)

    async def quality_evaluation_receipt(self, receipt_id: str) -> StoredQualityEvaluationReceipt | None:
        async with self.sessions() as session:
            row = await session.get(QualityEvaluationReceiptRecord, receipt_id)
            return self._stored_quality_receipt(row) if row is not None else None

    async def list_quality_evaluation_receipts(
        self, *, identity_digest: str, limit: int = 50
    ) -> list[StoredQualityEvaluationReceipt]:
        if not 1 <= limit <= 100:
            raise ValueError("receipt limit must be between 1 and 100")
        async with self.sessions() as session:
            rows = (await session.scalars(
                select(QualityEvaluationReceiptRecord)
                .where(QualityEvaluationReceiptRecord.identity_digest == identity_digest)
                .order_by(QualityEvaluationReceiptRecord.created_at.desc(), QualityEvaluationReceiptRecord.receipt_id.desc())
                .limit(limit)
            )).all()
            return [self._stored_quality_receipt(row) for row in rows]

    async def list_chain_quality_assessments(
        self, *, snapshot_id: str | None = None, snapshot_version: str | None = None
    ) -> list[StoredChainQualityAssessment]:
        statement = select(ChainQualityAssessmentRecord)
        if snapshot_id is not None:
            statement = statement.where(
                ChainQualityAssessmentRecord.snapshot_id == snapshot_id
            )
        if snapshot_version is not None:
            statement = statement.where(
                ChainQualityAssessmentRecord.snapshot_version == snapshot_version
            )
        async with self.sessions() as session:
            rows = list((await session.scalars(statement)).all())
        return [self._stored_chain_quality(row) for row in rows]

    async def active_quality_chain_ids(
        self, *, snapshot_id: str, snapshot_version: str
    ) -> set[str]:
        """Return chains with a durable Tier-2 job still in flight.

        A process restart loses the in-memory job managers, but the database
        still contains QUEUED/RUNNING lifecycle rows.  Background quality
        reconciliation uses this set to avoid submitting a duplicate job
        while the original worker still owns it.
        """
        active_statuses = ("QUEUED", "RUNNING")
        async with self.sessions() as session:
            deep_ids = set(
                (
                    await session.scalars(
                        select(DeepDiveJobRecord.chain_id).where(
                            DeepDiveJobRecord.snapshot_id == snapshot_id,
                            DeepDiveJobRecord.snapshot_version == snapshot_version,
                            DeepDiveJobRecord.status.in_(active_statuses),
                        )
                    )
                ).all()
            )
            review_ids = set(
                (
                    await session.scalars(
                        select(CounterfactualJobRecord.chain_id).where(
                            CounterfactualJobRecord.snapshot_id == snapshot_id,
                            CounterfactualJobRecord.snapshot_version == snapshot_version,
                            CounterfactualJobRecord.status.in_(active_statuses),
                        )
                    )
                ).all()
            )
        return {str(chain_id) for chain_id in deep_ids | review_ids}

    async def persist_operator_feedback(
        self, payload: dict[str, Any]
    ) -> StoredOperatorFeedback:
        async with self.sessions() as session:
            statement = (
                pg_insert(OperatorFeedbackRecord)
                .values(
                    feedback_id=payload["feedback_id"],
                    job_id=payload["job_id"],
                    snapshot_id=payload["snapshot_id"],
                    snapshot_version=payload["snapshot_version"],
                    chain_id=payload["chain_id"],
                    candidate_id=payload["candidate_id"],
                    operation=payload["operation"],
                    decision=payload["decision"],
                    operator_id=payload["operator_id"],
                    reason=payload.get("reason"),
                    partition_delta=payload["partition_delta"],
                    mutation_dispatched=payload.get("mutation_dispatched", False),
                    mutation_dispatch_result=payload.get("mutation_dispatch_result"),
                )
                .on_conflict_do_update(
                    index_elements=[OperatorFeedbackRecord.feedback_id],
                    set_={
                        "decision": payload["decision"],
                        "operator_id": payload["operator_id"],
                        "reason": payload.get("reason"),
                        "mutation_dispatched": payload.get("mutation_dispatched", False),
                        "mutation_dispatch_result": payload.get("mutation_dispatch_result"),
                    },
                )
            )
            await session.execute(statement)
            await session.commit()
        stored = await self.get_operator_feedback(payload["feedback_id"])
        if stored is None:
            raise RuntimeError("persisted operator feedback is unavailable")
        return stored

    async def get_operator_feedback(
        self, feedback_id: str
    ) -> StoredOperatorFeedback | None:
        async with self.sessions() as session:
            row = await session.get(OperatorFeedbackRecord, feedback_id)
            return self._stored_feedback(row) if row is not None else None

    async def operator_feedback_for_job(
        self, job_id: str
    ) -> list[StoredOperatorFeedback]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(OperatorFeedbackRecord)
                .where(OperatorFeedbackRecord.job_id == job_id)
                .order_by(OperatorFeedbackRecord.created_at.asc())
            )
            return [self._stored_feedback(row) for row in result.all()]

    async def operator_feedback_for_chain(
        self, chain_id: str
    ) -> list[StoredOperatorFeedback]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(OperatorFeedbackRecord)
                .where(OperatorFeedbackRecord.chain_id == chain_id)
                .order_by(OperatorFeedbackRecord.created_at.asc())
            )
            return [self._stored_feedback(row) for row in result.all()]

    @staticmethod
    def _stored_feedback(
        row: OperatorFeedbackRecord,
    ) -> StoredOperatorFeedback:
        return StoredOperatorFeedback(
            feedback_id=row.feedback_id,
            job_id=row.job_id,
            snapshot_id=row.snapshot_id,
            snapshot_version=row.snapshot_version,
            chain_id=row.chain_id,
            candidate_id=row.candidate_id,
            operation=row.operation,
            decision=row.decision,
            operator_id=row.operator_id,
            reason=row.reason,
            partition_delta=row.partition_delta,
            mutation_dispatched=row.mutation_dispatched,
            mutation_dispatch_result=row.mutation_dispatch_result,
            created_at=row.created_at,
        )

    # -------------------------------------------------------------------------
    # Review Learning Store (Migration 0013, Append-Only & Zero-Mutation)
    # -------------------------------------------------------------------------

    @staticmethod
    def _as_datetime(val: Any) -> datetime:
        if isinstance(val, datetime):
            if val.tzinfo is None:
                return val.replace(tzinfo=timezone.utc)
            return val.astimezone(timezone.utc)
        if isinstance(val, str) and val.strip():
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _make_exposure_id(review_id: str, candidate_id: str) -> str:
        raw = f"exp_{review_id}_{candidate_id}"
        if len(raw) <= 64:
            return raw
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"exp_{digest[:60]}"

    async def persist_succeeded_job_and_review_bundle(
        self,
        job_payload: Mapping[str, Any],
        session: ReviewSession,
        exposures: Sequence[CandidateExposure],
    ) -> None:
        """Atomically persist succeeded counterfactual job and immutable review bundle in a single transaction."""
        from review_learning.contracts import ImmutableReviewConflict

        status_rank = {"QUEUED": 0, "RUNNING": 1, "SUCCEEDED": 2, "FAILED": 2}
        if job_payload["status"] not in status_rank:
            raise ValueError("unknown counterfactual job status")
        if (
            session.job_id,
            session.snapshot_id,
            session.snapshot_version,
            session.chain_id,
        ) != (
            job_payload["job_id"],
            job_payload["snapshot_id"],
            job_payload["snapshot_version"],
            job_payload["chain_id"],
        ):
            raise ValueError("review session identity does not match counterfactual job")

        job_values = {
            "job_id": job_payload["job_id"],
            "snapshot_id": job_payload["snapshot_id"],
            "snapshot_version": job_payload["snapshot_version"],
            "chain_id": job_payload["chain_id"],
            "cache_fingerprint": job_payload["cache_fingerprint"],
            "status": job_payload["status"],
            "progress_percent": job_payload["progress_percent"],
            "cache_hit": job_payload["cache_hit"],
            "identity_payload": job_payload["identity"],
            "result_payload": job_payload.get("result"),
            "error": job_payload.get("error"),
        }

        async with self.sessions.begin() as db_session:
            # 1. Upsert CounterfactualJobRecord
            existing_job = await db_session.get(
                CounterfactualJobRecord, job_payload["job_id"], with_for_update=True
            )
            if existing_job is None:
                inserted_job_id = (await db_session.execute(
                    pg_insert(CounterfactualJobRecord)
                    .values(**job_values)
                    .on_conflict_do_nothing(
                        index_elements=[CounterfactualJobRecord.job_id]
                    )
                    .returning(CounterfactualJobRecord.job_id)
                )).scalar_one_or_none()
                if inserted_job_id is None:
                    # A row inserted after the initial SELECT is serialized by
                    # the unique key; read and verify its committed contents.
                    existing_job = await db_session.get(
                        CounterfactualJobRecord,
                        job_payload["job_id"],
                        with_for_update=True,
                    )
                    if existing_job is None:
                        raise RuntimeError(
                            "counterfactual job conflict without persisted row"
                        )
            if existing_job is not None:
                immutable = (
                    existing_job.snapshot_id,
                    existing_job.snapshot_version,
                    existing_job.chain_id,
                    existing_job.cache_fingerprint,
                    existing_job.identity_payload,
                )
                proposed = (
                    job_values["snapshot_id"],
                    job_values["snapshot_version"],
                    job_values["chain_id"],
                    job_values["cache_fingerprint"],
                    job_values["identity_payload"],
                )
                if immutable != proposed:
                    raise ValueError(
                        f"Job {job_payload['job_id']}: identity attributes are immutable"
                    )
                _assert_succeeded_result_replay(existing_job, job_values, "counterfactual job")
                if existing_job.status != "SUCCEEDED":
                    for key, val in job_values.items():
                        setattr(existing_job, key, val)

            # 2. Persist ReviewSession and CandidateExposureModel rows
            existing_session = await db_session.get(ReviewSessionModel, session.review_id, with_for_update=True)
            if existing_session is None:
                review_values = {
                    "review_id": session.review_id,
                    "job_id": session.job_id,
                    "snapshot_id": session.snapshot_id,
                    "snapshot_version": session.snapshot_version,
                    "chain_id": session.chain_id,
                    "review_time": self._as_datetime(session.review_time),
                    "source_kind": session.source_kind,
                    "lineage_component_id": session.lineage_component_id,
                    "candidate_set_fingerprint": session.candidate_set_fingerprint,
                    "generator_version": session.generator_version,
                    "config_version": session.config_version,
                    "delay_model_version": session.delay_model_version,
                    "retrieval_version": session.retrieval_version,
                    "exposure_policy": session.exposure_policy,
                    "status": session.status,
                    "review_domain": getattr(session, "review_domain", "UNKNOWN_DOMAIN"),
                    "snapshot_observed_at": self._as_datetime(session.snapshot_observed_at) if getattr(session, "snapshot_observed_at", None) else None,
                    "job_completed_at": self._as_datetime(session.job_completed_at) if getattr(session, "job_completed_at", None) else None,
                    "source_alarm_universe_fingerprint": getattr(session, "source_alarm_universe_fingerprint", None),
                    "created_at": self._as_datetime(session.created_at),
                }
                inserted_session_id = (await db_session.execute(
                    pg_insert(ReviewSessionModel)
                    .values(**review_values)
                    .on_conflict_do_nothing(
                        index_elements=[ReviewSessionModel.review_id]
                    )
                    .returning(ReviewSessionModel.review_id)
                )).scalar_one_or_none()
                if inserted_session_id is None:
                    existing_session = await db_session.get(
                        ReviewSessionModel, session.review_id, with_for_update=True
                    )
                    if existing_session is None:
                        raise RuntimeError(
                            "review session conflict without persisted row"
                        )

            if existing_session is not None:
                if (
                    existing_session.job_id != session.job_id
                    or existing_session.candidate_set_fingerprint != session.candidate_set_fingerprint
                    or existing_session.snapshot_id != session.snapshot_id
                    or existing_session.snapshot_version != session.snapshot_version
                    or existing_session.chain_id != session.chain_id
                    or existing_session.lineage_component_id != session.lineage_component_id
                ):
                    raise ImmutableReviewConflict(
                        f"Conflict: persisted review session {session.review_id} already exists with differing fingerprint or snapshot context"
                    )
                existing_exps = list((await db_session.scalars(
                    select(CandidateExposureModel).where(CandidateExposureModel.review_id == session.review_id)
                )).all())
                existing_fps = {exp.candidate_id: exp.candidate_fingerprint for exp in existing_exps}
                new_fps = {exp.candidate_id: exp.candidate_fingerprint for exp in exposures}
                if existing_fps != new_fps:
                    raise ImmutableReviewConflict(
                        f"Conflict: persisted review exposures for session {session.review_id} differ from submitted bundle"
                    )
            else:
                for exp in exposures:
                    exposure_row = CandidateExposureModel(
                        exposure_id=self._make_exposure_id(exp.review_id, exp.candidate_id),
                        review_id=exp.review_id,
                        candidate_id=exp.candidate_id,
                        candidate_fingerprint=exp.candidate_fingerprint,
                        operation=exp.operation,
                        original_rank=exp.original_rank,
                        displayed_rank=exp.displayed_rank,
                        deterministic_eligibility=exp.deterministic_eligibility,
                        hard_gate_status=exp.hard_gate_status,
                        pareto_state=exp.pareto_state,
                        deterministic_context=exp.deterministic_context,
                        case_context=exp.case_context,
                        temporal_context=exp.temporal_context,
                        feature_fingerprint=exp.feature_fingerprint,
                        feature_schema_version=exp.feature_schema_version,
                        feature_payload=exp.feature_payload,
                        created_at=self._as_datetime(exp.created_at),
                    )
                    db_session.add(exposure_row)

    async def persist_review_bundle(
        self,
        session: ReviewSession,
        exposures: Sequence[CandidateExposure],
    ) -> None:
        from review_learning.contracts import ImmutableReviewConflict
        async with self.sessions.begin() as db_session:
            existing = await db_session.get(ReviewSessionModel, session.review_id, with_for_update=True)
            if existing is not None:
                if (
                    existing.candidate_set_fingerprint != session.candidate_set_fingerprint
                    or existing.snapshot_id != session.snapshot_id
                    or existing.snapshot_version != session.snapshot_version
                    or existing.chain_id != session.chain_id
                    or existing.lineage_component_id != session.lineage_component_id
                ):
                    raise ImmutableReviewConflict(
                        f"Conflict: persisted review session {session.review_id} already exists with differing fingerprint or snapshot context"
                    )
                existing_exps = list((await db_session.scalars(
                    select(CandidateExposureModel).where(CandidateExposureModel.review_id == session.review_id)
                )).all())
                existing_fps = {exp.candidate_id: exp.candidate_fingerprint for exp in existing_exps}
                new_fps = {exp.candidate_id: exp.candidate_fingerprint for exp in exposures}
                if existing_fps != new_fps:
                    raise ImmutableReviewConflict(
                        f"Conflict: persisted review exposures for session {session.review_id} differ from submitted bundle"
                    )
                return

            review_row = ReviewSessionModel(
                review_id=session.review_id,
                job_id=session.job_id,
                snapshot_id=session.snapshot_id,
                snapshot_version=session.snapshot_version,
                chain_id=session.chain_id,
                review_time=self._as_datetime(session.review_time),
                source_kind=session.source_kind,
                lineage_component_id=session.lineage_component_id,
                candidate_set_fingerprint=session.candidate_set_fingerprint,
                generator_version=session.generator_version,
                config_version=session.config_version,
                delay_model_version=session.delay_model_version,
                retrieval_version=session.retrieval_version,
                exposure_policy=session.exposure_policy,
                status=session.status,
                review_domain=getattr(session, "review_domain", "UNKNOWN_DOMAIN"),
                snapshot_observed_at=self._as_datetime(session.snapshot_observed_at) if getattr(session, "snapshot_observed_at", None) else None,
                job_completed_at=self._as_datetime(session.job_completed_at) if getattr(session, "job_completed_at", None) else None,
                source_alarm_universe_fingerprint=getattr(session, "source_alarm_universe_fingerprint", None),
                created_at=self._as_datetime(session.created_at),
            )
            db_session.add(review_row)
            await db_session.flush()
            for exp in exposures:
                exposure_row = CandidateExposureModel(
                    exposure_id=self._make_exposure_id(exp.review_id, exp.candidate_id),
                    review_id=exp.review_id,
                    candidate_id=exp.candidate_id,
                    candidate_fingerprint=exp.candidate_fingerprint,
                    operation=exp.operation,
                    original_rank=exp.original_rank,
                    displayed_rank=exp.displayed_rank,
                    deterministic_eligibility=str(exp.deterministic_eligibility) if exp.deterministic_eligibility is not None else "ELIGIBLE",
                    hard_gate_status=exp.hard_gate_status,
                    pareto_state=exp.pareto_state,
                    deterministic_context=exp.deterministic_context,
                    case_context=exp.case_context,
                    temporal_context=exp.temporal_context,
                    feature_fingerprint=exp.feature_fingerprint,
                    feature_schema_version=exp.feature_schema_version,
                    feature_payload=exp.feature_payload,
                    created_at=self._as_datetime(exp.created_at),
                )
                db_session.add(exposure_row)

    async def get_review_session(self, review_id: str) -> ReviewSession | None:
        async with self.sessions() as db_session:
            row = await db_session.get(ReviewSessionModel, review_id)
            return self._stored_review_session(row) if row is not None else None

    async def get_review_session_by_job_id(self, job_id: str) -> ReviewSession | None:
        async with self.sessions() as db_session:
            result = await db_session.scalars(
                select(ReviewSessionModel).where(ReviewSessionModel.job_id == job_id).limit(1)
            )
            row = result.first()
            return self._stored_review_session(row) if row is not None else None

    async def get_candidate_exposures(self, review_id: str) -> list[CandidateExposure]:
        async with self.sessions() as db_session:
            result = await db_session.scalars(
                select(CandidateExposureModel)
                .where(CandidateExposureModel.review_id == review_id)
                .order_by(CandidateExposureModel.displayed_rank.asc())
            )
            return [self._stored_candidate_exposure(row) for row in result.all()]

    async def append_candidate_display_events(
        self, events: Sequence[CandidateDisplayEvent]
    ) -> None:
        if not events:
            return
        async with self.sessions.begin() as db_session:
            for ev in events:
                surf_val = ev.surface.value if hasattr(ev.surface, "value") else str(ev.surface)
                row = CandidateDisplayEventModel(
                    display_event_id=ev.display_event_id,
                    review_id=ev.review_id,
                    candidate_id=ev.candidate_id,
                    displayed_rank=ev.displayed_rank,
                    exposure_policy=ev.exposure_policy,
                    surface=surf_val,
                    rendered_at=self._as_datetime(ev.rendered_at),
                    viewer_session_id=ev.viewer_session_id,
                    client_event_id=ev.client_event_id,
                    created_at=self._as_datetime(ev.created_at),
                )
                db_session.add(row)

    async def append_review_feedback(
        self,
        feedback: ReviewFeedback,
        manual_correction: ManualCorrection | None = None,
        review_case: ReviewCase | None = None,
    ) -> ReviewFeedback:
        async with self.sessions.begin() as db_session:
            session_row = await db_session.get(ReviewSessionModel, feedback.review_id)
            if session_row is None:
                raise ValueError(f"Review session {feedback.review_id} does not exist")

            feedback_row = ReviewFeedbackModel(
                feedback_id=feedback.feedback_id,
                review_id=feedback.review_id,
                candidate_id=feedback.candidate_id,
                reviewer_subject=feedback.reviewer_subject,
                reviewer_role=feedback.reviewer_role,
                domain_scope=list(feedback.domain_scope),
                decision=feedback.decision.value,
                confidence=feedback.confidence,
                reason_policy_version=feedback.reason_policy_version,
                reason_codes=list(feedback.reason_codes),
                reason_text=feedback.reason_text,
                truth_tier=feedback.truth_tier.value,
                supersedes_feedback_id=feedback.supersedes_feedback_id,
                artifact_fingerprints=feedback.artifact_fingerprints,
                created_at=self._as_datetime(feedback.created_at),
            )
            db_session.add(feedback_row)
            await db_session.flush()

            lifecycle_row = FeedbackLifecycleEventModel(
                event_id=f"lc_{feedback.feedback_id}_created",
                feedback_id=feedback.feedback_id,
                event_type=FeedbackLifecycleType.CREATED.value,
                actor_subject=feedback.reviewer_subject,
                superseded_by_id=None,
                reason=None,
                created_at=self._as_datetime(feedback.created_at),
            )
            db_session.add(lifecycle_row)

            if manual_correction is not None:
                mc_row = ManualCorrectionModel(
                    correction_id=manual_correction.correction_id,
                    feedback_id=manual_correction.feedback_id,
                    operation=manual_correction.operation,
                    partition_delta=manual_correction.partition_delta,
                    correction_fingerprint=manual_correction.correction_fingerprint,
                    created_at=self._as_datetime(manual_correction.created_at),
                )
                db_session.add(mc_row)

            if review_case is not None:
                case_row = ReviewCaseModel(
                    case_id=review_case.case_id,
                    review_id=review_case.review_id,
                    feedback_id=review_case.feedback_id,
                    candidate_id=review_case.candidate_id,
                    case_time=self._as_datetime(review_case.case_time),
                    lineage_component_id=review_case.lineage_component_id,
                    operation_pattern=review_case.operation_pattern,
                    fingerprint_schema_version=review_case.fingerprint_schema_version,
                    fingerprint_payload=review_case.fingerprint_payload,
                    fingerprint_hash=review_case.fingerprint_hash,
                    case_domain=getattr(review_case, "case_domain", "UNKNOWN_DOMAIN"),
                    domain_scope=list(review_case.domain_scope) if getattr(review_case, "domain_scope", None) else None,
                    decision=review_case.decision.value,
                    truth_tier=review_case.truth_tier.value,
                    status="ACTIVE",
                    created_at=self._as_datetime(review_case.created_at),
                )
                db_session.add(case_row)

        return feedback

    async def append_superseding_feedback(
        self,
        feedback: ReviewFeedback,
        supersedes_feedback_id: str,
        manual_correction: ManualCorrection | None = None,
        review_case: ReviewCase | None = None,
    ) -> ReviewFeedback:
        from review_learning.contracts import InactiveFeedbackConflict
        async with self.sessions.begin() as db_session:
            old_feedback = await db_session.scalar(
                select(ReviewFeedbackModel)
                .where(ReviewFeedbackModel.feedback_id == supersedes_feedback_id)
                .with_for_update()
            )
            if old_feedback is None:
                raise ValueError(f"Previous feedback {supersedes_feedback_id} does not exist")

            terminal_events = list(
                (
                    await db_session.scalars(
                        select(FeedbackLifecycleEventModel).where(
                            FeedbackLifecycleEventModel.feedback_id == supersedes_feedback_id,
                            FeedbackLifecycleEventModel.event_type.in_([
                                FeedbackLifecycleType.SUPERSEDED.value,
                                FeedbackLifecycleType.RETRACTED.value,
                            ]),
                        )
                    )
                ).all()
            )
            if terminal_events:
                event_types = [e.event_type for e in terminal_events]
                raise InactiveFeedbackConflict(f"Cannot supersede feedback {supersedes_feedback_id} because it is already {event_types}")

            if old_feedback.review_id != feedback.review_id:
                raise ValueError(f"Feedback review_id mismatch: {feedback.review_id} vs {old_feedback.review_id}")

            feedback_row = ReviewFeedbackModel(
                feedback_id=feedback.feedback_id,
                review_id=feedback.review_id,
                candidate_id=feedback.candidate_id,
                reviewer_subject=feedback.reviewer_subject,
                reviewer_role=feedback.reviewer_role,
                domain_scope=list(feedback.domain_scope),
                decision=feedback.decision.value,
                confidence=feedback.confidence,
                reason_policy_version=feedback.reason_policy_version,
                reason_codes=list(feedback.reason_codes),
                reason_text=feedback.reason_text,
                truth_tier=feedback.truth_tier.value,
                supersedes_feedback_id=supersedes_feedback_id,
                artifact_fingerprints=feedback.artifact_fingerprints,
                created_at=self._as_datetime(feedback.created_at),
            )
            db_session.add(feedback_row)
            await db_session.flush()

            lc_superseded = FeedbackLifecycleEventModel(
                event_id=f"lc_{old_feedback.feedback_id}_superseded_{feedback.feedback_id}",
                feedback_id=old_feedback.feedback_id,
                event_type=FeedbackLifecycleType.SUPERSEDED.value,
                actor_subject=feedback.reviewer_subject,
                superseded_by_id=feedback.feedback_id,
                reason=f"Superseded by {feedback.feedback_id}",
                created_at=self._as_datetime(feedback.created_at),
            )
            db_session.add(lc_superseded)

            lc_created = FeedbackLifecycleEventModel(
                event_id=f"lc_{feedback.feedback_id}_created",
                feedback_id=feedback.feedback_id,
                event_type=FeedbackLifecycleType.CREATED.value,
                actor_subject=feedback.reviewer_subject,
                superseded_by_id=None,
                reason=None,
                created_at=self._as_datetime(feedback.created_at),
            )
            db_session.add(lc_created)

            if manual_correction is not None:
                mc_row = ManualCorrectionModel(
                    correction_id=manual_correction.correction_id,
                    feedback_id=manual_correction.feedback_id,
                    operation=manual_correction.operation,
                    partition_delta=manual_correction.partition_delta,
                    correction_fingerprint=manual_correction.correction_fingerprint,
                    created_at=self._as_datetime(manual_correction.created_at),
                )
                db_session.add(mc_row)

            if review_case is not None:
                case_row = ReviewCaseModel(
                    case_id=review_case.case_id,
                    review_id=review_case.review_id,
                    feedback_id=review_case.feedback_id,
                    candidate_id=review_case.candidate_id,
                    case_time=self._as_datetime(review_case.case_time),
                    lineage_component_id=review_case.lineage_component_id,
                    operation_pattern=review_case.operation_pattern,
                    fingerprint_schema_version=review_case.fingerprint_schema_version,
                    fingerprint_payload=review_case.fingerprint_payload,
                    fingerprint_hash=review_case.fingerprint_hash,
                    case_domain=getattr(review_case, "case_domain", "UNKNOWN_DOMAIN"),
                    domain_scope=list(review_case.domain_scope) if getattr(review_case, "domain_scope", None) else None,
                    decision=review_case.decision.value,
                    truth_tier=review_case.truth_tier.value,
                    status="ACTIVE",
                    created_at=self._as_datetime(review_case.created_at),
                )
                db_session.add(case_row)

        return feedback

    async def append_retraction_event(
        self,
        feedback_id: str,
        actor_subject: str,
        expected_review_id: str | None = None,
        reason: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        from review_learning.contracts import ReviewFeedbackNotFound, InactiveFeedbackConflict
        async with self.sessions.begin() as db_session:
            query = select(ReviewFeedbackModel).where(ReviewFeedbackModel.feedback_id == feedback_id)
            if expected_review_id is not None:
                query = query.where(ReviewFeedbackModel.review_id == expected_review_id)
            query = query.with_for_update()
            feedback = await db_session.scalar(query)
            if feedback is None:
                raise ReviewFeedbackNotFound(f"Feedback {feedback_id} not found in review session")

            inactive = await db_session.scalar(
                select(FeedbackLifecycleEventModel.event_id)
                .where(
                    FeedbackLifecycleEventModel.feedback_id == feedback_id,
                    FeedbackLifecycleEventModel.event_type.in_(
                        [FeedbackLifecycleType.SUPERSEDED.value, FeedbackLifecycleType.RETRACTED.value]
                    ),
                )
                .limit(1)
            )
            if inactive is not None:
                raise InactiveFeedbackConflict(f"Feedback {feedback_id} is already inactive (superseded or retracted)")

            event_time = self._as_datetime(created_at) if created_at is not None else datetime.now(timezone.utc)
            lc_retracted = FeedbackLifecycleEventModel(
                event_id=f"lc_{uuid.uuid4().hex[:16]}",
                feedback_id=feedback_id,
                event_type=FeedbackLifecycleType.RETRACTED.value,
                actor_subject=actor_subject,
                superseded_by_id=None,
                reason=reason,
                created_at=event_time,
            )
            db_session.add(lc_retracted)

    async def active_review_feedback_with_sessions(
        self,
        job_id: str | None = None,
        chain_id: str | None = None,
    ) -> list[tuple[ReviewFeedback, ReviewSession]]:
        """Return active feedbacks joined with their parent review sessions in a single query."""
        async with self.sessions() as db_session:
            inactive_subquery = (
                select(FeedbackLifecycleEventModel.feedback_id)
                .where(
                    FeedbackLifecycleEventModel.event_type.in_(
                        [FeedbackLifecycleType.SUPERSEDED.value, FeedbackLifecycleType.RETRACTED.value]
                    )
                )
                .scalar_subquery()
            )

            query = (
                select(ReviewFeedbackModel, ReviewSessionModel)
                .join(ReviewSessionModel, ReviewFeedbackModel.review_id == ReviewSessionModel.review_id)
                .where(ReviewFeedbackModel.feedback_id.not_in(inactive_subquery))
            )
            if job_id is not None:
                query = query.where(ReviewSessionModel.job_id == job_id)
            if chain_id is not None:
                query = query.where(ReviewSessionModel.chain_id == chain_id)
            query = query.order_by(ReviewFeedbackModel.created_at.asc())

            rows = (await db_session.execute(query)).all()
            return [
                {
                    "feedback": self._stored_review_feedback(fb_row),
                    "session": self._stored_review_session(sess_row),
                }
                for fb_row, sess_row in rows
            ]

    async def active_review_feedback(
        self,
        review_id: str | None = None,
        job_id: str | None = None,
        chain_id: str | None = None,
    ) -> list[ReviewFeedback]:
        async with self.sessions() as db_session:
            inactive_subquery = (
                select(FeedbackLifecycleEventModel.feedback_id)
                .where(
                    FeedbackLifecycleEventModel.event_type.in_(
                        [FeedbackLifecycleType.SUPERSEDED.value, FeedbackLifecycleType.RETRACTED.value]
                    )
                )
                .scalar_subquery()
            )

            query = select(ReviewFeedbackModel).where(
                ReviewFeedbackModel.feedback_id.not_in(inactive_subquery)
            )

            if review_id is not None:
                query = query.where(ReviewFeedbackModel.review_id == review_id)
            elif job_id is not None or chain_id is not None:
                query = query.join(ReviewSessionModel, ReviewFeedbackModel.review_id == ReviewSessionModel.review_id)
                if job_id is not None:
                    query = query.where(ReviewSessionModel.job_id == job_id)
                if chain_id is not None:
                    query = query.where(ReviewSessionModel.chain_id == chain_id)

            query = query.order_by(ReviewFeedbackModel.created_at.asc())
            rows = await db_session.scalars(query)
            return [self._stored_review_feedback(r) for r in rows.all()]

    async def active_review_cases_before(
        self, cutoff: datetime
    ) -> list[ReviewCase]:
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        async with self.sessions() as db_session:
            inactive_feedback_subquery = (
                select(FeedbackLifecycleEventModel.feedback_id)
                .where(
                    FeedbackLifecycleEventModel.event_type.in_(
                        [FeedbackLifecycleType.SUPERSEDED.value, FeedbackLifecycleType.RETRACTED.value]
                    ),
                    FeedbackLifecycleEventModel.created_at < cutoff,
                )
                .scalar_subquery()
            )
            query = (
                select(ReviewCaseModel)
                .where(
                    ReviewCaseModel.feedback_id.not_in(inactive_feedback_subquery),
                    ReviewCaseModel.case_time < cutoff,
                )
                .order_by(ReviewCaseModel.case_time.desc())
            )
            rows = await db_session.scalars(query)
            return [self._stored_review_case(r) for r in rows.all()]

    async def training_review_groups_before(
        self, cutoff: datetime
    ) -> list[dict[str, Any]]:
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        async with self.sessions() as db_session:
            inactive_subquery = (
                select(FeedbackLifecycleEventModel.feedback_id)
                .where(
                    FeedbackLifecycleEventModel.event_type.in_(
                        [FeedbackLifecycleType.SUPERSEDED.value, FeedbackLifecycleType.RETRACTED.value]
                    ),
                    FeedbackLifecycleEventModel.created_at < cutoff,
                )
                .scalar_subquery()
            )
            feedback_session_ids_subquery = (
                select(ReviewFeedbackModel.review_id)
                .where(
                    ReviewFeedbackModel.created_at < cutoff,
                    ReviewFeedbackModel.feedback_id.not_in(inactive_subquery),
                )
                .distinct()
                .scalar_subquery()
            )
            sessions = list(
                (
                    await db_session.scalars(
                        select(ReviewSessionModel)
                        .where(ReviewSessionModel.review_id.in_(feedback_session_ids_subquery))
                        .order_by(ReviewSessionModel.review_time.asc())
                    )
                ).all()
            )

            groups: list[dict[str, Any]] = []
            for s in sessions:
                exposures = list(
                    (
                        await db_session.scalars(
                            select(CandidateExposureModel)
                            .where(CandidateExposureModel.review_id == s.review_id)
                            .order_by(CandidateExposureModel.displayed_rank.asc())
                        )
                    ).all()
                )
                displays = list(
                    (
                        await db_session.scalars(
                            select(CandidateDisplayEventModel)
                            .where(CandidateDisplayEventModel.review_id == s.review_id)
                            .order_by(CandidateDisplayEventModel.rendered_at.asc())
                        )
                    ).all()
                )
                feedbacks = list(
                    (
                        await db_session.scalars(
                            select(ReviewFeedbackModel)
                            .where(
                                ReviewFeedbackModel.review_id == s.review_id,
                                ReviewFeedbackModel.created_at < cutoff,
                                ReviewFeedbackModel.feedback_id.not_in(inactive_subquery),
                            )
                            .order_by(ReviewFeedbackModel.created_at.asc())
                        )
                    ).all()
                )
                corrections = list(
                    (
                        await db_session.scalars(
                            select(ManualCorrectionModel)
                            .join(ReviewFeedbackModel, ManualCorrectionModel.feedback_id == ReviewFeedbackModel.feedback_id)
                            .where(
                                ReviewFeedbackModel.review_id == s.review_id,
                                ReviewFeedbackModel.created_at < cutoff,
                                ReviewFeedbackModel.feedback_id.not_in(inactive_subquery),
                            )
                        )
                    ).all()
                )

                corrections_list = [
                    ManualCorrection(
                        correction_id=mc.correction_id,
                        feedback_id=mc.feedback_id,
                        operation=mc.operation,
                        partition_delta=mc.partition_delta,
                        correction_fingerprint=mc.correction_fingerprint,
                        created_at=mc.created_at,
                    )
                    for mc in corrections
                ]
                mc_by_fb = {mc.feedback_id: mc for mc in corrections_list}
                group = {
                    "review_session": self._stored_review_session(s),
                    "candidate_exposures": [self._stored_candidate_exposure(e) for e in exposures],
                    "candidate_display_events": [
                        CandidateDisplayEvent(
                            display_event_id=d.display_event_id,
                            review_id=d.review_id,
                            candidate_id=d.candidate_id,
                            displayed_rank=d.displayed_rank,
                            exposure_policy=d.exposure_policy,
                            surface=d.surface,
                            rendered_at=d.rendered_at,
                            viewer_session_id=d.viewer_session_id,
                            client_event_id=d.client_event_id,
                            created_at=d.created_at,
                        )
                        for d in displays
                    ],
                    "active_feedbacks": [
                        self._stored_review_feedback(f, manual_correction=mc_by_fb.get(f.feedback_id))
                        for f in feedbacks
                    ],
                    "manual_corrections": corrections_list,
                }
                groups.append(group)

            return groups

    @classmethod
    def _stored_review_session(cls, row: ReviewSessionModel) -> ReviewSession:
        return ReviewSession(
            review_id=row.review_id,
            job_id=row.job_id,
            snapshot_id=row.snapshot_id,
            snapshot_version=row.snapshot_version,
            chain_id=row.chain_id,
            review_time=cls._as_datetime(row.review_time),
            source_kind=row.source_kind,
            lineage_component_id=row.lineage_component_id,
            candidate_set_fingerprint=row.candidate_set_fingerprint,
            generator_version=row.generator_version,
            config_version=row.config_version,
            delay_model_version=row.delay_model_version,
            retrieval_version=row.retrieval_version,
            exposure_policy=row.exposure_policy,
            status=row.status,
            review_domain=getattr(row, "review_domain", "IP_NETWORK"),
            snapshot_observed_at=cls._as_datetime(getattr(row, "snapshot_observed_at", None)) if getattr(row, "snapshot_observed_at", None) is not None else None,
            job_completed_at=cls._as_datetime(getattr(row, "job_completed_at", None)) if getattr(row, "job_completed_at", None) is not None else None,
            source_alarm_universe_fingerprint=getattr(row, "source_alarm_universe_fingerprint", None),
            created_at=cls._as_datetime(row.created_at),
        )

    @staticmethod
    def _stored_candidate_exposure(row: CandidateExposureModel) -> CandidateExposure:
        return CandidateExposure(
            review_id=row.review_id,
            candidate_id=row.candidate_id,
            candidate_fingerprint=row.candidate_fingerprint,
            operation=row.operation,
            original_rank=row.original_rank,
            displayed_rank=row.displayed_rank,
            deterministic_eligibility=row.deterministic_eligibility,
            hard_gate_status=row.hard_gate_status,
            pareto_state=row.pareto_state,
            deterministic_context=row.deterministic_context or {},
            case_context=row.case_context or {},
            temporal_context=row.temporal_context or {},
            feature_fingerprint=row.feature_fingerprint,
            feature_schema_version=getattr(row, "feature_schema_version", "cf-features-v1") or "cf-features-v1",
            feature_payload=row.feature_payload or {},
            created_at=row.created_at,
        )

    @staticmethod
    def _stored_review_feedback(
        row: ReviewFeedbackModel,
        manual_correction: ManualCorrection | None = None,
    ) -> ReviewFeedback:
        scopes = tuple(row.domain_scope or [])
        return ReviewFeedback(
            feedback_id=row.feedback_id,
            review_id=row.review_id,
            candidate_id=row.candidate_id,
            reviewer_subject=row.reviewer_subject,
            reviewer_role=row.reviewer_role,
            domain_scope=scopes,
            reviewer_domain_scope=scopes,
            decision=ReviewDecision(row.decision),
            confidence=row.confidence,
            reason_policy_version=row.reason_policy_version,
            reason_codes=tuple(row.reason_codes or []),
            reason_text=row.reason_text,
            truth_tier=TruthTier(row.truth_tier),
            supersedes_feedback_id=row.supersedes_feedback_id,
            artifact_fingerprints=row.artifact_fingerprints or {},
            manual_correction=manual_correction,
            created_at=row.created_at,
        )

    @staticmethod
    def _stored_review_case(row: ReviewCaseModel) -> ReviewCase:
        return ReviewCase(
            case_id=row.case_id,
            review_id=row.review_id,
            feedback_id=row.feedback_id,
            candidate_id=row.candidate_id,
            case_time=row.case_time,
            lineage_component_id=row.lineage_component_id or "",
            operation_pattern=row.operation_pattern,
            fingerprint_schema_version=row.fingerprint_schema_version,
            fingerprint_payload=row.fingerprint_payload or {},
            fingerprint_hash=row.fingerprint_hash,
            case_domain=getattr(row, "case_domain", "IP_NETWORK"),
            domain_scope=tuple(getattr(row, "domain_scope", None) or []),
            decision=ReviewDecision(row.decision),
            truth_tier=TruthTier(row.truth_tier),
            status=row.status,
            created_at=row.created_at,
        )

    @staticmethod
    def _stored_counterfactual(
        row: CounterfactualJobRecord,
    ) -> StoredCounterfactualJob:
        return StoredCounterfactualJob(
            job_id=row.job_id,
            snapshot_id=row.snapshot_id,
            snapshot_version=row.snapshot_version,
            chain_id=row.chain_id,
            cache_fingerprint=row.cache_fingerprint,
            status=row.status,
            progress_percent=row.progress_percent,
            cache_hit=row.cache_hit,
            identity=row.identity_payload,
            result=row.result_payload,
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _stored_deep_dive(row: DeepDiveJobRecord) -> StoredDeepDiveJob:
        return StoredDeepDiveJob(
            job_id=row.job_id,
            snapshot_id=row.snapshot_id,
            snapshot_version=row.snapshot_version,
            chain_id=row.chain_id,
            cache_fingerprint=row.cache_fingerprint,
            analysis_config_version=row.analysis_config_version,
            topology_version=row.topology_version,
            status=row.status,
            progress_percent=row.progress_percent,
            cache_hit=row.cache_hit,
            result=row.result_payload,
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _stored_chain_quality(
        row: ChainQualityAssessmentRecord,
    ) -> StoredChainQualityAssessment:
        return StoredChainQualityAssessment(
            snapshot_id=row.snapshot_id,
            snapshot_version=row.snapshot_version,
            chain_id=row.chain_id,
            assessment_version=row.assessment_version,
            input_fingerprint=row.input_fingerprint,
            status=row.status,
            stars=row.stars,
            label=row.label,
            available_dimension_count=row.available_dimension_count,
            stage=row.stage,
            deep_dive_job_id=row.deep_dive_job_id,
            counterfactual_job_id=row.counterfactual_job_id,
            recommendation_status=row.recommendation_status,
            payload=row.payload,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _stored_quality_receipt(row: QualityEvaluationReceiptRecord) -> StoredQualityEvaluationReceipt:
        return StoredQualityEvaluationReceipt(
            receipt_id=row.receipt_id,
            identity_digest=row.identity_digest,
            artifact_revision=row.artifact_revision,
            analysis_identity=row.analysis_identity,
            assessment=row.assessment,
            source_artifact_refs=row.source_artifact_refs,
            created_at=row.created_at,
        )

    async def record_kafka_event(
        self,
        event: SnapshotWireEvent,
        *,
        topic: str,
        partition: int,
        offset: int,
    ) -> IngestResult:
        async with self.sessions.begin() as session:
            seen = await session.scalar(
                select(KafkaInbox).where(
                    KafkaInbox.topic == topic,
                    KafkaInbox.partition == partition,
                    KafkaInbox.offset == offset,
                )
            )
            if seen is not None:
                # Kafka offsets are unique only for the lifetime of one log.
                # The Docker broker is intentionally ephemeral, while the
                # PostgreSQL inbox is durable, so a recreated broker can reuse
                # topic/partition/offset for a different snapshot.  Do not
                # short-circuit here: the snapshot/chunk natural keys below
                # provide the payload-aware idempotence check.  Retarget a
                # reused coordinate to the event currently present in Kafka.
                if (
                    seen.snapshot_id != event.snapshot_id
                    or seen.snapshot_version != event.snapshot_version
                    or seen.event_type != event.event_type
                ):
                    seen.snapshot_id = event.snapshot_id
                    seen.snapshot_version = event.snapshot_version
                    seen.event_type = event.event_type

            row = await session.get(
                SnapshotIngest,
                (event.snapshot_id, event.snapshot_version),
                with_for_update=True,
            )
            if row is None:
                row = SnapshotIngest(
                    snapshot_id=event.snapshot_id,
                    snapshot_version=event.snapshot_version,
                    status="RECEIVING",
                )
                session.add(row)
                await session.flush()

            if seen is None:
                session.add(
                    KafkaInbox(
                        topic=topic,
                        partition=partition,
                        offset=offset,
                        snapshot_id=event.snapshot_id,
                        snapshot_version=event.snapshot_version,
                        event_type=event.event_type,
                    )
                )
            if row.status in {"INVALID", "EXPIRED"}:
                return self._result(row)
            if row.status == "COMPLETE":
                duplicate = await self._verify_completed_event(session, row, event)
                return self._result(row, duplicate=duplicate)

            if isinstance(event, SnapshotChunkEvent):
                duplicate = await self._record_chunk(session, row, event)
            else:
                duplicate = self._record_barrier(row, event)

            if row.status == "INVALID":
                return self._result(row, duplicate=duplicate)
            payload = await self._try_complete(session, row)
            if payload is not None:
                await append_change_if_enabled(
                    session,
                    event_type="snapshot.changed",
                    snapshot_id=row.snapshot_id,
                    snapshot_version=row.snapshot_version,
                    topology_version=row.topology_version_ref,
                    invalidates=["catalog", "chain-list", "quality-summary", "evolution"],
                )
            return self._result(
                row,
                duplicate=duplicate,
                completed_now=payload is not None,
                canonical_payload=payload,
            )

    async def _verify_completed_event(self, session, row, event) -> bool:
        if isinstance(event, SnapshotCompleteEvent):
            expected = {
                "expected_chunk_count": event.expected_chunk_count,
                "snapshot_checksum": event.snapshot_checksum,
                "total_uncompressed_bytes": event.total_uncompressed_bytes,
                "produced_at": event.produced_at,
                "source": event.source,
                "source_kind": event.source_kind,
            }
            if all(getattr(row, name) == value for name, value in expected.items()):
                return True
            self._invalidate(row, "conflicting replay of completed barrier")
            return False

        existing = await session.get(
            SnapshotChunk,
            (event.snapshot_id, event.snapshot_version, event.chunk_index),
        )
        if existing is not None and (
            existing.checksum == event.chunk_checksum
            and existing.payload_bytes == event.payload
            and existing.chunk_count == event.chunk_count
            and existing.snapshot_checksum == event.snapshot_checksum
        ):
            return True
        self._invalidate(row, f"conflicting replay of completed chunk {event.chunk_index}")
        return False

    async def _record_chunk(self, session, row, event: SnapshotChunkEvent) -> bool:
        if row.expected_chunk_count not in (None, event.chunk_count):
            self._invalidate(row, "conflicting chunk_count")
            return False
        if row.snapshot_checksum not in (None, event.snapshot_checksum):
            self._invalidate(row, "conflicting snapshot checksum")
            return False
        row.expected_chunk_count = event.chunk_count
        row.snapshot_checksum = event.snapshot_checksum

        existing = await session.get(
            SnapshotChunk,
            (event.snapshot_id, event.snapshot_version, event.chunk_index),
        )
        if existing is not None:
            if (
                existing.checksum == event.chunk_checksum
                and existing.payload_bytes == event.payload
            ):
                return True
            self._invalidate(row, f"conflicting duplicate chunk {event.chunk_index}")
            return False

        retained_bytes = int(
            await session.scalar(
                select(
                    func.coalesce(
                        func.sum(func.octet_length(SnapshotChunk.payload_bytes)), 0
                    )
                ).where(
                    SnapshotChunk.snapshot_id == event.snapshot_id,
                    SnapshotChunk.snapshot_version == event.snapshot_version,
                )
            )
            or 0
        )
        if retained_bytes + len(event.payload) > self.max_compressed_snapshot_bytes:
            self._invalidate(row, "compressed snapshot exceeds configured limit")
            return False

        session.add(
            SnapshotChunk(
                snapshot_id=event.snapshot_id,
                snapshot_version=event.snapshot_version,
                chunk_index=event.chunk_index,
                chunk_count=event.chunk_count,
                checksum=event.chunk_checksum,
                snapshot_checksum=event.snapshot_checksum,
                payload_bytes=event.payload,
            )
        )
        await session.flush()
        row.received_chunk_count = int(
            await session.scalar(
                select(func.count(SnapshotChunk.chunk_index)).where(
                    SnapshotChunk.snapshot_id == event.snapshot_id,
                    SnapshotChunk.snapshot_version == event.snapshot_version,
                )
            )
            or 0
        )
        return False

    def _record_barrier(
        self, row: SnapshotIngest, event: SnapshotCompleteEvent
    ) -> bool:
        fields = (
            ("expected_chunk_count", event.expected_chunk_count),
            ("snapshot_checksum", event.snapshot_checksum),
            ("total_uncompressed_bytes", event.total_uncompressed_bytes),
            ("produced_at", event.produced_at),
            ("source", event.source),
            ("source_kind", event.source_kind),
        )
        duplicate = all(getattr(row, name) == value for name, value in fields)
        for name, value in fields:
            current = getattr(row, name)
            if current is not None and current != value:
                self._invalidate(row, f"conflicting barrier field {name}")
                return False
            setattr(row, name, value)
        return duplicate

    async def _try_complete(
        self, session, row: SnapshotIngest
    ) -> dict[str, Any] | None:
        if (
            row.produced_at is None
            or row.expected_chunk_count is None
            or row.received_chunk_count != row.expected_chunk_count
        ):
            return None
        chunks = list(
            (
                await session.scalars(
                    select(SnapshotChunk)
                    .where(
                        SnapshotChunk.snapshot_id == row.snapshot_id,
                        SnapshotChunk.snapshot_version == row.snapshot_version,
                    )
                    .order_by(SnapshotChunk.chunk_index)
                )
            ).all()
        )
        if [chunk.chunk_index for chunk in chunks] != list(
            range(row.expected_chunk_count)
        ):
            return None
        try:
            compressed_stream = io.BytesIO(
                b"".join(chunk.payload_bytes for chunk in chunks)
            )
            with zstandard.ZstdDecompressor().stream_reader(compressed_stream) as reader:
                canonical = reader.read((row.total_uncompressed_bytes or 0) + 1)
        except (zstandard.ZstdError, OSError) as exc:
            self._invalidate(row, f"zstd decompression failed: {exc}")
            return None
        if len(canonical) != row.total_uncompressed_bytes:
            self._invalidate(row, "uncompressed size mismatch")
            return None
        checksum = hashlib.sha256(canonical).hexdigest()
        if checksum != row.snapshot_checksum:
            self._invalidate(row, "whole snapshot checksum mismatch")
            return None
        try:
            payload = json.loads(canonical)
            package = load_validated_package(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._invalidate(row, f"canonical contract validation failed: {exc}")
            return None
        if (
            package.snapshot.snapshot_id != row.snapshot_id
            or package.snapshot.snapshot_version != row.snapshot_version
        ):
            self._invalidate(row, "envelope identity does not match canonical snapshot")
            return None
        if not package.snapshot.is_complete:
            self._invalidate(row, "canonical snapshot status is not COMPLETE")
            return None

        await self._persist_canonical(session, package, payload, checksum)
        row.canonical_payload = payload
        row.logical_snapshot_time = _logical_time(package.snapshot.snapshot_time)
        row.status = "COMPLETE"

        topo_ref = package.snapshot.topology_ref
        if topo_ref is not None:
            if isinstance(topo_ref, dict):
                topo_profile_id = topo_ref.get("profile_id")
                topo_version = topo_ref.get("topology_version")
            else:
                topo_profile_id = topo_ref.profile_id
                topo_version = topo_ref.topology_version
            row.topology_profile_id = topo_profile_id
            row.topology_version_ref = topo_version
            topo_ready = await session.scalar(
                select(1).select_from(TopologyVersionRecord).where(
                    TopologyVersionRecord.profile_id == topo_profile_id,
                    TopologyVersionRecord.topology_version == topo_version,
                    TopologyVersionRecord.status == "READY",
                )
            )
            row.tier1a_status = "PENDING" if topo_ready else "PENDING_TOPOLOGY"
        else:
            row.tier1a_status = "PENDING"

        row.completed_at = func.now()
        return payload

    async def ingest_direct(self, payload: dict[str, Any]) -> IngestResult:
        package = load_validated_package(payload)
        if not package.snapshot.is_complete:
            raise ValueError("Direct Snapshot ingest requires status COMPLETE")
        canonical = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        checksum = hashlib.sha256(canonical).hexdigest()
        identity = (package.snapshot.snapshot_id, package.snapshot.snapshot_version)
        async with self.sessions.begin() as session:
            row = await session.get(SnapshotIngest, identity, with_for_update=True)
            if row is not None:
                if row.status == "COMPLETE" and row.canonical_payload == payload:
                    return self._result(row, duplicate=True)
                raise ValueError("snapshot identity already exists with different content")
            topo_ref = package.snapshot.topology_ref
            topo_profile_id = None
            topo_version_ref = None
            tier1a_status = "PENDING"
            if topo_ref is not None:
                topo_profile_id = topo_ref.profile_id
                topo_version_ref = topo_ref.topology_version
                topo_ready = await session.scalar(
                    select(1).select_from(TopologyVersionRecord).where(
                        TopologyVersionRecord.profile_id == topo_ref.profile_id,
                        TopologyVersionRecord.topology_version == topo_ref.topology_version,
                        TopologyVersionRecord.status == "READY",
                    )
                )
                tier1a_status = "PENDING" if topo_ready else "PENDING_TOPOLOGY"

            row = SnapshotIngest(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                status="COMPLETE",
                expected_chunk_count=0,
                received_chunk_count=0,
                snapshot_checksum=checksum,
                total_uncompressed_bytes=len(canonical),
                produced_at=package.snapshot.produced_at,
                source=package.snapshot.source,
                source_kind=package.snapshot.source_kind,
                canonical_payload=payload,
                logical_snapshot_time=_logical_time(package.snapshot.snapshot_time),
                tier1a_status=tier1a_status,
                topology_profile_id=topo_profile_id,
                topology_version_ref=topo_version_ref,
                completed_at=func.now(),
            )
            session.add(row)
            await self._persist_canonical(session, package, payload, checksum)
            await append_change_if_enabled(
                session,
                event_type="snapshot.changed",
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                topology_version=topo_version_ref,
                invalidates=["catalog", "chain-list", "quality-summary", "evolution"],
            )
            return self._result(row, completed_now=True, canonical_payload=payload)

    async def _persist_canonical(
        self,
        session,
        package: IngestedPackage,
        payload: dict[str, Any],
        checksum: str,
    ) -> None:
        identity = (package.snapshot.snapshot_id, package.snapshot.snapshot_version)
        existing = await session.get(Snapshot, identity)
        if existing is not None:
            if existing.raw_payload != payload:
                raise ValueError("canonical snapshot identity conflict")
            return
        session.add(
            Snapshot(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                snapshot_time=package.snapshot.snapshot_time,
                status=package.snapshot.status,
                source=package.snapshot.source,
                source_kind=package.snapshot.source_kind,
                produced_at=package.snapshot.produced_at,
                config_version=package.snapshot.config_version,
                topology_version=package.snapshot.topology_version,
                raw_payload=payload,
                payload_checksum=checksum,
            )
        )
        # These models intentionally avoid ORM relationships.  Flush each FK
        # layer explicitly so SQLAlchemy does not need relationship metadata to
        # infer parent-before-child ordering.
        await session.flush()
        session.add_all(
            Alarm(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                alarm_id=alarm.alarm_id,
                alarm_name=alarm.alarm_name,
                device_code=alarm.device_code,
                node_reference=alarm.node_reference,
                severity_name=alarm.severity_name,
                canonical_start_time=alarm.canonical_start_time,
                canonical_end_time=alarm.canonical_end_time,
                quality_flags=list(alarm.quality_flags),
                raw=alarm.raw,
            )
            for alarm in package.alarms.values()
        )
        session.add_all(
            Chain(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                chain_id=chain.chain_id,
                member_count=chain.member_count,
                chain_name=chain.chain_name,
                event_span_seconds=chain.event_span_seconds,
            )
            for chain in package.chains.values()
        )
        await session.flush()
        session.add_all(
            Membership(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                chain_id=chain_id,
                alarm_id=alarm_id,
            )
            for chain_id, alarms in package.memberships.items()
            for alarm_id in alarms
        )

    async def claim_next_tier1a(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int = 5,
        now: datetime | None = None,
    ) -> Tier1AClaim | None:
        """Claim the oldest logical pending/stale job without blocking peers."""
        current = now or datetime.now(timezone.utc)
        lease_until = current + timedelta(seconds=lease_seconds)
        async with self.sessions.begin() as session:
            while True:
                row = await session.scalar(
                    select(SnapshotIngest)
                    .where(
                        SnapshotIngest.status == "COMPLETE",
                        or_(
                            SnapshotIngest.tier1a_status == "PENDING",
                            (
                                (SnapshotIngest.tier1a_status == "RUNNING")
                                & or_(
                                    SnapshotIngest.lease_expires_at.is_(None),
                                    SnapshotIngest.lease_expires_at <= current,
                                )
                            ),
                        ),
                    )
                    .order_by(
                        SnapshotIngest.logical_snapshot_time.asc().nulls_last(),
                        SnapshotIngest.completed_at.asc().nulls_last(),
                        SnapshotIngest.snapshot_id.asc(),
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if row is None or row.canonical_payload is None:
                    return None
                if row.next_attempt_at is not None and row.next_attempt_at > current:
                    return None
                if row.attempt_count >= max_attempts:
                    row.tier1a_status = "FAILED"
                    row.worker_id = None
                    row.lease_expires_at = None
                    row.heartbeat_at = None
                    row.next_attempt_at = None
                    await session.flush()
                    continue
                break
            row.tier1a_status = "RUNNING"
            row.worker_id = worker_id
            row.lease_expires_at = lease_until
            row.started_at = current
            row.heartbeat_at = current
            row.next_attempt_at = None
            row.attempt_count += 1
            await session.flush()
            return Tier1AClaim(
                snapshot_id=row.snapshot_id,
                snapshot_version=row.snapshot_version,
                payload=row.canonical_payload,
                worker_id=worker_id,
                attempt_count=row.attempt_count,
            )

    async def heartbeat_tier1a(
        self,
        snapshot_id: str,
        snapshot_version: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == snapshot_id,
                    SnapshotIngest.snapshot_version == snapshot_version,
                    SnapshotIngest.tier1a_status == "RUNNING",
                    SnapshotIngest.worker_id == worker_id,
                )
                .values(
                    heartbeat_at=current,
                    lease_expires_at=current + timedelta(seconds=lease_seconds),
                )
            )
            return bool(result.rowcount)

    async def latest_ready_payload(self) -> dict[str, Any] | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(SnapshotIngest.canonical_payload)
                .where(
                    SnapshotIngest.status == "COMPLETE",
                    SnapshotIngest.tier1a_status == "READY",
                )
                .order_by(
                    SnapshotIngest.logical_snapshot_time.desc().nulls_last(),
                    SnapshotIngest.completed_at.desc().nulls_last(),
                    SnapshotIngest.snapshot_id.desc(),
                )
                .limit(1)
            )

    async def get_ready_snapshot_payload(
        self, snapshot_id: str, snapshot_version: str | None = None
    ) -> dict[str, Any] | None:
        async with self.sessions() as session:
            statement = select(SnapshotIngest.canonical_payload).where(
                SnapshotIngest.snapshot_id == snapshot_id,
                SnapshotIngest.tier1a_status == "READY",
            )
            if snapshot_version is not None:
                statement = statement.where(
                    SnapshotIngest.snapshot_version == snapshot_version
                )
            else:
                statement = statement.order_by(SnapshotIngest.snapshot_version.desc())
            return await session.scalar(
                statement
                .limit(1)
            )

    async def finish_tier1a(
        self,
        snapshot_id: str,
        snapshot_version: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        worker_id: str | None = None,
        delete_chunks_after_ready: bool = False,
    ) -> int:
        async with self.sessions.begin() as session:
            statement = select(SnapshotIngest).where(
                SnapshotIngest.snapshot_id == snapshot_id,
                SnapshotIngest.snapshot_version == snapshot_version,
                SnapshotIngest.tier1a_status == "RUNNING",
            )
            if worker_id is not None:
                statement = statement.where(SnapshotIngest.worker_id == worker_id)
            row = await session.scalar(statement.with_for_update())
            if row is None:
                return 0
            row.tier1a_status = "FAILED" if error else "READY"
            row.tier1a_result = result if error is None else {"error": error}
            row.worker_id = None
            row.lease_expires_at = None
            row.heartbeat_at = None
            row.next_attempt_at = None
            row.lineage_status = "PENDING" if error is None else None
            if not delete_chunks_after_ready:
                return 0
            return await self._delete_chunks_if_cleanup_eligible(session, row)

    async def claim_next_lineage(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> LineageClaim | None:
        current = now or datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(SnapshotIngest)
                .where(
                    SnapshotIngest.tier1a_status == "READY",
                    or_(
                        SnapshotIngest.lineage_status == "PENDING",
                        (
                            (SnapshotIngest.lineage_status == "RUNNING")
                            & or_(
                                SnapshotIngest.lease_expires_at.is_(None),
                                SnapshotIngest.lease_expires_at <= current,
                            )
                        ),
                    ),
                )
                .order_by(
                    SnapshotIngest.logical_snapshot_time.asc().nulls_last(),
                    SnapshotIngest.completed_at.asc().nulls_last(),
                    SnapshotIngest.snapshot_id.asc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None or row.canonical_payload is None:
                return None
            previous = await session.scalar(
                select(SnapshotIngest)
                .where(
                    SnapshotIngest.tier1a_status == "READY",
                    tuple_(
                        SnapshotIngest.logical_snapshot_time,
                        SnapshotIngest.completed_at,
                        SnapshotIngest.snapshot_id,
                    )
                    < tuple_(
                        row.logical_snapshot_time,
                        row.completed_at,
                        row.snapshot_id,
                    ),
                )
                .order_by(
                    SnapshotIngest.logical_snapshot_time.desc(),
                    SnapshotIngest.completed_at.desc(),
                    SnapshotIngest.snapshot_id.desc(),
                )
                .limit(1)
            )
            row.lineage_status = "RUNNING"
            row.worker_id = worker_id
            row.heartbeat_at = current
            row.lease_expires_at = current + timedelta(seconds=lease_seconds)
            return LineageClaim(
                snapshot_id=row.snapshot_id,
                snapshot_version=row.snapshot_version,
                payload=row.canonical_payload,
                previous_payload=previous.canonical_payload if previous else None,
                previous_lineage_status=previous.lineage_status if previous else None,
                worker_id=worker_id,
            )

    async def load_episode_dag(self) -> GlobalEpisodeDag:
        async with self.sessions() as session:
            component_rows = list((await session.scalars(select(LineageComponent))).all())
            node_rows = list((await session.scalars(select(LineageNode))).all())
            edge_rows = list((await session.scalars(select(LineageEdge))).all())
        components = {
            row.component_id: DomainLineageComponent(
                component_id=row.component_id,
                canonical_component_id=row.canonical_component_id,
                first_snapshot_time=row.first_snapshot_time.isoformat(),
                last_snapshot_time=row.last_snapshot_time.isoformat(),
                status=row.status,
            )
            for row in component_rows
        }
        nodes = {}
        for row in node_rows:
            key = LineageNodeKey(
                row.snapshot_id, row.snapshot_version, row.snapshot_chain_id
            )
            nodes[key] = DomainLineageNode(
                key=key,
                snapshot_time=row.snapshot_time.isoformat(),
                component_id=row.component_id,
                branch_id=row.branch_id,
            )
        edges = {}
        for row in edge_rows:
            parent = LineageNodeKey(
                row.parent_snapshot_id,
                row.parent_snapshot_version,
                row.parent_chain_id,
            )
            child = LineageNodeKey(
                row.child_snapshot_id,
                row.child_snapshot_version,
                row.child_chain_id,
            )
            edges[(parent, child)] = DomainLineageEdge(
                parent=parent,
                child=child,
                edge_type=row.edge_type,
                overlap_count=row.overlap_count,
                contain_parent=row.contain_parent,
                contain_child=row.contain_child,
            )
        return GlobalEpisodeDag(nodes=nodes, edges=edges, components=components)

    async def finish_lineage(
        self,
        claim: LineageClaim,
        dag: GlobalEpisodeDag,
    ) -> None:
        async with self.sessions.begin() as session:
            for component in dag.components.values():
                statement = pg_insert(LineageComponent).values(
                    component_id=component.component_id,
                    canonical_component_id=component.canonical_component_id,
                    first_snapshot_time=_logical_time(component.first_snapshot_time),
                    last_snapshot_time=_logical_time(component.last_snapshot_time),
                    status=component.status,
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[LineageComponent.component_id],
                        set_={
                            "canonical_component_id": statement.excluded.canonical_component_id,
                            "first_snapshot_time": statement.excluded.first_snapshot_time,
                            "last_snapshot_time": statement.excluded.last_snapshot_time,
                            "status": statement.excluded.status,
                        },
                    )
                )
            for node in dag.nodes.values():
                statement = pg_insert(LineageNode).values(
                    snapshot_id=node.key.snapshot_id,
                    snapshot_version=node.key.snapshot_version,
                    snapshot_chain_id=node.key.snapshot_chain_id,
                    snapshot_time=_logical_time(node.snapshot_time),
                    component_id=node.component_id,
                    branch_id=node.branch_id,
                )
                await session.execute(statement.on_conflict_do_nothing())
            for edge in dag.edges.values():
                statement = pg_insert(LineageEdge).values(
                    parent_snapshot_id=edge.parent.snapshot_id,
                    parent_snapshot_version=edge.parent.snapshot_version,
                    parent_chain_id=edge.parent.snapshot_chain_id,
                    child_snapshot_id=edge.child.snapshot_id,
                    child_snapshot_version=edge.child.snapshot_version,
                    child_chain_id=edge.child.snapshot_chain_id,
                    edge_type=edge.edge_type,
                    overlap_count=edge.overlap_count,
                    contain_parent=edge.contain_parent,
                    contain_child=edge.contain_child,
                )
                await session.execute(statement.on_conflict_do_nothing())
            result = await session.execute(
                update(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == claim.snapshot_id,
                    SnapshotIngest.snapshot_version == claim.snapshot_version,
                    SnapshotIngest.lineage_status == "RUNNING",
                    SnapshotIngest.worker_id == claim.worker_id,
                )
                .values(
                    lineage_status="READY",
                    lineage_result={"node_count": len(dag.nodes), "edge_count": len(dag.edges)},
                    similarity_status="PENDING",
                    worker_id=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                )
            )
            if not result.rowcount:
                raise RuntimeError("lineage lease ownership was lost")

    async def mark_lineage_unavailable(self, claim: LineageClaim, reason: str) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == claim.snapshot_id,
                    SnapshotIngest.snapshot_version == claim.snapshot_version,
                    SnapshotIngest.worker_id == claim.worker_id,
                )
                .values(
                    lineage_status="UNAVAILABLE",
                    lineage_result={"reason": reason},
                    similarity_status="UNAVAILABLE",
                    worker_id=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                )
            )

    async def release_lineage(self, claim: LineageClaim, reason: str) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == claim.snapshot_id,
                    SnapshotIngest.snapshot_version == claim.snapshot_version,
                    SnapshotIngest.lineage_status == "RUNNING",
                    SnapshotIngest.worker_id == claim.worker_id,
                )
                .values(
                    lineage_status="PENDING",
                    lineage_result={"last_error": reason},
                    worker_id=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                )
            )

    async def claim_next_similarity(
        self, *, worker_id: str, lease_seconds: int, now: datetime | None = None
    ) -> SimilarityClaim | None:
        current = now or datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(SnapshotIngest)
                .where(
                    SnapshotIngest.lineage_status == "READY",
                    or_(
                        SnapshotIngest.similarity_status == "PENDING",
                        (
                            (SnapshotIngest.similarity_status == "RUNNING")
                            & or_(
                                SnapshotIngest.lease_expires_at.is_(None),
                                SnapshotIngest.lease_expires_at <= current,
                            )
                        ),
                    ),
                )
                .order_by(
                    SnapshotIngest.logical_snapshot_time.asc(),
                    SnapshotIngest.completed_at.asc(),
                    SnapshotIngest.snapshot_id.asc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None or row.canonical_payload is None:
                return None
            row.similarity_status = "RUNNING"
            row.worker_id = worker_id
            row.heartbeat_at = current
            row.lease_expires_at = current + timedelta(seconds=lease_seconds)
            return SimilarityClaim(
                row.snapshot_id, row.snapshot_version, row.canonical_payload, worker_id
            )

    async def load_similarity_history(
        self, *, cutoff: datetime, dag: GlobalEpisodeDag
    ) -> list[TimedChainFingerprint]:
        async with self.sessions() as session:
            rows = list(
                (
                    await session.scalars(
                        select(SimilarityFingerprint)
                        .where(SimilarityFingerprint.event_time < cutoff)
                        .order_by(
                            SimilarityFingerprint.event_time,
                            SimilarityFingerprint.snapshot_id,
                            SimilarityFingerprint.snapshot_chain_id,
                        )
                    )
                ).all()
            )
        history = []
        for row in rows:
            canonical = dag.canonical_lineage(
                LineageNodeKey(
                    row.snapshot_id, row.snapshot_version, row.snapshot_chain_id
                )
            )
            if canonical is None:
                raise RuntimeError("historical fingerprint has no canonical lineage")
            fingerprint = replace(
                fingerprint_from_dict(row.fingerprint_payload),
                lineage_component_id=canonical,
                scored_with_model_version=None,
            )
            history.append(
                TimedChainFingerprint(
                    fingerprint,
                    row.event_time.isoformat(),
                    row.snapshot_id,
                    row.snapshot_version,
                )
            )
        return history

    async def load_historical_packages(self, *, cutoff: datetime) -> list[IngestedPackage]:
        """Load the verified logical prefix used to build one immutable H model."""
        async with self.sessions() as session:
            payloads = list(
                (
                    await session.scalars(
                        select(SnapshotIngest.canonical_payload)
                        .where(
                            SnapshotIngest.tier1a_status == "READY",
                            SnapshotIngest.lineage_status == "READY",
                            SnapshotIngest.logical_snapshot_time < cutoff,
                        )
                        .order_by(
                            SnapshotIngest.logical_snapshot_time,
                            SnapshotIngest.completed_at,
                            SnapshotIngest.snapshot_id,
                            SnapshotIngest.snapshot_version,
                        )
                    )
                ).all()
            )
        return [load_validated_package(payload) for payload in payloads if payload is not None]

    async def finish_similarity(
        self,
        claim: SimilarityClaim,
        index: VersionedSimilarityIndex,
        current_fingerprints: list[TimedChainFingerprint],
    ) -> None:
        async with self.sessions.begin() as session:
            model_statement = pg_insert(SimilarityModelRecord).values(
                model_version=index.model.model_version,
                snapshot_id=claim.snapshot_id,
                snapshot_version=claim.snapshot_version,
                trained_until_exclusive=_logical_time(
                    index.model.trained_until_exclusive
                ),
                model_payload=model_to_dict(index.model),
            )
            await session.execute(model_statement.on_conflict_do_nothing())
            for entry in current_fingerprints:
                statement = pg_insert(SimilarityFingerprint).values(
                    snapshot_id=claim.snapshot_id,
                    snapshot_version=claim.snapshot_version,
                    snapshot_chain_id=entry.fingerprint.chain_id.rsplit("::", 1)[-1],
                    event_time=_logical_time(entry.event_time),
                    component_id=entry.fingerprint.lineage_component_id,
                    fingerprint_payload=fingerprint_to_dict(entry.fingerprint),
                )
                await session.execute(statement.on_conflict_do_nothing())
            for entry in index.entries:
                statement = pg_insert(SimilarityIndexEntry).values(
                    model_version=index.model.model_version,
                    snapshot_id=entry.snapshot_id,
                    snapshot_version=entry.snapshot_version,
                    snapshot_chain_id=entry.fingerprint.chain_id.rsplit("::", 1)[-1],
                    event_time=_logical_time(entry.event_time),
                    fingerprint_payload=fingerprint_to_dict(entry.fingerprint),
                )
                await session.execute(statement.on_conflict_do_nothing())
            result = await session.execute(
                update(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == claim.snapshot_id,
                    SnapshotIngest.snapshot_version == claim.snapshot_version,
                    SnapshotIngest.similarity_status == "RUNNING",
                    SnapshotIngest.worker_id == claim.worker_id,
                )
                .values(
                    similarity_status="READY",
                    worker_id=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                )
            )
            if not result.rowcount:
                raise RuntimeError("similarity lease ownership was lost")

    async def load_similarity_index(
        self, snapshot_id: str, snapshot_version: str
    ) -> VersionedSimilarityIndex | None:
        async with self.sessions() as session:
            model_row = await session.scalar(
                select(SimilarityModelRecord).where(
                    SimilarityModelRecord.snapshot_id == snapshot_id,
                    SimilarityModelRecord.snapshot_version == snapshot_version,
                )
            )
            if model_row is None:
                return None
            entry_rows = list(
                (
                    await session.scalars(
                        select(SimilarityIndexEntry)
                        .where(
                            SimilarityIndexEntry.model_version
                            == model_row.model_version
                        )
                        .order_by(
                            SimilarityIndexEntry.event_time,
                            SimilarityIndexEntry.snapshot_id,
                            SimilarityIndexEntry.snapshot_chain_id,
                        )
                    )
                ).all()
            )
        model = model_from_dict(model_row.model_payload)
        entries = tuple(
            TimedChainFingerprint(
                fingerprint_from_dict(row.fingerprint_payload),
                row.event_time.isoformat(),
                row.snapshot_id,
                row.snapshot_version,
            )
            for row in entry_rows
        )
        return VersionedSimilarityIndex(model=model, entries=entries)

    async def persist_historical_evidence_model(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        model: HistoricalEvidenceModel,
        taxonomy: HistoricalTaxonomy,
    ) -> None:
        """Insert one frozen H model; never mutate an existing snapshot model."""
        if (taxonomy.source_id, taxonomy.source_version) != (
            model.taxonomy_source_id,
            model.taxonomy_source_version,
        ):
            raise ValueError("historical taxonomy does not match model provenance")
        statement = pg_insert(HistoricalEvidenceModelRecord).values(
            model_version=model.model_version,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            training_cutoff=_logical_time(model.training_cutoff),
            model_payload=historical_model_to_dict(model),
            taxonomy_payload=historical_taxonomy_to_dict(taxonomy),
        )
        async with self.sessions.begin() as session:
            await session.execute(statement.on_conflict_do_nothing())

    async def load_historical_evidence_model(
        self, snapshot_id: str, snapshot_version: str
    ) -> tuple[HistoricalEvidenceModel, HistoricalTaxonomy] | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(HistoricalEvidenceModelRecord).where(
                    HistoricalEvidenceModelRecord.snapshot_id == snapshot_id,
                    HistoricalEvidenceModelRecord.snapshot_version == snapshot_version,
                )
            )
        if row is None:
            return None
        model = historical_model_from_dict(row.model_payload)
        taxonomy = historical_taxonomy_from_dict(row.taxonomy_payload)
        if (model.taxonomy_source_id, model.taxonomy_source_version) != (
            taxonomy.source_id,
            taxonomy.source_version,
        ):
            raise RuntimeError("persisted historical model/taxonomy provenance mismatch")
        return model, taxonomy

    async def persist_temporal_delay_model(
        self, *, snapshot_id: str, snapshot_version: str, model: FrozenDelayModel,
        taxonomy: HistoricalTaxonomy,
    ) -> None:
        if (model.taxonomy_source_id, model.taxonomy_source_version) != (taxonomy.source_id, taxonomy.source_version):
            raise ValueError("temporal delay taxonomy does not match model provenance")
        statement = pg_insert(TemporalDelayModelRecord).values(
            model_version=model.model_version, snapshot_id=snapshot_id, snapshot_version=snapshot_version,
            training_cutoff=_logical_time(model.training_cutoff), model_payload=delay_model_to_dict(model),
            taxonomy_payload=historical_taxonomy_to_dict(taxonomy),
        )
        async with self.sessions.begin() as session:
            await session.execute(statement.on_conflict_do_nothing())

    async def load_temporal_delay_model(
        self, snapshot_id: str, snapshot_version: str
    ) -> tuple[FrozenDelayModel, HistoricalTaxonomy] | None:
        async with self.sessions() as session:
            rows = (await session.scalars(
                select(TemporalDelayModelRecord)
                .where(
                    TemporalDelayModelRecord.snapshot_id == snapshot_id,
                    TemporalDelayModelRecord.snapshot_version == snapshot_version,
                )
                .order_by(TemporalDelayModelRecord.created_at.desc(), TemporalDelayModelRecord.model_version.desc())
            )).all()
        for row in rows:
            model = delay_model_from_dict(row.model_payload)
            if model.implementation_version != CURRENT_DELAY_MODEL_IMPLEMENTATION_VERSION:
                continue
            taxonomy = historical_taxonomy_from_dict(row.taxonomy_payload)
            if (model.taxonomy_source_id, model.taxonomy_source_version) != (taxonomy.source_id, taxonomy.source_version):
                raise RuntimeError("persisted temporal delay model/taxonomy provenance mismatch")
            return model, taxonomy
        return None

    async def canonical_lineages(
        self, snapshot_id: str, snapshot_version: str
    ) -> dict[str, str]:
        dag = await self.load_episode_dag()
        return {
            key.snapshot_chain_id: canonical
            for key in dag.nodes
            if key.snapshot_id == snapshot_id
            and key.snapshot_version == snapshot_version
            and (canonical := dag.canonical_lineage(key)) is not None
        }

    async def release_similarity(self, claim: SimilarityClaim, reason: str) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == claim.snapshot_id,
                    SnapshotIngest.snapshot_version == claim.snapshot_version,
                    SnapshotIngest.similarity_status == "RUNNING",
                    SnapshotIngest.worker_id == claim.worker_id,
                )
                .values(
                    similarity_status="PENDING",
                    lineage_result={"similarity_last_error": reason},
                    worker_id=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                )
            )

    async def record_tier1a_failure(
        self,
        snapshot_id: str,
        snapshot_version: str,
        *,
        error: str,
        worker_id: str,
        max_attempts: int,
        backoff_base_seconds: int,
        now: datetime | None = None,
    ) -> str | None:
        """Back off a failed claim or make it terminal after max attempts."""
        current = now or datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == snapshot_id,
                    SnapshotIngest.snapshot_version == snapshot_version,
                    SnapshotIngest.tier1a_status == "RUNNING",
                    SnapshotIngest.worker_id == worker_id,
                )
                .with_for_update()
            )
            if row is None:
                return None
            terminal = row.attempt_count >= max_attempts
            row.tier1a_status = "FAILED" if terminal else "PENDING"
            row.tier1a_result = {
                "last_error": error,
                "attempt_count": row.attempt_count,
            }
            row.worker_id = None
            row.lease_expires_at = None
            row.heartbeat_at = None
            row.next_attempt_at = (
                None
                if terminal
                else current
                + timedelta(
                    seconds=backoff_base_seconds * (2 ** (row.attempt_count - 1))
                )
            )
            return row.tier1a_status

    async def invalidate(
        self, snapshot_id: str, snapshot_version: str, reason: str
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(
                SnapshotIngest,
                (snapshot_id, snapshot_version),
                with_for_update=True,
            )
            if row is None:
                row = SnapshotIngest(
                    snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version,
                    status="INVALID",
                    invalid_reason=reason,
                )
                session.add(row)
            elif row.status != "COMPLETE":
                self._invalidate(row, reason)

    async def cleanup_chunks(self, snapshot_id: str, snapshot_version: str) -> int:
        """Delete only chunks whose canonical snapshot has reached Tier-1A READY.

        The operation is idempotent and cannot remove chunks from receiving,
        invalid, or merely COMPLETE snapshots.
        """
        async with self.sessions.begin() as session:
            row = await session.get(
                SnapshotIngest,
                (snapshot_id, snapshot_version),
                with_for_update=True,
            )
            if row is None:
                return 0
            return await self._delete_chunks_if_cleanup_eligible(session, row)

    @staticmethod
    async def _delete_chunks_if_cleanup_eligible(session, row: SnapshotIngest) -> int:
        if not (
            row.status == "COMPLETE"
            and row.canonical_payload is not None
            and row.tier1a_status == "READY"
        ):
            return 0
        result = await session.execute(
            delete(SnapshotChunk).where(
                SnapshotChunk.snapshot_id == row.snapshot_id,
                SnapshotChunk.snapshot_version == row.snapshot_version,
            )
        )
        return int(result.rowcount or 0)

    async def expire_receiving(
        self,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> int:
        """Expire incomplete assemblies and release their retained payload bytes."""
        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(seconds=ttl_seconds)
        async with self.sessions.begin() as session:
            rows = list(
                (
                    await session.scalars(
                        select(SnapshotIngest)
                        .where(
                            SnapshotIngest.status == "RECEIVING",
                            SnapshotIngest.updated_at < cutoff,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for row in rows:
                row.status = "EXPIRED"
                row.invalid_reason = "snapshot assembly exceeded receiving TTL"
                row.tier1a_status = None
                await session.execute(
                    delete(SnapshotChunk).where(
                        SnapshotChunk.snapshot_id == row.snapshot_id,
                        SnapshotChunk.snapshot_version == row.snapshot_version,
                    )
                )
                row.received_chunk_count = 0
            return len(rows)

    @staticmethod
    def _invalidate(row: SnapshotIngest, reason: str) -> None:
        row.status = "INVALID"
        row.invalid_reason = reason
        row.tier1a_status = None

    @staticmethod
    def _result(
        row: SnapshotIngest | None,
        *,
        duplicate: bool = False,
        completed_now: bool = False,
        canonical_payload: dict[str, Any] | None = None,
    ) -> IngestResult:
        if row is None:
            raise RuntimeError("snapshot ingest row is unavailable")
        return IngestResult(
            snapshot_id=row.snapshot_id,
            snapshot_version=row.snapshot_version,
            status=row.status,
            duplicate=duplicate,
            completed_now=completed_now,
            invalid_reason=row.invalid_reason,
            canonical_payload=canonical_payload,
        )

    async def list_live_snapshots(
        self, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return metadata for all tier1a-READY snapshots ingested via Kafka or direct ingest.

        Used by the catalog API to surface live snapshots alongside hardcoded presets.
        Returns list of dicts with keys: snapshot_id, snapshot_version, alarm_count,
        chain_count, source_kind, completed_at, topology_profile_id.
        """
        async with self.sessions() as session:
            stmt = (
                select(SnapshotIngest)
                .where(SnapshotIngest.tier1a_status == "READY")
                .order_by(
                    SnapshotIngest.completed_at.desc().nullslast(),
                    SnapshotIngest.snapshot_id,
                    SnapshotIngest.snapshot_version,
                )
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.scalars(stmt)).all()

        results = []
        for row in rows:
            payload = row.canonical_payload or {}
            # Extract counts from canonical payload (standard IngestedPackage structure)
            alarm_count = payload.get("alarm_count") or len(payload.get("alarms", []))
            chain_count = payload.get("chain_count") or len(payload.get("chains", []))
            results.append({
                "snapshot_id": row.snapshot_id,
                "snapshot_version": row.snapshot_version,
                "alarm_count": alarm_count,
                "chain_count": chain_count,
                "source_kind": row.source_kind,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "topology_profile_id": row.topology_profile_id,
            })
        return results

    async def interrupt_orphaned_analysis_jobs(self) -> tuple[int, int]:
        """Close lifecycle rows whose in-process executors vanished on restart."""
        async with self.sessions.begin() as session:
            deep_result = await session.execute(
                update(DeepDiveJobRecord)
                .where(DeepDiveJobRecord.status.in_(("QUEUED", "RUNNING")))
                .values(
                    status="INTERRUPTED",
                    progress_percent=100,
                    error="API_RESTART_INTERRUPTED",
                    updated_at=func.now(),
                )
            )
            review_result = await session.execute(
                update(CounterfactualJobRecord)
                .where(CounterfactualJobRecord.status.in_(("QUEUED", "RUNNING")))
                .values(
                    status="INTERRUPTED",
                    progress_percent=100,
                    error="API_RESTART_INTERRUPTED",
                    updated_at=func.now(),
                )
            )
        return int(deep_result.rowcount or 0), int(review_result.rowcount or 0)

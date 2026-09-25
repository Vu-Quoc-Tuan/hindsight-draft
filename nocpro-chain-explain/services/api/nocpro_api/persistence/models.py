from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


class Base(DeclarativeBase):
    pass


class ChangeEventClockModel(Base):
    """Transactional serialization point for ordered invalidation events."""

    __tablename__ = "change_event_clock"

    singleton_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    epoch: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_change_event_clock_singleton"),
        CheckConstraint("revision >= 0", name="ck_change_event_clock_revision"),
    )


class ChangeEventModel(Base):
    """Small, durable invalidation records; never stores business payloads."""

    __tablename__ = "change_events"

    epoch: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(Text)
    snapshot_version: Mapped[str | None] = mapped_column(Text)
    chain_id: Mapped[str | None] = mapped_column(Text)
    topology_version: Mapped[str | None] = mapped_column(Text)
    identity_digest: Mapped[str | None] = mapped_column(String(64))
    invalidates: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        Index("ix_change_events_created_at", "created_at"),
        CheckConstraint("revision > 0", name="ck_change_events_revision"),
    )


class SnapshotIngest(Base):
    __tablename__ = "snapshot_ingest"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVING")
    expected_chunk_count: Mapped[int | None]
    received_chunk_count: Mapped[int] = mapped_column(nullable=False, default=0)
    snapshot_checksum: Mapped[str | None] = mapped_column(String(64))
    total_uncompressed_bytes: Mapped[int | None] = mapped_column(BigInteger)
    produced_at: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str | None] = mapped_column(String(64))
    invalid_reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    logical_snapshot_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canonical_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tier1a_status: Mapped[str | None] = mapped_column(String(32))
    tier1a_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    lineage_status: Mapped[str | None] = mapped_column(String(32))
    lineage_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    similarity_status: Mapped[str | None] = mapped_column(String(32))
    topology_profile_id: Mapped[str | None] = mapped_column(String(64))
    topology_version_ref: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SnapshotChunk(Base):
    __tablename__ = "snapshot_chunks"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    chunk_index: Mapped[int] = mapped_column(primary_key=True)
    chunk_count: Mapped[int] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version"],
            ["snapshot_ingest.snapshot_id", "snapshot_ingest.snapshot_version"],
            ondelete="CASCADE",
        ),
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_time: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    produced_at: Mapped[str] = mapped_column(Text, nullable=False)
    config_version: Mapped[str | None] = mapped_column(Text)
    topology_version: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_checksum: Mapped[str] = mapped_column(String(64), nullable=False)


class Alarm(Base):
    __tablename__ = "alarms"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    alarm_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    alarm_name: Mapped[str | None] = mapped_column(Text)
    device_code: Mapped[str | None] = mapped_column(Text)
    node_reference: Mapped[str | None] = mapped_column(Text)
    severity_name: Mapped[str | None] = mapped_column(Text)
    canonical_start_time: Mapped[str | None] = mapped_column(Text)
    canonical_end_time: Mapped[str | None] = mapped_column(Text)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version"],
            ["snapshots.snapshot_id", "snapshots.snapshot_version"],
            ondelete="CASCADE",
        ),
    )


class Chain(Base):
    __tablename__ = "chains"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    member_count: Mapped[int] = mapped_column(nullable=False)
    chain_name: Mapped[str | None] = mapped_column(Text)
    event_span_seconds: Mapped[int | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version"],
            ["snapshots.snapshot_id", "snapshots.snapshot_version"],
            ondelete="CASCADE",
        ),
    )


class Membership(Base):
    __tablename__ = "memberships"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    alarm_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version", "chain_id"],
            ["chains.snapshot_id", "chains.snapshot_version", "chains.chain_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version", "alarm_id"],
            ["alarms.snapshot_id", "alarms.snapshot_version", "alarms.alarm_id"],
            ondelete="CASCADE",
        ),
    )


class KafkaInbox(Base):
    __tablename__ = "kafka_inbox"
    __table_args__ = (UniqueConstraint("topic", "partition", "offset"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    partition: Mapped[int] = mapped_column(nullable=False)
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(String(255))
    snapshot_version: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LineageNode(Base):
    __tablename__ = "lineage_node"
    __table_args__ = (
        ForeignKeyConstraint(
            ["component_id"], ["lineage_component.component_id"]
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    component_id: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_id: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LineageEdge(Base):
    __tablename__ = "lineage_edge"
    __table_args__ = (
        Index("ix_lineage_edge_child_key", "child_snapshot_id", "child_snapshot_version", "child_chain_id"),
        ForeignKeyConstraint(
            ["parent_snapshot_id", "parent_snapshot_version", "parent_chain_id"],
            [
                "lineage_node.snapshot_id",
                "lineage_node.snapshot_version",
                "lineage_node.snapshot_chain_id",
            ],
        ),
        ForeignKeyConstraint(
            ["child_snapshot_id", "child_snapshot_version", "child_chain_id"],
            [
                "lineage_node.snapshot_id",
                "lineage_node.snapshot_version",
                "lineage_node.snapshot_chain_id",
            ],
        ),
    )

    parent_snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    parent_snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    parent_chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    child_snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    child_snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    child_chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False)
    overlap_count: Mapped[int] = mapped_column(nullable=False)
    contain_parent: Mapped[float] = mapped_column(nullable=False)
    contain_child: Mapped[float] = mapped_column(nullable=False)


class LineageComponent(Base):
    __tablename__ = "lineage_component"

    component_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    canonical_component_id: Mapped[str] = mapped_column(String(64), nullable=False)
    first_snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class SimilarityFingerprint(Base):
    __tablename__ = "similarity_fingerprint"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version", "snapshot_chain_id"],
            [
                "lineage_node.snapshot_id",
                "lineage_node.snapshot_version",
                "lineage_node.snapshot_chain_id",
            ],
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    component_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class SimilarityModelRecord(Base):
    __tablename__ = "similarity_model"
    __table_args__ = (UniqueConstraint("snapshot_id", "snapshot_version"),)

    model_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(255), nullable=False)
    trained_until_exclusive: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    model_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SimilarityIndexEntry(Base):
    __tablename__ = "similarity_index_entry"
    __table_args__ = (
        ForeignKeyConstraint(
            ["model_version"],
            ["similarity_model.model_version"],
            ondelete="CASCADE",
        ),
    )

    model_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fingerprint_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class HistoricalEvidenceModelRecord(Base):
    """Immutable H model plus the exact taxonomy snapshot used to resolve it."""

    __tablename__ = "historical_evidence_model"
    __table_args__ = (UniqueConstraint("snapshot_id", "snapshot_version"),)

    model_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(255), nullable=False)
    training_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    taxonomy_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TemporalDelayModelRecord(Base):
    __tablename__ = "temporal_delay_model"

    model_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(255), nullable=False)
    training_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    taxonomy_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuditArtifactRecord(Base):
    __tablename__ = "audit_artifact"
    __table_args__ = (
        Index(
            "ix_audit_artifact_compatibility",
            "snapshot_id",
            "snapshot_version",
            "chain_id",
            "chain_fingerprint",
            "analysis_version",
            "analysis_config_version",
        ),
    )

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(255), nullable=False)
    chain_id: Mapped[str] = mapped_column(String(255), nullable=False)
    chain_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_config_version: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DeepDiveJobRecord(Base):
    __tablename__ = "deep_dive_job"
    __table_args__ = (
        Index(
            "ix_deep_dive_job_compatibility",
            "snapshot_id",
            "snapshot_version",
            "chain_id",
            "cache_fingerprint",
            "updated_at",
        ),
    )

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(255), nullable=False)
    chain_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cache_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_config_version: Mapped[str | None] = mapped_column(Text)
    topology_version: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress_percent: Mapped[int] = mapped_column(nullable=False)
    cache_hit: Mapped[bool] = mapped_column(nullable=False, default=False)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CounterfactualJobRecord(Base):
    __tablename__ = "counterfactual_job"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(255), nullable=False)
    chain_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cache_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress_percent: Mapped[int] = mapped_column(nullable=False)
    cache_hit: Mapped[bool] = mapped_column(nullable=False, default=False)
    identity_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChainQualityAssessmentRecord(Base):
    """Provider-independent quality result for one exact snapshot chain."""

    __tablename__ = "chain_quality_assessment"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    assessment_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stars: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    available_dimension_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    deep_dive_job_id: Mapped[str | None] = mapped_column(String(64))
    counterfactual_job_id: Mapped[str | None] = mapped_column(String(64))
    recommendation_status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_chain_quality_assessment_snapshot",
            "snapshot_id",
            "snapshot_version",
            "status",
        ),
        Index("ix_chain_quality_assessment_input", "input_fingerprint"),
    )


class QualityEvaluationReceiptRecord(Base):
    """Immutable evidence for one exact quality materialization revision."""

    __tablename__ = "quality_evaluation_receipts"

    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_identity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_artifact_refs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("identity_digest", "artifact_revision", name="uq_quality_receipt_identity_revision"),
        Index("ix_quality_receipts_identity_created", "identity_digest", "created_at"),
        Index(
            "ix_quality_receipts_analysis_identity_gin",
            "analysis_identity",
            postgresql_using="gin",
            postgresql_ops={"analysis_identity": "jsonb_path_ops"},
        ),
    )


class OperatorFeedbackRecord(Base):
    __tablename__ = "operator_feedback"
    __table_args__ = (
        Index("ix_operator_feedback_job_id", "job_id"),
        Index("ix_operator_feedback_chain_id", "chain_id"),
    )

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(255), nullable=False)
    chain_id: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    partition_delta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    mutation_dispatched: Mapped[bool] = mapped_column(nullable=False, default=False)
    mutation_dispatch_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TopologyIngest(Base):
    __tablename__ = "topology_ingest"

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topology_version: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVING")
    total_chunks: Mapped[int | None]
    received_chunks: Mapped[int] = mapped_column(nullable=False, default=0)
    payload_checksum: Mapped[str | None] = mapped_column(String(64))
    invalid_reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TopologyChunk(Base):
    __tablename__ = "topology_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_ingest.profile_id", "topology_ingest.topology_version"],
            ondelete="CASCADE",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topology_version: Mapped[str] = mapped_column(String(128), primary_key=True)
    chunk_index: Mapped[int] = mapped_column(primary_key=True)
    chunk_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_compressed: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TopologyKafkaInbox(Base):
    __tablename__ = "topology_kafka_inbox"

    topic: Mapped[str] = mapped_column(String(128), primary_key=True)
    partition: Mapped[int] = mapped_column(primary_key=True)
    offset: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_key: Mapped[str | None] = mapped_column(String(256))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TopologyVersionRecord(Base):
    __tablename__ = "topology_versions"

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topology_version: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVING")
    relation_model: Mapped[str] = mapped_column(String(64), nullable=False)
    direction_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    dependency_semantics: Mapped[str] = mapped_column(String(64), nullable=False)
    navigation_eligible: Mapped[bool] = mapped_column(nullable=False, default=True)
    p2_eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    node_count: Mapped[int] = mapped_column(nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(nullable=False, default=0)
    alias_count: Mapped[int] = mapped_column(nullable=False, default=0)
    payload_checksum: Mapped[str | None] = mapped_column(String(64))
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TopologyActiveVersionRecord(Base):
    __tablename__ = "topology_active_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_versions.profile_id", "topology_versions.topology_version"],
            ondelete="CASCADE",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topology_version: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TopologyNodeRecord(Base):
    __tablename__ = "topology_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_versions.profile_id", "topology_versions.topology_version"],
            ondelete="CASCADE",
        ),
        Index("ix_topology_nodes_search", "profile_id", "topology_version", "display_name"),
    )

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topology_version: Mapped[str] = mapped_column(String(128), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_tables: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class TopologyEdgeRecord(Base):
    __tablename__ = "topology_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_versions.profile_id", "topology_versions.topology_version"],
            ondelete="CASCADE",
        ),
        Index("ix_topology_edges_source", "profile_id", "topology_version", "source_id"),
        Index("ix_topology_edges_target", "profile_id", "topology_version", "target_id"),
        UniqueConstraint(
            "profile_id",
            "topology_version",
            "source_id",
            "target_id",
            "relation_type",
            name="uq_topology_edges_natural",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topology_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    target_id: Mapped[str] = mapped_column(String(256), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction_kind: Mapped[str | None] = mapped_column(String(64))
    dependency_semantics: Mapped[str | None] = mapped_column(String(64))
    source_table: Mapped[str | None] = mapped_column(String(128))
    source_version: Mapped[str | None] = mapped_column(String(128))


class TopologyAliasResolutionRecord(Base):
    __tablename__ = "topology_alias_resolution"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_versions.profile_id", "topology_versions.topology_version"],
            ondelete="CASCADE",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topology_version: Mapped[str] = mapped_column(String(128), primary_key=True)
    alias_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    unique_resource_id: Mapped[str | None] = mapped_column(String(256))
    verified_by: Mapped[str | None] = mapped_column(String(128))


class AlarmEntityResolutionRecord(Base):
    __tablename__ = "alarm_entity_resolutions"
    __table_args__ = (
        Index("ix_alarm_entity_resolutions_alarm_id", "alarm_id"),
        Index("ix_alarm_entity_resolutions_topo_ver", "profile_id", "topology_version"),
    )

    resolution_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    alarm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topology_version: Mapped[str] = mapped_column(String(128), nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(32), default="v1")
    entity_role: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_value: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    source_field: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    candidate_resource_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    matched_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class ReviewSessionModel(Base):
    __tablename__ = "review_session"
    __table_args__ = (
        Index("ix_review_session_job_id", "job_id"),
        Index("ix_review_session_chain_id", "chain_id"),
        Index("ix_review_session_review_time", "review_time"),
    )

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(255), nullable=False)
    chain_id: Mapped[str] = mapped_column(String(255), nullable=False)
    review_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_component_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    candidate_set_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(128), nullable=False)
    config_version: Mapped[str] = mapped_column(String(128), nullable=False)
    delay_model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retrieval_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exposure_policy: Mapped[str] = mapped_column(String(64), nullable=False, default="ALL_EVALUATED")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETED")
    review_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_alarm_universe_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CandidateExposureModel(Base):
    __tablename__ = "candidate_exposure"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id"],
            ["review_session.review_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_candidate_exposure_review_id", "review_id"),
        Index("ix_candidate_exposure_candidate_id", "candidate_id"),
        Index("ix_candidate_exposure_fingerprint", "candidate_fingerprint"),
        UniqueConstraint("review_id", "candidate_id", name="uq_candidate_exposure_review_candidate"),
    )

    exposure_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    original_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    displayed_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    deterministic_eligibility: Mapped[str] = mapped_column(String(64), nullable=False)
    hard_gate_status: Mapped[str] = mapped_column(String(32), nullable=False)
    pareto_state: Mapped[str] = mapped_column(String(64), nullable=False)
    deterministic_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    case_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    temporal_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    feature_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="cf-features-v1")
    feature_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CandidateDisplayEventModel(Base):
    __tablename__ = "candidate_display_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id", "candidate_id"],
            ["candidate_exposure.review_id", "candidate_exposure.candidate_id"],
            ondelete="RESTRICT",
            name="fk_display_event_candidate_exposure",
        ),
        Index("ix_candidate_display_review_candidate", "review_id", "candidate_id"),
        Index("ix_candidate_display_client_event_id", "client_event_id"),
        UniqueConstraint("review_id", "client_event_id", name="uq_display_event_review_client_event"),
    )

    display_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    displayed_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    exposure_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    surface: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    viewer_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewFeedbackModel(Base):
    __tablename__ = "review_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id"],
            ["review_session.review_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_feedback_id"],
            ["review_feedback.feedback_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["review_id", "candidate_id"],
            ["candidate_exposure.review_id", "candidate_exposure.candidate_id"],
            ondelete="RESTRICT",
            name="fk_feedback_candidate_exposure",
        ),
        Index("ix_review_feedback_review_id", "review_id"),
        Index("ix_review_feedback_candidate_id", "candidate_id"),
        Index("ix_review_feedback_reviewer_subject", "reviewer_subject"),
        Index("ix_review_feedback_decision", "decision"),
    )

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_scope: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    truth_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_feedback_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_fingerprints: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FeedbackLifecycleEventModel(Base):
    __tablename__ = "feedback_lifecycle_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["feedback_id"],
            ["review_feedback.feedback_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["superseded_by_id"],
            ["review_feedback.feedback_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_feedback_lifecycle_feedback_id", "feedback_id"),
        Index("ix_feedback_lifecycle_event_type", "event_type"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    feedback_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ManualCorrectionModel(Base):
    __tablename__ = "manual_correction"
    __table_args__ = (
        ForeignKeyConstraint(
            ["feedback_id"],
            ["review_feedback.feedback_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_manual_correction_feedback_id", "feedback_id"),
    )

    correction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    feedback_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    partition_delta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correction_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewCaseModel(Base):
    __tablename__ = "review_case"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id"],
            ["review_session.review_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["feedback_id"],
            ["review_feedback.feedback_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_review_case_fingerprint_hash", "fingerprint_hash"),
        Index("ix_review_case_decision", "decision"),
        Index("ix_review_case_review_id", "review_id"),
        Index("ix_review_case_feedback_id", "feedback_id"),
        Index("ix_review_case_status", "status"),
        Index("ix_review_case_case_domain", "case_domain"),
    )

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False)
    feedback_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    case_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lineage_component_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_pattern: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    case_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_scope: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    truth_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CohesionNarrativeCache(Base):
    __tablename__ = "cohesion_narrative_cache"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    chain_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    language: Mapped[str] = mapped_column(String(16), primary_key=True, default="en")
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    has_p2: Mapped[bool] = mapped_column(nullable=False, default=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    analytical_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="deterministic")
    provider_status: Mapped[str] = mapped_column(String(64), nullable=False, default="GROUNDED_DETERMINISTIC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_cohesion_narrative_cache_chain", "snapshot_id", "chain_id"),
        Index("ix_cohesion_narrative_cache_input", "input_fingerprint"),
    )


class TopologySubgraphCache(Base):
    __tablename__ = "topology_subgraph_cache"

    cache_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topology_version: Mapped[str] = mapped_column(String(128), nullable=False)
    subgraph_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_topology_subgraph_cache_profile", "profile_id", "topology_version"),
    )

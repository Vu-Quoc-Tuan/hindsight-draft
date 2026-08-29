from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
    canonical_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tier1a_status: Mapped[str | None] = mapped_column(String(32))
    tier1a_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
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

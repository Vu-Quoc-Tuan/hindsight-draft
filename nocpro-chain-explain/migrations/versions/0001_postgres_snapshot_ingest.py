"""PostgreSQL snapshot ingest, canonical data and Kafka inbox.

Revision ID: 0001
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot_ingest",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_version", sa.String(255), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expected_chunk_count", sa.Integer()),
        sa.Column("received_chunk_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_checksum", sa.String(64)),
        sa.Column("total_uncompressed_bytes", sa.BigInteger()),
        sa.Column("produced_at", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("source_kind", sa.String(64)),
        sa.Column("invalid_reason", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("canonical_payload", postgresql.JSONB()),
        sa.Column("tier1a_status", sa.String(32)),
        sa.Column("tier1a_result", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "snapshot_chunks",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_version", sa.String(255), primary_key=True),
        sa.Column("chunk_index", sa.Integer(), primary_key=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("snapshot_checksum", sa.String(64), nullable=False),
        sa.Column("payload_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version"],
            ["snapshot_ingest.snapshot_id", "snapshot_ingest.snapshot_version"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "snapshots",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_version", sa.String(255), primary_key=True),
        sa.Column("snapshot_time", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("produced_at", sa.Text(), nullable=False),
        sa.Column("config_version", sa.Text()),
        sa.Column("topology_version", sa.Text()),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_checksum", sa.String(64), nullable=False),
    )
    op.create_table(
        "alarms",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_version", sa.String(255), primary_key=True),
        sa.Column("alarm_id", sa.String(255), primary_key=True),
        sa.Column("alarm_name", sa.Text()),
        sa.Column("device_code", sa.Text()),
        sa.Column("node_reference", sa.Text()),
        sa.Column("severity_name", sa.Text()),
        sa.Column("canonical_start_time", sa.Text()),
        sa.Column("canonical_end_time", sa.Text()),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version"],
            ["snapshots.snapshot_id", "snapshots.snapshot_version"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "chains",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_version", sa.String(255), primary_key=True),
        sa.Column("chain_id", sa.String(255), primary_key=True),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("chain_name", sa.Text()),
        sa.Column("event_span_seconds", sa.Integer()),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version"],
            ["snapshots.snapshot_id", "snapshots.snapshot_version"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "memberships",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_version", sa.String(255), primary_key=True),
        sa.Column("chain_id", sa.String(255), primary_key=True),
        sa.Column("alarm_id", sa.String(255), primary_key=True),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version", "chain_id"],
            ["chains.snapshot_id", "chains.snapshot_version", "chains.chain_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "snapshot_version", "alarm_id"],
            ["alarms.snapshot_id", "alarms.snapshot_version", "alarms.alarm_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "kafka_inbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_id", sa.String(255)),
        sa.Column("snapshot_version", sa.String(255)),
        sa.Column("event_type", sa.String(64)),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("topic", "partition", "offset"),
    )


def downgrade() -> None:
    for table in (
        "kafka_inbox",
        "memberships",
        "chains",
        "alarms",
        "snapshots",
        "snapshot_chunks",
        "snapshot_ingest",
    ):
        op.drop_table(table)

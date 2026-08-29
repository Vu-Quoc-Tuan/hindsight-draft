"""tier1a logical ordering and worker leases

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snapshot_ingest",
        sa.Column("logical_snapshot_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("snapshot_ingest", sa.Column("worker_id", sa.String(255)))
    op.add_column(
        "snapshot_ingest",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "snapshot_ingest", sa.Column("started_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "snapshot_ingest", sa.Column("heartbeat_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "snapshot_ingest", sa.Column("next_attempt_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "snapshot_ingest",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        """
        UPDATE snapshot_ingest
        SET logical_snapshot_time =
            ((canonical_payload -> 'snapshot' ->> 'snapshot_time')::timestamptz)
        WHERE canonical_payload IS NOT NULL
          AND canonical_payload -> 'snapshot' ->> 'snapshot_time' IS NOT NULL
        """
    )
    op.create_index(
        "ix_snapshot_ingest_logical_order",
        "snapshot_ingest",
        ["logical_snapshot_time", "completed_at", "snapshot_id"],
    )
    op.create_index(
        "ix_snapshot_ingest_tier1a_lease",
        "snapshot_ingest",
        ["tier1a_status", "lease_expires_at", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_snapshot_ingest_tier1a_lease", table_name="snapshot_ingest")
    op.drop_index("ix_snapshot_ingest_logical_order", table_name="snapshot_ingest")
    for name in (
        "attempt_count",
        "next_attempt_at",
        "heartbeat_at",
        "started_at",
        "lease_expires_at",
        "worker_id",
        "logical_snapshot_time",
    ):
        op.drop_column("snapshot_ingest", name)

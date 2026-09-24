"""create a durable transaction-ordered invalidation journal

Revision ID: 0021
Revises: 0020
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "change_event_clock",
        sa.Column("singleton_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("epoch", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "singleton_id = 1", name="ck_change_event_clock_singleton"
        ),
        sa.CheckConstraint("revision >= 0", name="ck_change_event_clock_revision"),
    )
    op.create_table(
        "change_events",
        sa.Column("epoch", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("revision", sa.BigInteger(), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("snapshot_id", sa.Text(), nullable=True),
        sa.Column("snapshot_version", sa.Text(), nullable=True),
        sa.Column("chain_id", sa.Text(), nullable=True),
        sa.Column("topology_version", sa.Text(), nullable=True),
        sa.Column("identity_digest", sa.String(length=64), nullable=True),
        sa.Column("invalidates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("revision > 0", name="ck_change_events_revision"),
    )
    op.create_index(
        "ix_change_events_created_at", "change_events", ["created_at"]
    )
    op.bulk_insert(
        sa.table(
            "change_event_clock",
            sa.column("singleton_id", sa.Integer()),
            sa.column("epoch", sa.Uuid(as_uuid=True)),
            sa.column("revision", sa.BigInteger()),
        ),
        [{"singleton_id": 1, "epoch": uuid4(), "revision": 0}],
    )


def downgrade() -> None:
    op.drop_index("ix_change_events_created_at", table_name="change_events")
    op.drop_table("change_events")
    op.drop_table("change_event_clock")

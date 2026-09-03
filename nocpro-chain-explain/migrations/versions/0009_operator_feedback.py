"""persist operator feedback and mutation outcomes

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_feedback",
        sa.Column("feedback_id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("snapshot_version", sa.String(255), nullable=False),
        sa.Column("chain_id", sa.String(255), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("operator_id", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("partition_delta", postgresql.JSONB(), nullable=False),
        sa.Column("mutation_dispatched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mutation_dispatch_result", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_operator_feedback_job_id",
        "operator_feedback",
        ["job_id"],
    )
    op.create_index(
        "ix_operator_feedback_chain_id",
        "operator_feedback",
        ["chain_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_operator_feedback_chain_id", table_name="operator_feedback")
    op.drop_index("ix_operator_feedback_job_id", table_name="operator_feedback")
    op.drop_table("operator_feedback")

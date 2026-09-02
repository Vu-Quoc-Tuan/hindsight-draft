"""persist counterfactual review jobs

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterfactual_job",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("snapshot_version", sa.String(255), nullable=False),
        sa.Column("chain_id", sa.String(255), nullable=False),
        sa.Column("cache_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("identity_payload", postgresql.JSONB(), nullable=False),
        sa.Column("result_payload", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_counterfactual_job_identity",
        "counterfactual_job",
        ["snapshot_id", "snapshot_version", "chain_id", "updated_at"],
    )
    op.create_index(
        "ix_counterfactual_job_cache",
        "counterfactual_job",
        ["cache_fingerprint", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_counterfactual_job_cache", table_name="counterfactual_job")
    op.drop_index("ix_counterfactual_job_identity", table_name="counterfactual_job")
    op.drop_table("counterfactual_job")

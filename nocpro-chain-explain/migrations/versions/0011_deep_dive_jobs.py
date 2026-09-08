"""persist Deep Dive lifecycle and public results

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deep_dive_job",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("snapshot_version", sa.String(255), nullable=False),
        sa.Column("chain_id", sa.String(255), nullable=False),
        sa.Column("cache_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')",
            name="ck_deep_dive_job_status",
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_deep_dive_job_progress",
        ),
    )
    op.create_index(
        "ix_deep_dive_job_compatibility",
        "deep_dive_job",
        [
            "snapshot_id",
            "snapshot_version",
            "chain_id",
            "cache_fingerprint",
            "updated_at",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deep_dive_job_compatibility", table_name="deep_dive_job"
    )
    op.drop_table("deep_dive_job")

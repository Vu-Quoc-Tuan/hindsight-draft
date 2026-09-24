"""add provider-independent chain quality assessments.

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chain_quality_assessment" in set(inspector.get_table_names()):
        return
    op.create_table(
        "chain_quality_assessment",
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("snapshot_version", sa.String(255), nullable=False),
        sa.Column("chain_id", sa.String(255), nullable=False),
        sa.Column("assessment_version", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("available_dimension_count", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("deep_dive_job_id", sa.String(64), nullable=True),
        sa.Column("counterfactual_job_id", sa.String(64), nullable=True),
        sa.Column("recommendation_status", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
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
        sa.PrimaryKeyConstraint(
            "snapshot_id", "snapshot_version", "chain_id",
            name="pk_chain_quality_assessment",
        ),
    )
    op.create_index(
        "ix_chain_quality_assessment_snapshot",
        "chain_quality_assessment",
        ["snapshot_id", "snapshot_version", "status"],
    )
    op.create_index(
        "ix_chain_quality_assessment_input",
        "chain_quality_assessment",
        ["input_fingerprint"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chain_quality_assessment" not in set(inspector.get_table_names()):
        return
    op.drop_index(
        "ix_chain_quality_assessment_input",
        table_name="chain_quality_assessment",
    )
    op.drop_index(
        "ix_chain_quality_assessment_snapshot",
        table_name="chain_quality_assessment",
    )
    op.drop_table("chain_quality_assessment")

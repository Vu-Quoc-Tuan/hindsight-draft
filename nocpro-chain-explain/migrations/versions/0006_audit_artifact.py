"""persist immutable exact Audit artifacts

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_artifact",
        sa.Column("artifact_id", sa.String(64), primary_key=True),
        sa.Column("artifact_version", sa.String(64), nullable=False),
        sa.Column("artifact_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("snapshot_version", sa.String(255), nullable=False),
        sa.Column("chain_id", sa.String(255), nullable=False),
        sa.Column("chain_fingerprint", sa.String(64), nullable=False),
        sa.Column("analysis_version", sa.String(64), nullable=False),
        sa.Column("analysis_config_version", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status = 'AVAILABLE' AND mode = 'EXACT'",
            name="ck_audit_artifact_exact_available",
        ),
    )
    op.create_index(
        "ix_audit_artifact_compatibility",
        "audit_artifact",
        [
            "snapshot_id",
            "snapshot_version",
            "chain_id",
            "chain_fingerprint",
            "analysis_version",
            "analysis_config_version",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_artifact_compatibility", table_name="audit_artifact")
    op.drop_table("audit_artifact")

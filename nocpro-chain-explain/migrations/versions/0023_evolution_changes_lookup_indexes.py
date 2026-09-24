"""Bounded lookup indexes for C4 evolution changes.

Revision ID: 0023
Revises: 0022
"""

from alembic import op


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_lineage_edge_child_key",
        "lineage_edge",
        ["child_snapshot_id", "child_snapshot_version", "child_chain_id"],
    )
    op.create_index(
        "ix_quality_receipts_analysis_identity_gin",
        "quality_evaluation_receipts",
        ["analysis_identity"],
        postgresql_using="gin",
        postgresql_ops={"analysis_identity": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_quality_receipts_analysis_identity_gin", table_name="quality_evaluation_receipts")
    op.drop_index("ix_lineage_edge_child_key", table_name="lineage_edge")

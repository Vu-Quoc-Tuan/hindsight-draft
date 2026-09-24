"""Persist immutable historical quality evaluation receipts.

Revision ID: 0022
Revises: 0021
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quality_evaluation_receipts",
        sa.Column("receipt_id", sa.String(64), primary_key=True),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("artifact_revision", sa.String(64), nullable=False),
        sa.Column("analysis_identity", postgresql.JSONB(), nullable=False),
        sa.Column("assessment", postgresql.JSONB(), nullable=False),
        sa.Column("source_artifact_refs", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("identity_digest", "artifact_revision", name="uq_quality_receipt_identity_revision"),
    )
    op.create_index(
        "ix_quality_receipts_identity_created",
        "quality_evaluation_receipts",
        ["identity_digest", "created_at"],
    )
    op.execute("""
        CREATE FUNCTION reject_quality_receipt_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'quality evaluation receipts are immutable';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER quality_receipt_immutable
        BEFORE UPDATE OR DELETE ON quality_evaluation_receipts
        FOR EACH ROW EXECUTE FUNCTION reject_quality_receipt_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER quality_receipt_immutable ON quality_evaluation_receipts")
    op.execute("DROP FUNCTION reject_quality_receipt_mutation()")
    op.drop_index("ix_quality_receipts_identity_created", table_name="quality_evaluation_receipts")
    op.drop_table("quality_evaluation_receipts")

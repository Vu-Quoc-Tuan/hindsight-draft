"""persist immutable temporal delay models

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "temporal_delay_model",
        sa.Column("model_version", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("snapshot_version", sa.String(255), nullable=False),
        sa.Column("training_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_payload", postgresql.JSONB(), nullable=False),
        sa.Column("taxonomy_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("snapshot_id", "snapshot_version", name="uq_temporal_delay_model_snapshot"),
    )

def downgrade() -> None:
    op.drop_table("temporal_delay_model")

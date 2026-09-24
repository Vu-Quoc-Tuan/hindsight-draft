"""bind cohesion cache entries to every narrative input identity.

Revision ID: 0017
Revises: 0016
"""

from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cohesion_narrative_cache" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("cohesion_narrative_cache")}
    if "input_fingerprint" not in columns:
        op.add_column(
            "cohesion_narrative_cache",
            sa.Column("input_fingerprint", sa.String(length=64), nullable=False, server_default="LEGACY"),
        )
        op.create_index(
            "ix_cohesion_narrative_cache_input",
            "cohesion_narrative_cache",
            ["input_fingerprint"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cohesion_narrative_cache" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("cohesion_narrative_cache")}
    if "input_fingerprint" in columns:
        op.drop_index("ix_cohesion_narrative_cache_input", table_name="cohesion_narrative_cache")
        op.drop_column("cohesion_narrative_cache", "input_fingerprint")

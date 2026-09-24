"""persist the exact topology identity on Deep Dive jobs.

Revision ID: 0020
Revises: 0019
"""

from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "deep_dive_job" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("deep_dive_job")}
    if "topology_version" not in columns:
        op.add_column(
            "deep_dive_job",
            sa.Column("topology_version", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "deep_dive_job" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("deep_dive_job")}
    if "topology_version" in columns:
        op.drop_column("deep_dive_job", "topology_version")

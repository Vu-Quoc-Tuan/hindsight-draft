"""record the analysis config identity on active deep-dive jobs.

Revision ID: 0019
Revises: 0018
"""

from alembic import op
import sqlalchemy as sa


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "deep_dive_job" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("deep_dive_job")}
    if "analysis_config_version" not in columns:
        op.add_column(
            "deep_dive_job",
            sa.Column("analysis_config_version", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "deep_dive_job" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("deep_dive_job")}
    if "analysis_config_version" in columns:
        op.drop_column("deep_dive_job", "analysis_config_version")

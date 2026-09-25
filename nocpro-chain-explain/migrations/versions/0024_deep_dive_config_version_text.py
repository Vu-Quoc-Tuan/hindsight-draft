"""store the complete Deep Dive config identity without truncation.

Revision ID: 0024
Revises: 0023
"""

from alembic import op
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "deep_dive_job",
        "analysis_config_version",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_extended_values = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM deep_dive_job "
            "WHERE length(analysis_config_version) > 255)"
        )
    ).scalar_one()
    if has_extended_values:
        raise RuntimeError(
            "cannot downgrade analysis_config_version to VARCHAR(255): "
            "Deep Dive jobs contain longer config identities"
        )
    op.alter_column(
        "deep_dive_job",
        "analysis_config_version",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )

"""add cohesion_narrative_cache and topology_subgraph_cache tables

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "cohesion_narrative_cache" not in existing_tables:
        op.create_table(
            "cohesion_narrative_cache",
            sa.Column("snapshot_id", sa.String(255), nullable=False),
            sa.Column("snapshot_version", sa.String(255), nullable=False),
            sa.Column("chain_id", sa.String(255), nullable=False),
            sa.Column("language", sa.String(16), nullable=False, server_default="en"),
            sa.Column("has_p2", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("narrative", sa.Text(), nullable=False),
            sa.Column(
                "analytical_findings",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "context",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("model", sa.String(128), nullable=False, server_default="deterministic"),
            sa.Column(
                "provider_status",
                sa.String(64),
                nullable=False,
                server_default="GROUNDED_DETERMINISTIC",
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
                "snapshot_id", "snapshot_version", "chain_id", "language",
                name="pk_cohesion_narrative_cache",
            ),
        )
        op.create_index(
            "ix_cohesion_narrative_cache_chain",
            "cohesion_narrative_cache",
            ["snapshot_id", "chain_id"],
        )

    if "topology_subgraph_cache" not in existing_tables:
        op.create_table(
            "topology_subgraph_cache",
            sa.Column("cache_key", sa.String(255), primary_key=True),
            sa.Column("profile_id", sa.String(64), nullable=False),
            sa.Column("topology_version", sa.String(128), nullable=False),
            sa.Column(
                "subgraph_payload",
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
        )
        op.create_index(
            "ix_topology_subgraph_cache_profile",
            "topology_subgraph_cache",
            ["profile_id", "topology_version"],
        )


def downgrade() -> None:
    op.drop_index("ix_topology_subgraph_cache_profile", table_name="topology_subgraph_cache")
    op.drop_table("topology_subgraph_cache")
    op.drop_index("ix_cohesion_narrative_cache_chain", table_name="cohesion_narrative_cache")
    op.drop_table("cohesion_narrative_cache")

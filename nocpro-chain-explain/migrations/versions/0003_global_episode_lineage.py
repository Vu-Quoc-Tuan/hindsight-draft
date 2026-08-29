"""global persisted episode DAG lineage

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("snapshot_ingest", sa.Column("lineage_status", sa.String(32)))
    op.add_column("snapshot_ingest", sa.Column("lineage_result", postgresql.JSONB()))
    op.add_column("snapshot_ingest", sa.Column("similarity_status", sa.String(32)))
    op.execute(
        "UPDATE snapshot_ingest SET lineage_status = 'PENDING' "
        "WHERE tier1a_status = 'READY'"
    )
    op.create_table(
        "lineage_component",
        sa.Column("component_id", sa.String(64), primary_key=True),
        sa.Column("canonical_component_id", sa.String(64), nullable=False),
        sa.Column("first_snapshot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_snapshot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    op.create_table(
        "lineage_node",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_chain_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component_id", sa.String(64), nullable=False),
        sa.Column("branch_id", sa.String(96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["component_id"], ["lineage_component.component_id"]),
    )
    op.create_table(
        "lineage_edge",
        sa.Column("parent_snapshot_id", sa.String(255), primary_key=True),
        sa.Column("parent_chain_id", sa.String(255), primary_key=True),
        sa.Column("child_snapshot_id", sa.String(255), primary_key=True),
        sa.Column("child_chain_id", sa.String(255), primary_key=True),
        sa.Column("edge_type", sa.String(32), nullable=False),
        sa.Column("overlap_count", sa.Integer(), nullable=False),
        sa.Column("contain_parent", sa.Float(), nullable=False),
        sa.Column("contain_child", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_snapshot_id", "parent_chain_id"],
            ["lineage_node.snapshot_id", "lineage_node.snapshot_chain_id"],
        ),
        sa.ForeignKeyConstraint(
            ["child_snapshot_id", "child_chain_id"],
            ["lineage_node.snapshot_id", "lineage_node.snapshot_chain_id"],
        ),
    )
    op.create_index(
        "ix_snapshot_ingest_lineage_order",
        "snapshot_ingest",
        ["lineage_status", "logical_snapshot_time", "snapshot_id"],
    )
    op.create_index(
        "ix_lineage_node_component", "lineage_node", ["component_id"]
    )
    op.create_table(
        "similarity_fingerprint",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_chain_id", sa.String(255), primary_key=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component_id", sa.String(64), nullable=False),
        sa.Column("fingerprint_payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "snapshot_chain_id"],
            ["lineage_node.snapshot_id", "lineage_node.snapshot_chain_id"],
        ),
    )
    op.create_table(
        "similarity_model",
        sa.Column("model_version", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(255), nullable=False, unique=True),
        sa.Column("trained_until_exclusive", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "similarity_index_entry",
        sa.Column("model_version", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("snapshot_chain_id", sa.String(255), primary_key=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint_payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["model_version"], ["similarity_model.model_version"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("similarity_index_entry")
    op.drop_table("similarity_model")
    op.drop_table("similarity_fingerprint")
    op.drop_index("ix_lineage_node_component", table_name="lineage_node")
    op.drop_index("ix_snapshot_ingest_lineage_order", table_name="snapshot_ingest")
    op.drop_table("lineage_edge")
    op.drop_table("lineage_node")
    op.drop_table("lineage_component")
    op.drop_column("snapshot_ingest", "similarity_status")
    op.drop_column("snapshot_ingest", "lineage_result")
    op.drop_column("snapshot_ingest", "lineage_status")

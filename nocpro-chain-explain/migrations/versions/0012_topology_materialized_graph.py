"""materialize versioned topology graph and durable Kafka ingest tables

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Durable Kafka Ingestion Tables
    op.create_table(
        "topology_ingest",
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("topology_version", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=True),
        sa.Column("received_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_checksum", sa.String(64), nullable=True),
        sa.Column("invalid_reason", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("profile_id", "topology_version"),
        sa.CheckConstraint(
            "status IN ('RECEIVING', 'READY', 'INVALID', 'EXPIRED')",
            name="ck_topology_ingest_status",
        ),
    )

    op.create_table(
        "topology_chunks",
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("topology_version", sa.String(128), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_checksum", sa.String(64), nullable=False),
        sa.Column("payload_compressed", sa.LargeBinary(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("profile_id", "topology_version", "chunk_index"),
        sa.ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_ingest.profile_id", "topology_ingest.topology_version"],
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "topology_kafka_inbox",
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column("message_key", sa.String(256), nullable=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("topic", "partition", "offset"),
    )

    # 2. Materialized Topology Versioning & Metadata
    op.create_table(
        "topology_versions",
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("topology_version", sa.String(128), nullable=False),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("relation_model", sa.String(64), nullable=False),
        sa.Column("direction_kind", sa.String(64), nullable=False),
        sa.Column("dependency_semantics", sa.String(64), nullable=False),
        sa.Column("navigation_eligible", sa.Boolean(), nullable=False),
        sa.Column("p2_eligible", sa.Boolean(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("alias_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_checksum", sa.String(64), nullable=True),
        sa.Column(
            "produced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("profile_id", "topology_version"),
        sa.CheckConstraint(
            "status IN ('RECEIVING', 'READY', 'INVALID')",
            name="ck_topology_versions_status",
        ),
    )

    op.create_table(
        "topology_active_versions",
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column("topology_version", sa.String(128), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_versions.profile_id", "topology_versions.topology_version"],
            ondelete="CASCADE",
        ),
    )

    # 3. Materialized Nodes, Edges & Aliases
    op.create_table(
        "topology_nodes",
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("topology_version", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(256), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("source_tables", postgresql.JSONB(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("profile_id", "topology_version", "resource_id"),
        sa.ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_versions.profile_id", "topology_versions.topology_version"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_topology_nodes_search",
        "topology_nodes",
        ["profile_id", "topology_version", "display_name"],
    )

    op.create_table(
        "topology_edges",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("topology_version", sa.String(128), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("target_id", sa.String(256), nullable=False),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("direction_kind", sa.String(64), nullable=True),
        sa.Column("dependency_semantics", sa.String(64), nullable=True),
        sa.Column("source_table", sa.String(128), nullable=True),
        sa.Column("source_version", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_versions.profile_id", "topology_versions.topology_version"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "profile_id",
            "topology_version",
            "source_id",
            "target_id",
            "relation_type",
            name="uq_topology_edges_natural",
        ),
    )
    op.create_index(
        "ix_topology_edges_source",
        "topology_edges",
        ["profile_id", "topology_version", "source_id"],
    )
    op.create_index(
        "ix_topology_edges_target",
        "topology_edges",
        ["profile_id", "topology_version", "target_id"],
    )

    op.create_table(
        "topology_alias_resolution",
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("topology_version", sa.String(128), nullable=False),
        sa.Column("alias_key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("unique_resource_id", sa.String(256), nullable=True),
        sa.Column("verified_by", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("profile_id", "topology_version", "alias_key"),
        sa.CheckConstraint(
            "status IN ('UNIQUE', 'AMBIGUOUS')",
            name="ck_topology_alias_resolution_status",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "topology_version"],
            ["topology_versions.profile_id", "topology_versions.topology_version"],
            ondelete="CASCADE",
        ),
    )

    # 4. Snapshot-to-Topology cross reference
    op.add_column(
        "snapshot_ingest",
        sa.Column("topology_profile_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "snapshot_ingest",
        sa.Column("topology_version_ref", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("snapshot_ingest", "topology_version_ref")
    op.drop_column("snapshot_ingest", "topology_profile_id")
    op.drop_table("topology_alias_resolution")
    op.drop_table("topology_edges")
    op.drop_table("topology_nodes")
    op.drop_table("topology_active_versions")
    op.drop_table("topology_versions")
    op.drop_table("topology_kafka_inbox")
    op.drop_table("topology_chunks")
    op.drop_table("topology_ingest")

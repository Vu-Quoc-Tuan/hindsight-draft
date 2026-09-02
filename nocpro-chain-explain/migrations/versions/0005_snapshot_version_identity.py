"""make lineage and similarity identity snapshot-version aware

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _require_unambiguous_legacy_rows() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM (
              SELECT legacy.snapshot_id
              FROM (
                SELECT snapshot_id FROM lineage_node
                UNION ALL SELECT snapshot_id FROM similarity_fingerprint
                UNION ALL SELECT snapshot_id FROM similarity_model
                UNION ALL SELECT snapshot_id FROM similarity_index_entry
              ) AS legacy
              LEFT JOIN snapshots AS snapshot
                ON snapshot.snapshot_id = legacy.snapshot_id
              GROUP BY legacy.snapshot_id
              HAVING COUNT(DISTINCT snapshot.snapshot_version) <> 1
            ) AS ambiguous
          ) THEN
            RAISE EXCEPTION
              '0005 cannot backfill snapshot_version: legacy snapshot_id is missing or ambiguous';
          END IF;
        END $$;
        """
    )


def upgrade() -> None:
    op.add_column("lineage_node", sa.Column("snapshot_version", sa.String(255)))
    op.add_column(
        "lineage_edge", sa.Column("parent_snapshot_version", sa.String(255))
    )
    op.add_column(
        "lineage_edge", sa.Column("child_snapshot_version", sa.String(255))
    )
    op.add_column(
        "similarity_fingerprint", sa.Column("snapshot_version", sa.String(255))
    )
    op.add_column(
        "similarity_model", sa.Column("snapshot_version", sa.String(255))
    )
    op.add_column(
        "similarity_index_entry", sa.Column("snapshot_version", sa.String(255))
    )

    _require_unambiguous_legacy_rows()
    for table in (
        "lineage_node",
        "similarity_fingerprint",
        "similarity_model",
        "similarity_index_entry",
    ):
        op.execute(
            f"""
            UPDATE {table} AS target
            SET snapshot_version = snapshot.snapshot_version
            FROM snapshots AS snapshot
            WHERE snapshot.snapshot_id = target.snapshot_id
            """
        )
    op.execute(
        """
        UPDATE lineage_edge AS edge
        SET parent_snapshot_version = parent.snapshot_version,
            child_snapshot_version = child.snapshot_version
        FROM lineage_node AS parent, lineage_node AS child
        WHERE parent.snapshot_id = edge.parent_snapshot_id
          AND parent.snapshot_chain_id = edge.parent_chain_id
          AND child.snapshot_id = edge.child_snapshot_id
          AND child.snapshot_chain_id = edge.child_chain_id
        """
    )

    op.drop_constraint(
        "lineage_edge_parent_snapshot_id_parent_chain_id_fkey",
        "lineage_edge",
        type_="foreignkey",
    )
    op.drop_constraint(
        "lineage_edge_child_snapshot_id_child_chain_id_fkey",
        "lineage_edge",
        type_="foreignkey",
    )
    op.drop_constraint(
        "similarity_fingerprint_snapshot_id_snapshot_chain_id_fkey",
        "similarity_fingerprint",
        type_="foreignkey",
    )
    op.drop_constraint(
        "similarity_model_snapshot_id_key", "similarity_model", type_="unique"
    )

    for table in (
        "lineage_node",
        "lineage_edge",
        "similarity_fingerprint",
        "similarity_index_entry",
    ):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")

    for table, column in (
        ("lineage_node", "snapshot_version"),
        ("lineage_edge", "parent_snapshot_version"),
        ("lineage_edge", "child_snapshot_version"),
        ("similarity_fingerprint", "snapshot_version"),
        ("similarity_model", "snapshot_version"),
        ("similarity_index_entry", "snapshot_version"),
    ):
        op.alter_column(table, column, nullable=False)

    op.create_primary_key(
        "lineage_node_pkey",
        "lineage_node",
        ["snapshot_id", "snapshot_version", "snapshot_chain_id"],
    )
    op.create_primary_key(
        "lineage_edge_pkey",
        "lineage_edge",
        [
            "parent_snapshot_id",
            "parent_snapshot_version",
            "parent_chain_id",
            "child_snapshot_id",
            "child_snapshot_version",
            "child_chain_id",
        ],
    )
    op.create_primary_key(
        "similarity_fingerprint_pkey",
        "similarity_fingerprint",
        ["snapshot_id", "snapshot_version", "snapshot_chain_id"],
    )
    op.create_primary_key(
        "similarity_index_entry_pkey",
        "similarity_index_entry",
        ["model_version", "snapshot_id", "snapshot_version", "snapshot_chain_id"],
    )
    op.create_unique_constraint(
        "uq_similarity_model_snapshot_identity",
        "similarity_model",
        ["snapshot_id", "snapshot_version"],
    )
    op.create_foreign_key(
        "fk_lineage_edge_parent_versioned",
        "lineage_edge",
        "lineage_node",
        ["parent_snapshot_id", "parent_snapshot_version", "parent_chain_id"],
        ["snapshot_id", "snapshot_version", "snapshot_chain_id"],
    )
    op.create_foreign_key(
        "fk_lineage_edge_child_versioned",
        "lineage_edge",
        "lineage_node",
        ["child_snapshot_id", "child_snapshot_version", "child_chain_id"],
        ["snapshot_id", "snapshot_version", "snapshot_chain_id"],
    )
    op.create_foreign_key(
        "fk_similarity_fingerprint_lineage_versioned",
        "similarity_fingerprint",
        "lineage_node",
        ["snapshot_id", "snapshot_version", "snapshot_chain_id"],
        ["snapshot_id", "snapshot_version", "snapshot_chain_id"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM lineage_node
            GROUP BY snapshot_id, snapshot_chain_id HAVING COUNT(*) > 1
          ) OR EXISTS (
            SELECT 1 FROM lineage_edge
            GROUP BY parent_snapshot_id, parent_chain_id,
                     child_snapshot_id, child_chain_id HAVING COUNT(*) > 1
          ) OR EXISTS (
            SELECT 1 FROM similarity_fingerprint
            GROUP BY snapshot_id, snapshot_chain_id HAVING COUNT(*) > 1
          ) OR EXISTS (
            SELECT 1 FROM similarity_model
            GROUP BY snapshot_id HAVING COUNT(*) > 1
          ) OR EXISTS (
            SELECT 1 FROM similarity_index_entry
            GROUP BY model_version, snapshot_id, snapshot_chain_id HAVING COUNT(*) > 1
          ) THEN
            RAISE EXCEPTION
              '0005 downgrade would collapse distinct snapshot versions';
          END IF;
        END $$;
        """
    )

    op.drop_constraint(
        "fk_similarity_fingerprint_lineage_versioned",
        "similarity_fingerprint",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_lineage_edge_child_versioned", "lineage_edge", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_lineage_edge_parent_versioned", "lineage_edge", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_similarity_model_snapshot_identity", "similarity_model", type_="unique"
    )
    for table in (
        "lineage_node",
        "lineage_edge",
        "similarity_fingerprint",
        "similarity_index_entry",
    ):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")

    op.create_primary_key(
        "lineage_node_pkey", "lineage_node", ["snapshot_id", "snapshot_chain_id"]
    )
    op.create_primary_key(
        "lineage_edge_pkey",
        "lineage_edge",
        [
            "parent_snapshot_id",
            "parent_chain_id",
            "child_snapshot_id",
            "child_chain_id",
        ],
    )
    op.create_primary_key(
        "similarity_fingerprint_pkey",
        "similarity_fingerprint",
        ["snapshot_id", "snapshot_chain_id"],
    )
    op.create_primary_key(
        "similarity_index_entry_pkey",
        "similarity_index_entry",
        ["model_version", "snapshot_id", "snapshot_chain_id"],
    )
    op.create_unique_constraint(
        "similarity_model_snapshot_id_key", "similarity_model", ["snapshot_id"]
    )
    op.create_foreign_key(
        "lineage_edge_parent_snapshot_id_parent_chain_id_fkey",
        "lineage_edge",
        "lineage_node",
        ["parent_snapshot_id", "parent_chain_id"],
        ["snapshot_id", "snapshot_chain_id"],
    )
    op.create_foreign_key(
        "lineage_edge_child_snapshot_id_child_chain_id_fkey",
        "lineage_edge",
        "lineage_node",
        ["child_snapshot_id", "child_chain_id"],
        ["snapshot_id", "snapshot_chain_id"],
    )
    op.create_foreign_key(
        "similarity_fingerprint_snapshot_id_snapshot_chain_id_fkey",
        "similarity_fingerprint",
        "lineage_node",
        ["snapshot_id", "snapshot_chain_id"],
        ["snapshot_id", "snapshot_chain_id"],
    )
    for table, column in (
        ("similarity_index_entry", "snapshot_version"),
        ("similarity_model", "snapshot_version"),
        ("similarity_fingerprint", "snapshot_version"),
        ("lineage_edge", "child_snapshot_version"),
        ("lineage_edge", "parent_snapshot_version"),
        ("lineage_node", "snapshot_version"),
    ):
        op.drop_column(table, column)

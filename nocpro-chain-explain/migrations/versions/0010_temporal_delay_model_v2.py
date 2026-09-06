"""allow immutable temporal delay model implementation versions

Revision ID: 0010
Revises: 0009
"""

from alembic import op


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # V1 rows remain immutable for audit/replay.  A corrected model procedure
    # receives a new model_version rather than overwriting a prior artifact.
    op.drop_constraint(
        "uq_temporal_delay_model_snapshot",
        "temporal_delay_model",
        type_="unique",
    )
    op.create_index(
        "ix_temporal_delay_model_snapshot_created",
        "temporal_delay_model",
        ["snapshot_id", "snapshot_version", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_temporal_delay_model_snapshot_created",
        table_name="temporal_delay_model",
    )
    # A data-preserving downgrade is valid only before a second immutable model
    # version exists for one snapshot.  Refuse to silently discard either
    # artifact merely to restore the old uniqueness rule.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM temporal_delay_model
            GROUP BY snapshot_id, snapshot_version
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION
              'cannot downgrade 0010 while multiple immutable temporal models exist per snapshot';
          END IF;
        END
        $$;
        """
    )
    op.create_unique_constraint(
        "uq_temporal_delay_model_snapshot",
        "temporal_delay_model",
        ["snapshot_id", "snapshot_version"],
    )

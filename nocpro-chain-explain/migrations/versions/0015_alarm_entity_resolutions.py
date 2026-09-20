"""add alarm_entity_resolutions table

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # This table was introduced while some long-lived development databases
    # already had it materialized from ORM metadata.  Do not destroy those
    # persisted resolutions: reconcile the DDL Alembic owns, then let the
    # revision be recorded normally.
    if "alarm_entity_resolutions" in existing_tables:
        columns = {
            column["name"]: column
            for column in inspector.get_columns("alarm_entity_resolutions")
        }
        required_columns = {
            "resolution_id",
            "alarm_id",
            "profile_id",
            "topology_version",
            "resolver_version",
            "entity_role",
            "raw_value",
            "resource_id",
            "status",
            "method",
            "source_field",
            "confidence",
            "candidate_resource_ids",
            "matched_text",
            "created_at",
        }
        missing_columns = required_columns - columns.keys()
        if missing_columns:
            raise RuntimeError(
                "Existing alarm_entity_resolutions table is incompatible with "
                f"migration 0015; missing columns: {', '.join(sorted(missing_columns))}"
            )

        # ORM-created tables have client-side defaults, whereas this migration
        # deliberately establishes database defaults for direct SQL callers.
        if columns["resolver_version"]["default"] is None:
            op.alter_column(
                "alarm_entity_resolutions",
                "resolver_version",
                server_default="v1",
            )
        if columns["candidate_resource_ids"]["default"] is None:
            op.alter_column(
                "alarm_entity_resolutions",
                "candidate_resource_ids",
                server_default=sa.text("'[]'::jsonb"),
            )
        if columns["created_at"]["default"] is None:
            op.alter_column(
                "alarm_entity_resolutions",
                "created_at",
                server_default=sa.func.now(),
            )

        existing_indexes = {
            index["name"]
            for index in inspector.get_indexes("alarm_entity_resolutions")
        }
        if "ix_alarm_entity_resolutions_alarm_id" not in existing_indexes:
            op.create_index(
                "ix_alarm_entity_resolutions_alarm_id",
                "alarm_entity_resolutions",
                ["alarm_id"],
            )
        if "ix_alarm_entity_resolutions_topo_ver" not in existing_indexes:
            op.create_index(
                "ix_alarm_entity_resolutions_topo_ver",
                "alarm_entity_resolutions",
                ["profile_id", "topology_version"],
            )
        return

    op.create_table(
        "alarm_entity_resolutions",
        sa.Column("resolution_id", sa.String(256), primary_key=True),
        sa.Column("alarm_id", sa.String(64), nullable=False),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("topology_version", sa.String(128), nullable=False),
        sa.Column("resolver_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("entity_role", sa.String(64), nullable=False),
        sa.Column("raw_value", sa.String(256), nullable=False),
        sa.Column("resource_id", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("source_field", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "candidate_resource_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("matched_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_alarm_entity_resolutions_alarm_id",
        "alarm_entity_resolutions",
        ["alarm_id"],
    )
    op.create_index(
        "ix_alarm_entity_resolutions_topo_ver",
        "alarm_entity_resolutions",
        ["profile_id", "topology_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_alarm_entity_resolutions_topo_ver", table_name="alarm_entity_resolutions")
    op.drop_index("ix_alarm_entity_resolutions_alarm_id", table_name="alarm_entity_resolutions")
    op.drop_table("alarm_entity_resolutions")

"""review learning store: complete candidate exposure, immutable feedback, lifecycle audit, and review cases

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. review_session
    op.create_table(
        "review_session",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("snapshot_version", sa.String(255), nullable=False),
        sa.Column("chain_id", sa.String(255), nullable=False),
        sa.Column("review_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("lineage_component_id", sa.String(255), nullable=True),
        sa.Column("candidate_set_fingerprint", sa.String(64), nullable=False),
        sa.Column("generator_version", sa.String(128), nullable=False),
        sa.Column("config_version", sa.String(128), nullable=False),
        sa.Column("delay_model_version", sa.String(128), nullable=True),
        sa.Column("retrieval_version", sa.String(128), nullable=True),
        sa.Column("exposure_policy", sa.String(64), nullable=False, server_default="ALL_EVALUATED"),
        sa.Column("status", sa.String(32), nullable=False, server_default="COMPLETED"),
        sa.Column("review_domain", sa.String(64), nullable=False),
        sa.Column("snapshot_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("job_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_alarm_universe_fingerprint", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_review_session_job_id", "review_session", ["job_id"])
    op.create_index("ix_review_session_chain_id", "review_session", ["chain_id"])
    op.create_index("ix_review_session_review_time", "review_session", ["review_time"])
    op.create_index("ix_review_session_review_domain", "review_session", ["review_domain"])

    # 2. candidate_exposure
    op.create_table(
        "candidate_exposure",
        sa.Column("exposure_id", sa.String(64), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(64),
            sa.ForeignKey("review_session.review_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("candidate_fingerprint", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("original_rank", sa.Integer(), nullable=False),
        sa.Column("displayed_rank", sa.Integer(), nullable=False),
        sa.Column("deterministic_eligibility", sa.String(64), nullable=False),
        sa.Column("hard_gate_status", sa.String(32), nullable=False),
        sa.Column("pareto_state", sa.String(64), nullable=False),
        sa.Column("deterministic_context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("case_context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("temporal_context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("feature_fingerprint", sa.String(64), nullable=False),
        sa.Column("feature_schema_version", sa.String(64), nullable=False, server_default="cf-features-v1"),
        sa.Column("feature_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("review_id", "candidate_id", name="uq_candidate_exposure_review_candidate"),
    )
    op.create_index("ix_candidate_exposure_review_id", "candidate_exposure", ["review_id"])
    op.create_index("ix_candidate_exposure_candidate_id", "candidate_exposure", ["candidate_id"])
    op.create_index("ix_candidate_exposure_fingerprint", "candidate_exposure", ["candidate_fingerprint"])

    # 3. candidate_display_event
    op.create_table(
        "candidate_display_event",
        sa.Column("display_event_id", sa.String(64), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(64),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("displayed_rank", sa.Integer(), nullable=False),
        sa.Column("exposure_policy", sa.String(64), nullable=False),
        sa.Column("surface", sa.String(64), nullable=False),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("viewer_session_id", sa.String(64), nullable=True),
        sa.Column("client_event_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "candidate_id"],
            ["candidate_exposure.review_id", "candidate_exposure.candidate_id"],
            ondelete="RESTRICT",
            name="fk_display_event_candidate_exposure",
        ),
        sa.UniqueConstraint("review_id", "client_event_id", name="uq_display_event_review_client_event"),
    )
    op.create_index(
        "ix_candidate_display_client_event_id",
        "candidate_display_event",
        ["client_event_id"],
    )
    op.create_index(
        "ix_candidate_display_review_candidate",
        "candidate_display_event",
        ["review_id", "candidate_id"],
    )

    # 4. review_feedback
    op.create_table(
        "review_feedback",
        sa.Column("feedback_id", sa.String(64), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(64),
            sa.ForeignKey("review_session.review_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.String(64), nullable=True),
        sa.Column("reviewer_subject", sa.String(255), nullable=False),
        sa.Column("reviewer_role", sa.String(64), nullable=False),
        sa.Column("domain_scope", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason_policy_version", sa.String(64), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("truth_tier", sa.String(32), nullable=False),
        sa.Column(
            "supersedes_feedback_id",
            sa.String(64),
            sa.ForeignKey("review_feedback.feedback_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("artifact_fingerprints", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "candidate_id"],
            ["candidate_exposure.review_id", "candidate_exposure.candidate_id"],
            ondelete="RESTRICT",
            name="fk_feedback_candidate_exposure",
        ),
    )
    op.create_index("ix_review_feedback_review_id", "review_feedback", ["review_id"])
    op.create_index("ix_review_feedback_candidate_id", "review_feedback", ["candidate_id"])
    op.create_index("ix_review_feedback_reviewer_subject", "review_feedback", ["reviewer_subject"])
    op.create_index("ix_review_feedback_decision", "review_feedback", ["decision"])

    # 5. feedback_lifecycle_event
    op.create_table(
        "feedback_lifecycle_event",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column(
            "feedback_id",
            sa.String(64),
            sa.ForeignKey("review_feedback.feedback_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor_subject", sa.String(255), nullable=False),
        sa.Column(
            "superseded_by_id",
            sa.String(64),
            sa.ForeignKey("review_feedback.feedback_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_feedback_lifecycle_feedback_id", "feedback_lifecycle_event", ["feedback_id"])
    op.create_index("ix_feedback_lifecycle_event_type", "feedback_lifecycle_event", ["event_type"])

    # 6. manual_correction
    op.create_table(
        "manual_correction",
        sa.Column("correction_id", sa.String(64), primary_key=True),
        sa.Column(
            "feedback_id",
            sa.String(64),
            sa.ForeignKey("review_feedback.feedback_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("partition_delta", postgresql.JSONB(), nullable=False),
        sa.Column("correction_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_manual_correction_feedback_id", "manual_correction", ["feedback_id"])

    # 7. review_case
    op.create_table(
        "review_case",
        sa.Column("case_id", sa.String(64), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(64),
            sa.ForeignKey("review_session.review_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "feedback_id",
            sa.String(64),
            sa.ForeignKey("review_feedback.feedback_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.String(64), nullable=True),
        sa.Column("case_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lineage_component_id", sa.String(255), nullable=True),
        sa.Column("operation_pattern", sa.String(64), nullable=False),
        sa.Column("fingerprint_schema_version", sa.String(64), nullable=False),
        sa.Column("fingerprint_payload", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint_hash", sa.String(64), nullable=False),
        sa.Column("case_domain", sa.String(64), nullable=False),
        sa.Column("domain_scope", postgresql.JSONB(), nullable=True),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("truth_tier", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_review_case_fingerprint_hash", "review_case", ["fingerprint_hash"])
    op.create_index("ix_review_case_decision", "review_case", ["decision"])
    op.create_index("ix_review_case_review_id", "review_case", ["review_id"])
    op.create_index("ix_review_case_feedback_id", "review_case", ["feedback_id"])
    op.create_index("ix_review_case_status", "review_case", ["status"])
    op.create_index("ix_review_case_case_domain", "review_case", ["case_domain"])


def downgrade() -> None:
    op.drop_table("review_case")
    op.drop_table("manual_correction")
    op.drop_table("feedback_lifecycle_event")
    op.drop_table("review_feedback")
    op.drop_table("candidate_display_event")
    op.drop_table("candidate_exposure")
    op.drop_table("review_session")

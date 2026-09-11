"""remove unsafe review-learning provenance defaults

Revision ID: 0014
Revises: 0013
"""

from alembic import op


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Provenance must be supplied by the server-side frozen review context;
    # a raw SQL insert must never acquire IP_NETWORK or PO_ASSERTED implicitly.
    op.alter_column("review_session", "review_domain", server_default=None)
    op.alter_column("review_feedback", "truth_tier", server_default=None)
    op.alter_column("review_case", "case_domain", server_default=None)


def downgrade() -> None:
    op.alter_column("review_session", "review_domain", server_default="IP_NETWORK")
    op.alter_column("review_feedback", "truth_tier", server_default="PO_ASSERTED")
    op.alter_column("review_case", "case_domain", server_default="IP_NETWORK")

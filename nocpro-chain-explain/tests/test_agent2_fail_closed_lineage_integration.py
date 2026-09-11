"""End-to-end integration test verifying fail-closed lineage and source provenance

Validates that Agent 1's fail-closed defaults ("LINEAGE_UNAVAILABLE", "SOURCE_KIND_UNAVAILABLE")
are safely received by Agent 2's materializer and correctly excluded from protected training corpora.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from review_learning.contracts import (
    CandidateExposure,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
)
from review_learning.materializer import (
    materialize_training_corpus_from_repository_groups,
)


from dataclasses import replace
from review_learning import generate_synthetic_review_group


def _make_review_group(
    review_id: str,
    lineage_component_id: str | None,
    source_kind: str | None = "COUNTERFACTUAL_JOB",
    review_time: str = "2026-09-01T10:00:00Z",
) -> dict:
    session, exposures, feedback = generate_synthetic_review_group(
        review_id=review_id,
        review_time=review_time,
        lineage_component_id=lineage_component_id or "placeholder_comp",
        scenario="STANDARD_TOP1_APPROVED",
        truth_tier=TruthTier.PO_ASSERTED,
    )
    session = replace(
        session,
        lineage_component_id=lineage_component_id,
        source_kind=source_kind or "SOURCE_KIND_UNAVAILABLE",
    )
    return {
        "review_session": session,
        "candidate_exposures": exposures,
        "active_feedbacks": feedback,
    }


def test_agent2_materializer_rejects_lineage_unavailable():
    """Agent 2 materializer must exclude groups with LINEAGE_UNAVAILABLE."""
    grp_unavailable = _make_review_group(
        review_id="rev_no_lineage",
        lineage_component_id="LINEAGE_UNAVAILABLE",
    )
    grp_none = _make_review_group(
        review_id="rev_none_lineage",
        lineage_component_id=None,
    )
    grp_valid = _make_review_group(
        review_id="rev_valid_lineage",
        lineage_component_id="valid_comp_100",
    )

    corpus = materialize_training_corpus_from_repository_groups(
        groups=[grp_unavailable, grp_none, grp_valid],
        cutoff="2026-09-10T00:00:00Z",
        protected_mode=True,
    )

    # rev_no_lineage and rev_none_lineage must be in excluded_groups
    excluded_reasons = {eg.review_id: eg.reason for eg in corpus.excluded_groups}
    assert "rev_no_lineage" in excluded_reasons
    assert excluded_reasons["rev_no_lineage"] == "LINEAGE_UNAVAILABLE"
    assert "rev_none_lineage" in excluded_reasons
    assert excluded_reasons["rev_none_lineage"] == "LINEAGE_UNAVAILABLE"

    # rev_valid_lineage should not be excluded for lineage reasons
    assert "rev_valid_lineage" not in excluded_reasons


def test_agent2_materializer_rejects_unverified_fallback_lineage():
    """Agent 2 materializer must exclude groups with fallback_lineage: prefixes."""
    grp_fallback = _make_review_group(
        review_id="rev_fallback",
        lineage_component_id="fallback_lineage:chain_1",
    )
    corpus = materialize_training_corpus_from_repository_groups(
        groups=[grp_fallback],
        cutoff="2026-09-10T00:00:00Z",
        protected_mode=True,
    )
    excluded_reasons = {eg.review_id: eg.reason for eg in corpus.excluded_groups}
    assert "rev_fallback" in excluded_reasons
    assert excluded_reasons["rev_fallback"] == "UNVERIFIED_LINEAGE_FALLBACK"

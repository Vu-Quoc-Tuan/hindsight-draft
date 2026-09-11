"""Synthetic data factory for testing the Review-Learning pipeline.

Generates realistic, schema-compliant synthetic review groups to validate:
- Candidate approve / reject
- NONE_ACCEPTABLE
- Manual correction
- Temporal leakage (feedback after cutoff)
- Lineage leakage (same lineage component across temporal splits)
- Missing features (delay unavailable, similar cases unavailable)
- Superseded / retracted feedback
- Unreviewed candidates (must never be treated as negative labels)

Every synthetic object MUST be explicitly tagged with SourceKind.SYNTHETIC_TEST.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from .contracts import (
    CandidateExposure,
    FeedbackStatus,
    ManualCorrection,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
    canonical_fingerprint,
)
from .features import FEATURE_SCHEMA_VERSION, materialize_candidate_features


def create_synthetic_candidate_exposure(
    *,
    review_id: str,
    candidate_id: str,
    operation: str = "REMOVE_MEMBER",
    original_rank: int = 1,
    displayed_rank: int = 1,
    shown_to_reviewer: bool = True,
    deterministic_eligibility: bool = True,
    hard_gate_status: str = "PASSED",
    pareto_state: str = "FRONTIER_SELECTED",
    metric_deltas: dict[str, float] | None = None,
    edit_cost: dict[str, int] | None = None,
    temporal_available: bool = True,
    case_available: bool = True,
    created_at: str = "2026-09-01T10:00:00Z",
) -> CandidateExposure:
    """Generate a single candidate exposure with full synthetic context."""
    deltas = metric_deltas or {
        "weak_member_count": -1.0,
        "minimum_membership_support": 0.15,
        "evidence_union_coverage": 0.05,
        "component_count": 0.0,
        "audit_conductance": -0.08,
        "audit_verdict_severity": -1.0,
    }

    deterministic_ctx = {
        "metric_deltas": deltas,
        "before_metrics": {
            "weak_member_count": {"availability": "AVAILABLE", "value": 2.0},
            "minimum_membership_support": {"availability": "AVAILABLE", "value": 0.40},
            "component_count": {"availability": "AVAILABLE", "value": 1.0},
        },
        "edit_cost": edit_cost or {
            "members_moved": 1,
            "chains_created": 0,
            "chains_removed": 0,
        },
        "topology_dep_hop_available": True,
    }

    temporal_ctx = (
        {
            "status": "AVAILABLE",
            "delay_score_mean": 0.72,
            "atypical_fraction": 0.05,
            "fallback_fraction": 0.0,
        }
        if temporal_available
        else {"status": "UNAVAILABLE", "reason": "TAXONOMY_MISSING"}
    )

    case_ctx = (
        {
            "status": "AVAILABLE",
            "approved_ratio": 0.80,
            "max_similarity": 0.88,
        }
        if case_available
        else {"status": "UNAVAILABLE", "reason": "NO_PRIOR_CASES"}
    )

    features = materialize_candidate_features(
        operation=operation,
        deterministic_context=deterministic_ctx,
        temporal_context=temporal_ctx,
        case_context=case_ctx,
        hard_gate_status=hard_gate_status,
        pareto_state=pareto_state,
        source_kind="SYNTHETIC_TEST",
    )

    candidate_fingerprint = canonical_fingerprint(
        {"candidate_id": candidate_id, "operation": operation, "deltas": deltas}
    )
    feature_fingerprint = canonical_fingerprint(features)

    return CandidateExposure(
        review_id=review_id,
        candidate_id=candidate_id,
        candidate_fingerprint=candidate_fingerprint,
        operation=operation,
        original_rank=original_rank,
        displayed_rank=displayed_rank,
        shown_to_reviewer=shown_to_reviewer,
        deterministic_eligibility=deterministic_eligibility,
        hard_gate_status=hard_gate_status,
        pareto_state=pareto_state,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_payload=features,
        feature_fingerprint=feature_fingerprint,
        created_at=created_at,
    )


def generate_synthetic_review_group(
    *,
    review_id: str,
    chain_id: str = "chain-syn-100",
    lineage_component_id: str = "lineage-syn-1",
    review_time: str = "2026-09-01T10:00:00Z",
    scenario: str = "STANDARD_TOP1_APPROVED",
    truth_tier: TruthTier = TruthTier.TEST_FIXTURE,
    reviewer_subject: str = "operator:tester",
    feedback_time: str | None = None,
) -> tuple[ReviewSession, list[CandidateExposure], list[ReviewFeedback]]:
    """Factory to generate structured synthetic review groups for pipeline testing."""
    fb_time = feedback_time or review_time

    session = ReviewSession(
        review_id=review_id,
        job_id=f"job-{review_id}",
        snapshot_id=f"snap-{review_id}",
        snapshot_version="v1",
        chain_id=chain_id,
        review_time=review_time,
        source_kind="SYNTHETIC_TEST",
        lineage_component_id=lineage_component_id,
        candidate_set_fingerprint=canonical_fingerprint({"review_id": review_id}),
        generator_version="v1",
        config_version="v1",
        created_at=review_time,
    )

    exposures: list[CandidateExposure] = []
    feedbacks: list[ReviewFeedback] = []

    if scenario == "STANDARD_TOP1_APPROVED":
        # 4 candidates: c1 approved, c2, c3, c4 rejected
        ops = ["REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS"]
        for idx, op in enumerate(ops, 1):
            cand_id = f"{review_id}-cand-{idx}"
            exp = create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=cand_id,
                operation=op,
                original_rank=idx,
                displayed_rank=idx,
                created_at=review_time,
            )
            exposures.append(exp)

            # c1 approved, others rejected
            dec = ReviewDecision.APPROVE if idx == 1 else ReviewDecision.REJECT
            feedbacks.append(
                ReviewFeedback(
                    feedback_id=f"fb-{cand_id}",
                    review_id=review_id,
                    candidate_id=cand_id,
                    decision=dec,
                    confidence=0.95 if dec is ReviewDecision.APPROVE else 0.85,
                    truth_tier=truth_tier,
                    reviewer_subject=reviewer_subject,
                    created_at=fb_time,
                )
            )

    elif scenario == "NONE_ACCEPTABLE":
        # All candidates rejected / none acceptable
        for idx in range(1, 4):
            cand_id = f"{review_id}-cand-{idx}"
            exp = create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=cand_id,
                operation="REMOVE_MEMBER",
                original_rank=idx,
                displayed_rank=idx,
                created_at=review_time,
            )
            exposures.append(exp)

        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{review_id}-none",
                review_id=review_id,
                candidate_id=None,
                decision=ReviewDecision.NONE_ACCEPTABLE,
                confidence=1.0,
                truth_tier=truth_tier,
                reviewer_subject=reviewer_subject,
                reason_codes=("ALL_PROPOSALS_VIOLATE_SERVICE_DOMAIN",),
                created_at=fb_time,
            )
        )

    elif scenario == "MANUAL_CORRECTION":
        # Operator rejected proposals and provided manual partition delta
        cand_id = f"{review_id}-cand-1"
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=cand_id,
                operation="MOVE_MEMBER",
                original_rank=1,
                displayed_rank=1,
                created_at=review_time,
            )
        )
        correction = ManualCorrection(
            correction_id=f"corr-{review_id}",
            feedback_id=f"fb-{review_id}-corr",
            operation="MOVE_MEMBER",
            partition_delta={"moved_alarms": ["alm-1"], "target_chain": "chain-syn-200"},
            correction_fingerprint=canonical_fingerprint({"moved": ["alm-1"]}),
            created_at=fb_time,
        )
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{review_id}-corr",
                review_id=review_id,
                candidate_id=None,
                decision=ReviewDecision.MANUAL_CORRECTION,
                confidence=1.0,
                truth_tier=truth_tier,
                reviewer_subject=reviewer_subject,
                manual_correction=correction,
                created_at=fb_time,
            )
        )

    elif scenario == "UNREVIEWED_AND_SUPERSEDED":
        # 3 candidates:
        # c1 initially rejected, then superseded with APPROVE
        # c2 rejected
        # c3 unreviewed (must NOT be assigned label)
        c1 = f"{review_id}-cand-1"
        c2 = f"{review_id}-cand-2"
        c3 = f"{review_id}-cand-3"
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id, candidate_id=c1, operation="REMOVE_MEMBER", original_rank=1, created_at=review_time
            )
        )
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id, candidate_id=c2, operation="SPLIT_CHAIN", original_rank=2, created_at=review_time
            )
        )
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id, candidate_id=c3, operation="MOVE_MEMBER", original_rank=3, created_at=review_time
            )
        )

        old_fb_time = (
            datetime.datetime.fromisoformat(review_time.replace("Z", "+00:00"))
            + datetime.timedelta(minutes=1)
        ).isoformat()
        new_fb_time = (
            datetime.datetime.fromisoformat(review_time.replace("Z", "+00:00"))
            + datetime.timedelta(minutes=5)
        ).isoformat()

        # Older superseded feedback
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c1}-v1",
                review_id=review_id,
                candidate_id=c1,
                decision=ReviewDecision.REJECT,
                confidence=0.7,
                truth_tier=truth_tier,
                status=FeedbackStatus.SUPERSEDED,
                created_at=old_fb_time,
            )
        )
        # Active superseding feedback
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c1}-v2",
                review_id=review_id,
                candidate_id=c1,
                decision=ReviewDecision.APPROVE,
                confidence=0.9,
                truth_tier=truth_tier,
                status=FeedbackStatus.ACTIVE,
                supersedes_feedback_id=f"fb-{c1}-v1",
                created_at=new_fb_time,
            )
        )
        # c2 rejected
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c2}",
                review_id=review_id,
                candidate_id=c2,
                decision=ReviewDecision.REJECT,
                confidence=0.8,
                truth_tier=truth_tier,
                status=FeedbackStatus.ACTIVE,
                created_at=new_fb_time,
            )
        )
        # c3 has no feedback -> unreviewed!

    elif scenario in {"SUBOPTIMAL_TOP1_RANK2_APPROVED", "RANK2_APPROVED"}:
        # Candidate 1 (original rank 1): REMOVE_MEMBER, large metric improvement BUT excessive blast radius, REJECTED
        c1 = f"{review_id}-cand-1"
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=c1,
                operation="REMOVE_MEMBER",
                original_rank=1,
                displayed_rank=1,
                metric_deltas={
                    "weak_member_count": -5.0,
                    "minimum_membership_support": 0.50,
                    "evidence_union_coverage": 0.25,
                    "component_count": 0.0,
                    "audit_conductance": 0.85,
                    "audit_verdict_severity": -1.0,
                },
                edit_cost={
                    "members_moved": 8,
                    "chains_created": 2,
                    "chains_removed": 1,
                },
                temporal_available=True,
                case_available=True,
                created_at=review_time,
            )
        )
        # Candidate 2 (original rank 2): SPLIT_CHAIN, solid improvement with low blast radius, APPROVED
        c2 = f"{review_id}-cand-2"
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=c2,
                operation="SPLIT_CHAIN",
                original_rank=2,
                displayed_rank=2,
                metric_deltas={
                    "weak_member_count": -2.0,
                    "minimum_membership_support": 0.35,
                    "evidence_union_coverage": 0.15,
                    "component_count": 1.0,
                    "audit_conductance": 0.40,
                    "audit_verdict_severity": -1.0,
                },
                edit_cost={
                    "members_moved": 1,
                    "chains_created": 0,
                    "chains_removed": 0,
                },
                temporal_available=True,
                case_available=True,
                created_at=review_time,
            )
        )
        # Candidate 3 (original rank 3): MOVE_MEMBER, REJECTED
        c3 = f"{review_id}-cand-3"
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=c3,
                operation="MOVE_MEMBER",
                original_rank=3,
                displayed_rank=3,
                metric_deltas={
                    "weak_member_count": 0.0,
                    "minimum_membership_support": 0.02,
                    "evidence_union_coverage": 0.0,
                    "component_count": 0.0,
                    "audit_conductance": 0.0,
                    "audit_verdict_severity": 0.0,
                },
                temporal_available=True,
                case_available=True,
                created_at=review_time,
            )
        )
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c1}",
                review_id=review_id,
                candidate_id=c1,
                decision=ReviewDecision.REJECT,
                confidence=0.8,
                truth_tier=truth_tier,
                reviewer_subject=reviewer_subject,
                created_at=fb_time,
            )
        )
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c2}",
                review_id=review_id,
                candidate_id=c2,
                decision=ReviewDecision.APPROVE,
                confidence=0.95,
                truth_tier=truth_tier,
                reviewer_subject=reviewer_subject,
                created_at=fb_time,
            )
        )
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c3}",
                review_id=review_id,
                candidate_id=c3,
                decision=ReviewDecision.REJECT,
                confidence=0.85,
                truth_tier=truth_tier,
                reviewer_subject=reviewer_subject,
                created_at=fb_time,
            )
        )

    elif scenario == "RANK3_APPROVED_MOVE_PREFERRED":
        c1 = f"{review_id}-cand-1"
        c2 = f"{review_id}-cand-2"
        c3 = f"{review_id}-cand-3"
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id, candidate_id=c1, operation="REMOVE_MEMBER", original_rank=1, created_at=review_time
            )
        )
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id, candidate_id=c2, operation="SPLIT_CHAIN", original_rank=2, created_at=review_time
            )
        )
        exposures.append(
            create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=c3,
                operation="MOVE_MEMBER",
                original_rank=3,
                displayed_rank=3,
                metric_deltas={
                    "weak_member_count": -3.0,
                    "minimum_membership_support": 0.40,
                    "evidence_union_coverage": 0.25,
                    "component_count": 0.0,
                    "audit_conductance": 0.50,
                    "audit_verdict_severity": -2.0,
                },
                created_at=review_time,
            )
        )
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c1}",
                review_id=review_id,
                candidate_id=c1,
                decision=ReviewDecision.REJECT,
                confidence=0.8,
                truth_tier=truth_tier,
                created_at=fb_time,
            )
        )
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c2}",
                review_id=review_id,
                candidate_id=c2,
                decision=ReviewDecision.REJECT,
                confidence=0.8,
                truth_tier=truth_tier,
                created_at=fb_time,
            )
        )
        feedbacks.append(
            ReviewFeedback(
                feedback_id=f"fb-{c3}",
                review_id=review_id,
                candidate_id=c3,
                decision=ReviewDecision.APPROVE,
                confidence=0.95,
                truth_tier=truth_tier,
                created_at=fb_time,
            )
        )

    elif scenario == "MISSING_FEATURES":
        # Candidate with missing temporal and case evidence
        for idx in range(1, 3):
            cand_id = f"{review_id}-cand-{idx}"
            exp = create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=cand_id,
                operation="REMOVE_MEMBER",
                original_rank=idx,
                temporal_available=False,
                case_available=False,
                created_at=review_time,
            )
            exposures.append(exp)
            dec = ReviewDecision.APPROVE if idx == 1 else ReviewDecision.REJECT
            feedbacks.append(
                ReviewFeedback(
                    feedback_id=f"fb-{cand_id}",
                    review_id=review_id,
                    candidate_id=cand_id,
                    decision=dec,
                    confidence=0.9,
                    truth_tier=truth_tier,
                    reviewer_subject=reviewer_subject,
                    created_at=fb_time,
                )
            )

    elif scenario == "UNIFORM_LABELS":
        # All candidates approved -> no preference gradient
        for idx in range(1, 3):
            cand_id = f"{review_id}-cand-{idx}"
            exp = create_synthetic_candidate_exposure(
                review_id=review_id, candidate_id=cand_id, original_rank=idx, created_at=review_time
            )
            exposures.append(exp)
            feedbacks.append(
                ReviewFeedback(
                    feedback_id=f"fb-{cand_id}",
                    review_id=review_id,
                    candidate_id=cand_id,
                    decision=ReviewDecision.APPROVE,
                    confidence=0.9,
                    truth_tier=truth_tier,
                    reviewer_subject=reviewer_subject,
                    created_at=fb_time,
                )
            )

    elif scenario == "DUPLICATE_LINEAGE":
        # Group with explicit duplicated lineage components across operations
        ops = ["REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER"]
        for idx, op in enumerate(ops, 1):
            cand_id = f"{review_id}-cand-{idx}"
            exp = create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=cand_id,
                operation=op,
                original_rank=idx,
                displayed_rank=idx,
                created_at=review_time,
            )
            exposures.append(exp)
            dec = ReviewDecision.APPROVE if idx == 1 else ReviewDecision.REJECT
            feedbacks.append(
                ReviewFeedback(
                    feedback_id=f"fb-{cand_id}",
                    review_id=review_id,
                    candidate_id=cand_id,
                    decision=dec,
                    confidence=0.9,
                    truth_tier=truth_tier,
                    reviewer_subject=reviewer_subject,
                    created_at=fb_time,
                )
            )

    elif scenario == "FEATURE_TAMPERING":
        # Group containing a tampered candidate with mismatched feature fingerprint
        ops = ["REMOVE_MEMBER", "SPLIT_CHAIN"]
        for idx, op in enumerate(ops, 1):
            cand_id = f"{review_id}-cand-{idx}"
            exp = create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=cand_id,
                operation=op,
                original_rank=idx,
                displayed_rank=idx,
                created_at=review_time,
            )
            if idx == 1:
                # Tamper with the fingerprint hash
                exp = dataclasses.replace(exp, feature_fingerprint="tampered_hash_bad_sha256_deadbeef")
            exposures.append(exp)
            dec = ReviewDecision.APPROVE if idx == 1 else ReviewDecision.REJECT
            feedbacks.append(
                ReviewFeedback(
                    feedback_id=f"fb-{cand_id}",
                    review_id=review_id,
                    candidate_id=cand_id,
                    decision=dec,
                    confidence=0.9,
                    truth_tier=truth_tier,
                    reviewer_subject=reviewer_subject,
                    created_at=fb_time,
                )
            )

    elif scenario == "RETRACTED_FEEDBACK":
        # Group with candidate whose feedback was subsequently retracted
        ops = ["REMOVE_MEMBER", "SPLIT_CHAIN"]
        for idx, op in enumerate(ops, 1):
            cand_id = f"{review_id}-cand-{idx}"
            exp = create_synthetic_candidate_exposure(
                review_id=review_id,
                candidate_id=cand_id,
                operation=op,
                original_rank=idx,
                displayed_rank=idx,
                created_at=review_time,
            )
            exposures.append(exp)
            feedbacks.append(
                ReviewFeedback(
                    feedback_id=f"fb-{cand_id}",
                    review_id=review_id,
                    candidate_id=cand_id,
                    decision=ReviewDecision.APPROVE,
                    confidence=0.9,
                    truth_tier=truth_tier,
                    status=FeedbackStatus.RETRACTED if idx == 1 else FeedbackStatus.ACTIVE,
                    reviewer_subject=reviewer_subject,
                    created_at=fb_time,
                )
            )

    return session, exposures, feedbacks


def generate_synthetic_review_corpus(
    group_count: int = 30,
    base_date: str = "2026-09-01T10:00:00Z",
) -> tuple[list[ReviewSession], list[CandidateExposure], list[ReviewFeedback]]:
    """Generate a multi-group synthetic corpus with distinct lineages over time.

    Guarantees:
    - Every group has an independent lineage_component_id so chronological splitting
      (train / val / test) does not cause lineage holdout starvation.
    - Balanced mix of scenarios (standard approved, suboptimal top1 where rank 2 or 3
      is preferred, unreviewed & superseded, missing features, none acceptable).
    - Monotonically advancing timestamps across the group sequence.
    """
    sessions: list[ReviewSession] = []
    exposures: list[CandidateExposure] = []
    feedbacks: list[ReviewFeedback] = []

    base_dt = datetime.datetime.fromisoformat(base_date.replace("Z", "+00:00"))
    scenarios = [
        "STANDARD_TOP1_APPROVED",
        "SUBOPTIMAL_TOP1_RANK2_APPROVED",
        "UNREVIEWED_AND_SUPERSEDED",
        "RANK3_APPROVED_MOVE_PREFERRED",
        "MISSING_FEATURES",
        "NONE_ACCEPTABLE",
    ]

    for i in range(1, group_count + 1):
        scenario = scenarios[(i - 1) % len(scenarios)]
        dt = (base_dt + datetime.timedelta(hours=i * 6)).isoformat()
        lin = f"lineage-syn-{i:03d}"
        s, e, f = generate_synthetic_review_group(
            review_id=f"rev-syn-{i:03d}",
            chain_id=f"chain-syn-{i:03d}",
            lineage_component_id=lin,
            review_time=dt,
            scenario=scenario,
        )
        sessions.append(s)
        exposures.extend(e)
        feedbacks.extend(f)

    return sessions, exposures, feedbacks

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from fastapi import HTTPException
import pytest

from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.review_principal import ReviewerPrincipal
from review_learning.contracts import ReviewDecision, TruthTier


@dataclass
class DummyJobView:
    job_id: str
    chain_id: str
    result: Any
    identity: dict
    review_domain: str = "IP_NETWORK"


@pytest.mark.anyio
async def test_freeze_review_bundle_captures_all_evaluated_candidates():
    service = ReviewLearningService()

    cand1 = {
        "candidate_id": "c1",
        "operation": "REMOVE",
        "hard_gate_passed": True,
        "recommended": True,
        "raw_score": 0.85,
        "partition_delta": {"removed_alarms": ["a2"]},
    }
    cand2 = {
        "candidate_id": "c2",
        "operation": "SPLIT",
        "hard_gate_passed": True,
        "recommended": False,  # dominated
        "raw_score": 0.40,
        "partition_delta": {"partitions": [["a1"], ["a2"]]},
    }
    cand3 = {
        "candidate_id": "c3",
        "operation": "MERGE",
        "hard_gate_passed": False,  # hard gate rejected
        "hard_gate_failures": ["COHESION_DEGRADED"],
        "recommended": False,
        "raw_score": 0.10,
        "partition_delta": {},
    }

    job_view = DummyJobView(
        job_id="job_exposure_1",
        chain_id="chain_1",
        result={
            "chain_id": "chain_1",
            "recommendations": [cand1],
            "evaluated_candidates": [cand1, cand2, cand3],
        },
        identity={"snapshot_id": "s1", "snapshot_version": "v1"},
    )

    session = await service.freeze_review_bundle(
        job_id="job_exposure_1",
        job_view=job_view,
        package=None,
        delay_model=None,
        taxonomy=None,
    )

    assert session.review_id == "rev_job_exposure_1"
    assert session.exposure_policy == "ALL_EVALUATED"

    exposures = service._exposures[session.review_id]
    assert len(exposures) == 3

    # Check eligibility flags
    exp1 = next(e for e in exposures if e.candidate_id == "c1")
    assert exp1.deterministic_eligibility == "HARD_GATES_PASSED"
    assert exp1.hard_gate_status == "PASSED"
    assert exp1.pareto_state == "FRONTIER_SELECTED"

    exp2 = next(e for e in exposures if e.candidate_id == "c2")
    assert exp2.deterministic_eligibility == "DOMINATED"
    assert exp2.hard_gate_status == "PASSED"
    assert exp2.pareto_state == "DOMINATED"

    exp3 = next(e for e in exposures if e.candidate_id == "c3")
    assert exp3.deterministic_eligibility == "HARD_GATE_REJECTED"
    assert exp3.hard_gate_status == "REJECTED"
    assert exp3.pareto_state == "INELIGIBLE"


@pytest.mark.anyio
async def test_display_events_and_feedback_lifecycle_in_service():
    service = ReviewLearningService()
    cand1 = {
        "candidate_id": "c1",
        "operation": "REMOVE",
        "hard_gate_passed": True,
        "recommended": True,
        "partition_delta": {"removed_alarms": ["a2"]},
    }
    job_view = DummyJobView(
        job_id="job_lifecycle_1",
        chain_id="chain_1",
        result={"chain_id": "chain_1", "recommendations": [cand1], "evaluated_candidates": [cand1]},
        identity={"snapshot_id": "s1", "snapshot_version": "v1"},
        review_domain="IP_NETWORK",
    )
    await service.freeze_review_bundle(
        job_id="job_lifecycle_1",
        job_view=job_view,
        package=None,
    )

    principal = ReviewerPrincipal(
        subject="po_alice",
        role="PRODUCT_OWNER",
        domain_scope=("IP_NETWORK",),
        auth_type="LOCAL_DEV",
    )

    # 1. Record display event (1-based rank)
    count = await service.record_display_events(
        job_id="job_lifecycle_1",
        events_payload=[
            {
                "candidate_id": "c1",
                "displayed_rank": 1,
                "exposure_policy": "ALL_EVALUATED",
                "surface": "VALIDATION_VIEW_TOP_CARD",
                "rendered_at": "2026-09-11T08:00:00Z",
                "client_event_id": "evt_test_1",
            }
        ],
        principal=principal,
    )
    assert count == 1
    assert len(service._display_events) == 1

    # 1b. Test rejection of 0-based rank
    with pytest.raises(ValueError):
        await service.record_display_events(
            job_id="job_lifecycle_1",
            events_payload=[
                {
                    "candidate_id": "c1",
                    "displayed_rank": 0,
                    "surface": "VALIDATION_VIEW_TOP_CARD",
                }
            ],
            principal=principal,
        )

    # 2. Record feedback
    fb = await service.record_feedback(
        job_id="job_lifecycle_1",
        submission={
            "candidate_id": "c1",
            "decision": "APPROVE",
            "confidence": 0.95,
            "reason_code": "PLAUSIBLE_SUBGRAPH",
            "reason": "Good partition",
        },
        principal=principal,
    )
    assert fb.decision == ReviewDecision.APPROVE
    assert fb.reviewer_subject == "po_alice"
    assert fb.truth_tier == TruthTier.PO_ASSERTED
    assert len(service._active_feedbacks) == 1

    # 3. Supersede feedback
    fb2 = await service.supersede_feedback(
        job_id="job_lifecycle_1",
        supersedes_feedback_id=fb.feedback_id,
        submission={
            "candidate_id": "c1",
            "decision": "REJECT",
            "confidence": 0.8,
            "reason_code": "INCORRECT_PARTITION",
            "reason": "Changed my mind",
        },
        principal=principal,
    )
    assert fb2.decision == ReviewDecision.REJECT
    assert fb2.supersedes_feedback_id == fb.feedback_id
    assert fb.feedback_id not in service._active_feedbacks
    assert fb2.feedback_id in service._active_feedbacks

    # 4. Retract feedback
    await service.retract_feedback(
        job_id="job_lifecycle_1",
        feedback_id=fb2.feedback_id,
        principal=principal,
        reason="Retracted decision",
    )
    assert fb2.feedback_id not in service._active_feedbacks

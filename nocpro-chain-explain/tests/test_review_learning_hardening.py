from __future__ import annotations

import os
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from review_learning.contracts import (
    validate_manual_correction,
    ReviewDecision,
    ImmutableReviewSnapshotContext,
    ImmutableReviewConflict,
    UnknownExposureCandidate,
)
from nocpro_api.review_principal import (
    ReviewerPrincipal,
    get_reviewer_principal,
)
from nocpro_api.schemas import OperatorFeedbackSubmission
from nocpro_api.review_learning_service import ReviewLearningService
from fastapi import HTTPException


class DummyJobView:
    def __init__(self, job_id: str, chain_id: str, result: dict, identity: dict = None, review_domain: str = "IP_NETWORK"):
        self.job_id = job_id
        self.chain_id = chain_id
        self.result = result
        self.identity = identity or {"snapshot_id": "snap_1", "snapshot_version": "v1"}
        self.generator_version = "v1"
        self.lineage_component_id = "comp_1"
        self.review_domain = review_domain


# --------------------------------------------------------------------------
# 1. Manual Correction Validation Tests
# --------------------------------------------------------------------------

def test_manual_split_conservation_success():
    validate_manual_correction(
        operation="MANUAL_SPLIT",
        partition_delta={
            "after": [
                ["chain_1", ["alarm_1", "alarm_2"]],
                ["chain_1::split_1", ["alarm_3"]],
            ]
        },
        server_chain_alarms=["alarm_1", "alarm_2", "alarm_3"],
    )


def test_manual_split_missing_alarm_fails_conservation():
    with pytest.raises(ValueError, match="Alarm universe conservation violated"):
        validate_manual_correction(
            operation="MANUAL_SPLIT",
            partition_delta={
                "after": [
                    ["chain_1", ["alarm_1"]],
                    ["chain_1::split_1", ["alarm_2"]],
                ]
            },
            server_chain_alarms=["alarm_1", "alarm_2", "alarm_3"],  # alarm_3 dropped
        )


def test_manual_split_duplicate_alarm_fails():
    with pytest.raises(ValueError, match="duplicate alarm assignments"):
        validate_manual_correction(
            operation="MANUAL_SPLIT",
            partition_delta={
                "after": [
                    ["chain_1", ["alarm_1", "alarm_2"]],
                    ["chain_1::split_1", ["alarm_2", "alarm_3"]],  # alarm_2 duplicated
                ]
            },
            server_chain_alarms=["alarm_1", "alarm_2", "alarm_3"],
        )


def test_manual_split_duplicate_partition_ids_fail():
    with pytest.raises(ValueError, match="partition IDs must be unique"):
        validate_manual_correction(
            operation="MANUAL_SPLIT",
            partition_delta={
                "after": [
                    ["chain_1", ["alarm_1"]],
                    ["chain_1", ["alarm_2"]],  # Duplicate ID
                ]
            },
            server_chain_alarms=["alarm_1", "alarm_2"],
        )


def test_manual_correction_disallowed_operation_fails():
    with pytest.raises(ValueError, match="not an allowed manual correction operation"):
        validate_manual_correction(
            operation="DELETE_UNSAFE",
            partition_delta={"after": [["chain_1", ["alarm_1"]]]},
            server_chain_alarms=["alarm_1"],
        )


def test_manual_correction_invalid_reason_code_fails():
    with pytest.raises(ValueError, match="not in the active policy"):
        validate_manual_correction(
            operation="MANUAL_SPLIT",
            partition_delta={
                "after": [
                    ["chain_1", ["alarm_1"]],
                    ["chain_2", ["alarm_2"]],
                ]
            },
            server_chain_alarms=["alarm_1", "alarm_2"],
            allowed_reason_codes=["PLAUSIBLE_SUBGRAPH", "INCORRECT_PARTITION"],
            submitted_reason_code="UNKNOWN_HACK_REASON",
        )


def test_manual_remove_requires_unassigned_partition():
    validate_manual_correction(
        operation="MANUAL_REMOVE",
        partition_delta={
            "after": [
                ["chain_1", ["alarm_1"]],
                ["UNASSIGNED", ["alarm_2"]],
            ]
        },
        server_chain_alarms=["alarm_1", "alarm_2"],
    )


# --------------------------------------------------------------------------
# 2. Concurrency & Single-Insert Supersede Tests
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_supersede_feedback_single_insert_lifecycle():
    service = ReviewLearningService()
    cand = {
        "candidate_id": "cand_1",
        "operation": "REMOVE",
        "hard_gate_passed": True,
        "recommended": True,
    }
    job_view = DummyJobView(
        job_id="job_sup_1",
        chain_id="chain_1",
        result={"chain_id": "chain_1", "recommendations": [cand], "evaluated_candidates": [cand]},
        review_domain="IP_NETWORK",
    )
    await service.freeze_review_bundle(job_id="job_sup_1", job_view=job_view, package=None)

    principal = ReviewerPrincipal(
        subject="po_alice",
        role="PRODUCT_OWNER",
        domain_scope=("IP_NETWORK",),
        auth_type="LOCAL_DEV",
    )

    # Initial feedback
    fb1 = await service.record_feedback(
        job_id="job_sup_1",
        submission={"candidate_id": "cand_1", "decision": "APPROVE"},
        principal=principal,
    )
    assert fb1.feedback_id in service._active_feedbacks

    # Supersede feedback
    fb2 = await service.supersede_feedback(
        job_id="job_sup_1",
        supersedes_feedback_id=fb1.feedback_id,
        submission={"candidate_id": "cand_1", "decision": "REJECT"},
        principal=principal,
    )

    # fb1 should be deleted from active, fb2 should be active
    assert fb1.feedback_id not in service._active_feedbacks
    assert fb2.feedback_id in service._active_feedbacks
    assert fb2.supersedes_feedback_id == fb1.feedback_id
    assert fb2.decision == ReviewDecision.REJECT


# --------------------------------------------------------------------------
# 3. Candidate Display Events Validation Tests
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_display_events_validation_rules():
    service = ReviewLearningService()
    cands = [
        {"candidate_id": "cand_1", "operation": "REMOVE", "hard_gate_passed": True, "recommended": True},
        {"candidate_id": "cand_2", "operation": "SPLIT", "hard_gate_passed": True, "recommended": False},
    ]
    job_view = DummyJobView(
        job_id="job_disp_val",
        chain_id="chain_1",
        result={"chain_id": "chain_1", "recommendations": [cands[0]], "evaluated_candidates": cands},
        review_domain="IP_NETWORK",
    )
    await service.freeze_review_bundle(job_id="job_disp_val", job_view=job_view, package=None)
    disp_principal = ReviewerPrincipal(
        subject="po_alice",
        role="PRODUCT_OWNER",
        domain_scope=("IP_NETWORK",),
        auth_type="LOCAL_DEV",
    )

    # 1. displayed_rank < 1 fails
    with pytest.raises((ValueError, HTTPException)):
        await service.record_display_events(
            job_id="job_disp_val",
            events_payload=[{"candidate_id": "cand_1", "displayed_rank": 0}],
            principal=disp_principal,
        )

    # 2. displayed_rank > candidate count fails
    with pytest.raises((ValueError, HTTPException)):
        await service.record_display_events(
            job_id="job_disp_val",
            events_payload=[{"candidate_id": "cand_1", "displayed_rank": 3}],  # max is 2
            principal=disp_principal,
        )

    # 3. Unknown candidate_id fails
    with pytest.raises((UnknownExposureCandidate, HTTPException)):
        await service.record_display_events(
            job_id="job_disp_val",
            events_payload=[{"candidate_id": "cand_unknown", "displayed_rank": 1}],
            principal=disp_principal,
        )

    # 4. Duplicate (surface, displayed_rank) fails
    with pytest.raises((ValueError, HTTPException)):
        await service.record_display_events(
            job_id="job_disp_val",
            events_payload=[
                {"candidate_id": "cand_1", "displayed_rank": 1, "surface": "TOP_CARD"},
                {"candidate_id": "cand_2", "displayed_rank": 1, "surface": "TOP_CARD"},
            ],
            principal=disp_principal,
        )

    # 5. Batch size > 50 fails
    with pytest.raises((ValueError, HTTPException)):
        await service.record_display_events(
            job_id="job_disp_val",
            events_payload=[{"candidate_id": "cand_1", "displayed_rank": 1}] * 51,
            principal=disp_principal,
        )

    # 6. Valid batch succeeds
    count = await service.record_display_events(
        job_id="job_disp_val",
        events_payload=[
            {"candidate_id": "cand_1", "displayed_rank": 1, "surface": "TOP_CARD", "client_event_id": "e1"},
            {"candidate_id": "cand_2", "displayed_rank": 2, "surface": "TOP_CARD", "client_event_id": "e2"},
        ],
        principal=disp_principal,
    )
    assert count == 2


# --------------------------------------------------------------------------
# 4. Identity & Schema Security (Fail-Closed, extra='forbid')
# --------------------------------------------------------------------------

def test_submission_schema_forbids_extra_fields():
    # operator_id in body must be rejected with ValidationError (extra="forbid")
    with pytest.raises(ValidationError):
        OperatorFeedbackSubmission.model_validate({
            "candidate_id": "cand_1",
            "decision": "APPROVE",
            "operator_id": "spoofed_operator",
        })


def test_production_fails_closed_when_identity_disabled():
    old_env = os.environ.get("APP_ENV")
    old_mode = os.environ.get("REVIEW_IDENTITY_MODE")
    try:
        os.environ["APP_ENV"] = "production"
        os.environ["REVIEW_IDENTITY_MODE"] = "DISABLED"

        class MockRequest:
            headers = {}
            client = type("Client", (), {"host": "127.0.0.1"})()

        with pytest.raises(HTTPException) as exc:
            get_reviewer_principal(MockRequest())
        assert exc.value.status_code == 503
        assert "DISABLED" in exc.value.detail
    finally:
        if old_env is not None:
            os.environ["APP_ENV"] = old_env
        else:
            os.environ.pop("APP_ENV", None)
        if old_mode is not None:
            os.environ["REVIEW_IDENTITY_MODE"] = old_mode
        else:
            os.environ.pop("REVIEW_IDENTITY_MODE", None)


# --------------------------------------------------------------------------
# 5. Feature Snapshot Round-Trip & Replay Conflict Detection
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_feature_snapshot_and_replay_conflict():
    service = ReviewLearningService()
    cand = {
        "candidate_id": "cand_replay",
        "operation": "REMOVE",
        "hard_gate_passed": True,
        "recommended": True,
        "partition_delta": {"removed_alarms": ["a1"]},
    }
    job_view = DummyJobView(
        job_id="job_replay_1",
        chain_id="chain_1",
        result={"chain_id": "chain_1", "recommendations": [cand], "evaluated_candidates": [cand]},
    )

    ctx = ImmutableReviewSnapshotContext(
        snapshot_id="snap_replay",
        snapshot_version="v1",
        chain_id="chain_1",
        review_time=datetime.now(timezone.utc),
    )

    session1 = await service.freeze_review_bundle(
        job_id="job_replay_1",
        job_view=job_view,
        package=None,
        context=ctx,
    )
    assert session1.review_id in service._sessions
    exposures = service._exposures[session1.review_id]
    assert len(exposures) == 1
    assert exposures[0].feature_schema_version == "cf-features-v1"
    assert "exact_metrics" in exposures[0].feature_payload
    assert "temporal_features" in exposures[0].feature_payload
    assert "availability_flags" in exposures[0].feature_payload

    # Replay with same context is idempotent
    session2 = await service.freeze_review_bundle(
        job_id="job_replay_1",
        job_view=job_view,
        package=None,
        context=ctx,
    )
    assert session2.review_id == session1.review_id

    # Replay with mismatched candidates/features raises 409 conflict
    mismatched_cand = {
        "candidate_id": "cand_replay",
        "operation": "SPLIT",  # Changed operation alters feature fingerprint
        "hard_gate_passed": True,
        "recommended": True,
        "partition_delta": {"partitions": [["a1"], ["a2"]]},
    }
    job_view_mismatched = DummyJobView(
        job_id="job_replay_1",
        chain_id="chain_1",
        result={"chain_id": "chain_1", "recommendations": [mismatched_cand], "evaluated_candidates": [mismatched_cand]},
    )
    with pytest.raises((ImmutableReviewConflict, HTTPException)) as exc:
        await service.freeze_review_bundle(
            job_id="job_replay_1",
            job_view=job_view_mismatched,
            package=None,
            context=ctx,
        )
    assert "differing candidate set fingerprint" in str(exc.value)

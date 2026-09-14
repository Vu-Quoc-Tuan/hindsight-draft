from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import httpx2
import pytest

from configuration import load_analysis_config
from nocpro_api import create_app
from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.review_principal import ReviewerPrincipal
from nocpro_api.workspace import Workspace
from review_learning.contracts import (
    CandidateExposure,
    ImmutableReviewConflict,
    ManualCorrection,
    ReviewDecision,
    ReviewSession,
    validate_manual_correction,
)

pytestmark = pytest.mark.anyio


def _make_session_and_target_exposure(
    review_id: str = "rev_mc_test",
    job_id: str = "job_mc_test",
    source_chain_id: str = "chain_src_1",
    target_chain_id: str = "chain_tgt_2",
) -> tuple[ReviewSession, list[CandidateExposure]]:
    now = datetime.now(timezone.utc)
    session = ReviewSession(
        review_id=review_id,
        job_id=job_id,
        snapshot_id="snap_mc_1",
        snapshot_version="1",
        chain_id=source_chain_id,
        review_time=now,
        source_kind="OPERATOR_REVIEW",
        review_domain="IP_NETWORK",
        lineage_component_id="comp_mc_1",
        candidate_set_fingerprint="cs_fp_mc",
        generator_version="v1",
        config_version="v1",
        exposure_policy="ALL_EVALUATED",
    )
    # Candidate 1: MOVE operation bound to target_chain_id
    exp_move = CandidateExposure(
        review_id=review_id,
        candidate_id="cand_move_1",
        candidate_fingerprint="fp_move_1",
        operation="MOVE",
        original_rank=1,
        displayed_rank=1,
        deterministic_eligibility="HARD_GATES_PASSED",
        hard_gate_status="PASSED",
        pareto_state="FRONTIER_SELECTED",
        deterministic_context={
            "benefit": 3.0,
            "partition_delta": {
                "before": {source_chain_id: ["a1", "a2"], target_chain_id: ["b1", "b2"]},
                "after": {source_chain_id: ["a1"], target_chain_id: ["a2", "b1", "b2"]},
            },
            "frozen_universe": {
                "source_chain_id": source_chain_id,
                "source_alarm_ids": ["a1", "a2"],
                "target_chain_id": target_chain_id,
                "target_alarm_ids": ["b1", "b2"],
                "snapshot_id": "snap_mc_1",
                "snapshot_version": "1",
            },
        },
        case_context={"domain": "IP_NETWORK"},
        feature_schema_version="cf-features-v1",
        feature_payload={"exact_metrics": {"benefit": 3.0}},
    )
    # Candidate 2: SPLIT operation without target chain
    exp_split = CandidateExposure(
        review_id=review_id,
        candidate_id="cand_split_2",
        candidate_fingerprint="fp_split_2",
        operation="SPLIT",
        original_rank=2,
        displayed_rank=2,
        deterministic_eligibility="HARD_GATES_PASSED",
        hard_gate_status="PASSED",
        pareto_state="FRONTIER_SELECTED",
        deterministic_context={
            "benefit": 2.0,
            "partition_delta": {
                "before": [["a1", "a2"]],
                "after": [["a1"], ["a2"]],
            },
            "frozen_universe": {
                "source_chain_id": source_chain_id,
                "source_alarm_ids": ["a1", "a2"],
                "target_chain_id": None,
                "target_alarm_ids": [],
                "snapshot_id": "snap_mc_1",
                "snapshot_version": "1",
            },
        },
        case_context={"domain": "IP_NETWORK"},
        feature_schema_version="cf-features-v1",
        feature_payload={"exact_metrics": {"benefit": 2.0}},
    )
    return session, [exp_move, exp_split]


def _reviewer_principal() -> ReviewerPrincipal:
    return ReviewerPrincipal(
        subject="expert_reviewer_1",
        role="PRODUCT_OWNER",
        domain_scope=("IP_NETWORK",),
        auth_type="TEST",
    )


def test_validate_manual_correction_contracts_enforcement():
    source_alarms = ["a1", "a2"]
    target_alarms = ["b1", "b2"]

    # 1. MANUAL_SPLIT rejects target_chain_id
    with pytest.raises(ValueError, match="MANUAL_SPLIT must not specify target_chain_id"):
        validate_manual_correction(
            operation="MANUAL_SPLIT",
            partition_delta={"after": [["a1"], ["a2"]]},
            server_chain_alarms=source_alarms,
            target_chain_id="chain_tgt_2",
        )

    # 2. MANUAL_REMOVE rejects target_chain_id
    with pytest.raises(ValueError, match="MANUAL_REMOVE must not specify target_chain_id"):
        validate_manual_correction(
            operation="MANUAL_REMOVE",
            partition_delta={"after": [("REMAINING", ["a1"]), ("UNASSIGNED", ["a2"])]},
            server_chain_alarms=source_alarms,
            target_chain_id="chain_tgt_2",
        )

    # 3. MANUAL_MOVE before must use exact keys {source_chain_id, target_chain_id}
    with pytest.raises(ValueError, match="MANUAL_MOVE before partitions must use exact keys"):
        validate_manual_correction(
            operation="MANUAL_MOVE",
            partition_delta={
                "before": {"arbitrary_src": ["a1", "a2"], "arbitrary_tgt": ["b1", "b2"]},
                "after": {"chain_src_1": ["a1"], "chain_tgt_2": ["a2", "b1", "b2"]},
            },
            server_chain_alarms=source_alarms,
            server_target_chain_alarms=target_alarms,
            source_chain_id="chain_src_1",
            target_chain_id="chain_tgt_2",
        )

    # 4. MANUAL_MOVE after must use exact keys {source_chain_id, target_chain_id}
    with pytest.raises(ValueError, match="MANUAL_MOVE after partitions must use exact keys"):
        validate_manual_correction(
            operation="MANUAL_MOVE",
            partition_delta={
                "before": {"chain_src_1": ["a1", "a2"], "chain_tgt_2": ["b1", "b2"]},
                "after": {"wrong_src": ["a1"], "wrong_tgt": ["a2", "b1", "b2"]},
            },
            server_chain_alarms=source_alarms,
            server_target_chain_alarms=target_alarms,
            source_chain_id="chain_src_1",
            target_chain_id="chain_tgt_2",
        )

    # 5. MANUAL_MERGE destination key must match source, target, or source+target
    with pytest.raises(ValueError, match="MANUAL_MERGE destination partition key must be one of"):
        validate_manual_correction(
            operation="MANUAL_MERGE",
            partition_delta={
                "before": {"chain_src_1": ["a1", "a2"], "chain_tgt_2": ["b1", "b2"]},
                "after": {"arbitrary_merged_chain": ["a1", "a2", "b1", "b2"]},
            },
            server_chain_alarms=source_alarms,
            server_target_chain_alarms=target_alarms,
            source_chain_id="chain_src_1",
            target_chain_id="chain_tgt_2",
        )


async def test_service_rejects_manual_split_with_target_chain():
    service = ReviewLearningService()
    session, exposures = _make_session_and_target_exposure()
    service.register_persisted_bundle(session, exposures)

    with pytest.raises(ValueError, match="MANUAL_SPLIT must not specify target_chain_id"):
        await service.record_feedback(
            job_id="job_mc_test",
            submission={
                "candidate_id": "cand_split_2",
                "decision": "MANUAL_CORRECTION",
                "reason_code": "MANUAL_TOPOLOGY_SPLIT",
                "manual_correction": {
                    "operation": "MANUAL_SPLIT",
                    "target_chain_id": "chain_tgt_2",  # Forbidden on split!
                    "partition_delta": {
                        "partitions": [["a1"], ["a2"]],
                    },
                },
            },
            principal=_reviewer_principal(),
        )


async def test_service_rejects_mismatched_target_chain_id_with_conflict():
    service = ReviewLearningService()
    session, exposures = _make_session_and_target_exposure(
        source_chain_id="chain_src_1", target_chain_id="chain_tgt_2"
    )
    service.register_persisted_bundle(session, exposures)

    # Client tries to claim target_chain_id is "attacker_chain_99" when candidate is frozen to "chain_tgt_2"
    with pytest.raises(ImmutableReviewConflict, match="conflicts with frozen target_chain_id"):
        await service.record_feedback(
            job_id="job_mc_test",
            submission={
                "candidate_id": "cand_move_1",
                "decision": "MANUAL_CORRECTION",
                "reason_code": "MANUAL_DOMAIN_PARTITION",
                "manual_correction": {
                    "operation": "MANUAL_MOVE",
                    "target_chain_id": "attacker_chain_99",
                    "partition_delta": {
                        "before": {"chain_src_1": ["a1", "a2"], "attacker_chain_99": ["b1", "b2"]},
                        "after": {"chain_src_1": ["a1"], "attacker_chain_99": ["a2", "b1", "b2"]},
                    },
                },
            },
            principal=_reviewer_principal(),
        )


async def test_service_accepts_valid_manual_move_matching_candidate_frozen_universe():
    service = ReviewLearningService()
    session, exposures = _make_session_and_target_exposure(
        source_chain_id="chain_src_1", target_chain_id="chain_tgt_2"
    )
    service.register_persisted_bundle(session, exposures)

    # Valid manual move matching the candidate's exact frozen target chain
    fb = await service.record_feedback(
        job_id="job_mc_test",
        submission={
            "candidate_id": "cand_move_1",
            "decision": "MANUAL_CORRECTION",
            "reason_code": "MANUAL_DOMAIN_PARTITION",
            "manual_correction": {
                "operation": "MANUAL_MOVE",
                "target_chain_id": "chain_tgt_2",
                "partition_delta": {
                    "before": {"chain_src_1": ["a1", "a2"], "chain_tgt_2": ["b1", "b2"]},
                    "after": {"chain_src_1": ["a1"], "chain_tgt_2": ["a2", "b1", "b2"]},
                },
            },
        },
        principal=_reviewer_principal(),
    )
    assert fb.manual_correction is not None
    assert fb.manual_correction.operation == "MANUAL_MOVE"
    assert fb.manual_correction.partition_delta["after"]["chain_tgt_2"] == ["a2", "b1", "b2"]


async def test_manual_correction_http_api_validation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")

    ws = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    session, exposures = _make_session_and_target_exposure(
        source_chain_id="chain_src_1", target_chain_id="chain_tgt_2"
    )
    ws.review_learning.register_persisted_bundle(session, exposures)

    mock_job = type(
        "MockJob",
        (),
        {
            "job_id": session.job_id,
            "chain_id": session.chain_id,
            "review_domain": "IP_NETWORK",
            "completed_at": datetime.now(timezone.utc),
            "source_kind": "REAL_LIVE",
            "lineage_component_id": "comp_mc_1",
            "identity": {
                "snapshot_id": "snap_mc_1",
                "snapshot_version": "1",
                "chain_id": session.chain_id,
                "domain": "IP_NETWORK",
            },
            "result": {
                "identity": {
                    "snapshot_id": "snap_mc_1",
                    "snapshot_version": "1",
                    "chain_id": session.chain_id,
                    "domain": "IP_NETWORK",
                },
                "evaluated_candidates": [
                    {"candidate_id": "cand_move_1", "operation": "MOVE"},
                    {"candidate_id": "cand_split_2", "operation": "SPLIT"},
                ],
                "recommendations": [
                    {"candidate_id": "cand_move_1", "operation": "MOVE"},
                ],
            },
        },
    )()
    ws.review_jobs.get = lambda jid: mock_job

    app = create_app(workspace=ws)
    transport = httpx2.ASGITransport(app=app)

    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # A. Conflict (409) on target chain mismatch
        resp_conflict = await client.post(
            f"/api/v1/review-jobs/{session.job_id}/feedback",
            json={
                "candidate_id": "cand_move_1",
                "decision": "MANUAL_CORRECTION",
                "reason_code": "MANUAL_DOMAIN_PARTITION",
                "manual_correction": {
                    "operation": "MANUAL_MOVE",
                    "target_chain_id": "unrelated_chain_x",
                    "partition_delta": {
                        "before": {"chain_src_1": ["a1", "a2"], "unrelated_chain_x": ["b1", "b2"]},
                        "after": {"chain_src_1": ["a1"], "unrelated_chain_x": ["a2", "b1", "b2"]},
                    },
                },
            },
            headers={"X-Dev-Operator-Id": "expert_reviewer_1", "X-Dev-Operator-Role": "PRODUCT_OWNER", "X-Dev-Domain-Scope": "IP_NETWORK"},
        )
        assert resp_conflict.status_code == 409
        assert "conflicts with frozen target_chain_id" in resp_conflict.json()["detail"]

        # B. Unprocessable (422) on arbitrary partition keys
        resp_bad_keys = await client.post(
            f"/api/v1/review-jobs/{session.job_id}/feedback",
            json={
                "candidate_id": "cand_move_1",
                "decision": "MANUAL_CORRECTION",
                "reason_code": "MANUAL_DOMAIN_PARTITION",
                "manual_correction": {
                    "operation": "MANUAL_MOVE",
                    "target_chain_id": "chain_tgt_2",
                    "partition_delta": {
                        "before": {"arbitrary_1": ["a1", "a2"], "arbitrary_2": ["b1", "b2"]},
                        "after": {"arbitrary_1": ["a1"], "arbitrary_2": ["a2", "b1", "b2"]},
                    },
                },
            },
            headers={"X-Dev-Operator-Id": "expert_reviewer_1", "X-Dev-Operator-Role": "PRODUCT_OWNER", "X-Dev-Domain-Scope": "IP_NETWORK"},
        )
        assert resp_bad_keys.status_code == 422
        assert "exact keys" in resp_bad_keys.json()["detail"]

        # C. Success (201) on correct target chain and exact keys
        resp_success = await client.post(
            f"/api/v1/review-jobs/{session.job_id}/feedback",
            json={
                "candidate_id": "cand_move_1",
                "decision": "MANUAL_CORRECTION",
                "reason_code": "MANUAL_DOMAIN_PARTITION",
                "manual_correction": {
                    "operation": "MANUAL_MOVE",
                    "target_chain_id": "chain_tgt_2",
                    "partition_delta": {
                        "before": {"chain_src_1": ["a1", "a2"], "chain_tgt_2": ["b1", "b2"]},
                        "after": {"chain_src_1": ["a1"], "chain_tgt_2": ["a2", "b1", "b2"]},
                    },
                },
            },
            headers={"X-Dev-Operator-Id": "expert_reviewer_1", "X-Dev-Operator-Role": "PRODUCT_OWNER", "X-Dev-Domain-Scope": "IP_NETWORK"},
        )
        assert resp_success.status_code == 201
        data = resp_success.json()
        assert data["decision"] in ("MANUAL_CORRECTION", "MANUAL")
        assert data["has_manual_correction"] is True
        assert data["partition_delta"]["after"]["chain_tgt_2"] == ["a2", "b1", "b2"]

        # D. Success (201) on manual split without specifying candidate_id
        resp_split = await client.post(
            f"/api/v1/review-jobs/{session.job_id}/feedback",
            json={
                "decision": "MANUAL_CORRECTION",
                "reason_code": "MANUAL_TOPOLOGY_SPLIT",
                "manual_correction": {
                    "operation": "MANUAL_SPLIT",
                    "partition_delta": {
                        "before": [["chain_src_1", ["a1", "a2"]]],
                        "after": [
                            ["chain_src_1", ["a1"]],
                            ["chain_src_1::partition_custom", ["a2"]],
                        ],
                    },
                    "edit_summary": "Manual split of a2 into new partition",
                },
            },
            headers={"X-Dev-Operator-Id": "expert_reviewer_1", "X-Dev-Operator-Role": "PRODUCT_OWNER", "X-Dev-Domain-Scope": "IP_NETWORK"},
        )
        assert resp_split.status_code == 201
        split_data = resp_split.json()
        assert split_data["decision"] in ("MANUAL_CORRECTION", "MANUAL")
        assert split_data["has_manual_correction"] is True
        assert split_data["operation"] == "MANUAL_SPLIT"

    ws.close()

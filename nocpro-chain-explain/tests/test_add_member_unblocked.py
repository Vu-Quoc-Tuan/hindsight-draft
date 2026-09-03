"""Test unblocked ADD_MEMBER in counterfactual review."""

from __future__ import annotations

from tier2.counterfactual.candidates import generate_add_candidates
from tier2.counterfactual.models import (
    CandidateBatch,
    DomainStatus,
    EditCost,
    Operation,
    PartitionDelta,
    ReviewIdentity,
    SearchMode,
)
from tier2.counterfactual.public_contract import public_review_result


def test_operation_enum_includes_add_member() -> None:
    assert Operation.ADD_MEMBER.value == "ADD_MEMBER"


def test_generate_add_candidates_from_singleton_chains() -> None:
    identity = ReviewIdentity(
        snapshot_id="SNAP_1",
        snapshot_version="1",
        chain_id="C1",
        alarm_universe_fingerprint="fp1",
        analysis_version="v1",
        engine_version="v1",
        config_version="v1",
        tier1b_artifact_fingerprint="t1b",
    )
    singleton_members = {
        "C_SINGLE_1": "ALM_ORPHAN_1",
        "C_SINGLE_2": "ALM_ORPHAN_2",
    }
    batch = generate_add_candidates(
        identity,
        chain_id="C1",
        members=("ALM_CORE_1", "ALM_CORE_2"),
        singleton_members=singleton_members,
        limit=5,
    )

    assert batch.operation == Operation.ADD_MEMBER
    assert batch.discovered_count == 2
    assert len(batch.candidates) == 2

    c1 = batch.candidates[0]
    assert c1.operation == Operation.ADD_MEMBER
    assert c1.edit_cost == EditCost(1, 1, 1)
    assert c1.source_chain_id in singleton_members
    assert c1.member_ids[0] in singleton_members.values()
    assert "ALM_CORE_1" in c1.partition_delta.after[0][1]
    assert c1.member_ids[0] in c1.partition_delta.after[0][1]


def test_public_contract_unblocks_add_member() -> None:
    identity = ReviewIdentity(
        snapshot_id="SNAP_1",
        snapshot_version="1",
        chain_id="C1",
        alarm_universe_fingerprint="fp1",
        analysis_version="v1",
        engine_version="v1",
        config_version="v1",
        tier1b_artifact_fingerprint="t1",
        structural_audit_artifact_fingerprint=None,
        external_validation_artifact_fingerprint=None,
    )

    class DummyResult:
        calibration_status = "CALIBRATED_REAL_DATA"
        status = DomainStatus.AVAILABLE
        reason = None
        recommendation_status = DomainStatus.AVAILABLE
        recommendations = ()
        frontier_count_before_limit = 0
        frontier_truncated = False
        frontier_candidate_ids = frozenset()
        parameter_provenance = {}
        remove = None
        split = None
        move = None
        merge = None

    dummy = DummyResult()
    dummy.identity = identity
    dummy.remove = _operation_res(Operation.REMOVE_MEMBER)
    dummy.split = _operation_res(Operation.SPLIT_CHAIN)
    dummy.move = _operation_res(Operation.MOVE_MEMBER)
    dummy.merge = _operation_res(Operation.MERGE_CHAINS)

    payload = public_review_result(dummy)
    assert "ADD_MEMBER" in payload["operation_status"]
    add_status = payload["operation_status"]["ADD_MEMBER"]
    assert add_status["status"] == "READY"
    assert add_status["reason"] == "NO_SINGLETON_CANDIDATES"


def _operation_res(op: Operation):
    from tier2.counterfactual.models import OperationResult
    return OperationResult(
        operation=op,
        status=DomainStatus.AVAILABLE,
        reason=None,
        search_mode=SearchMode.BOUNDED,
        discovered_candidate_count=0,
        evaluated_candidate_count=0,
        rejected_candidate_count=0,
        candidate_limit=10,
        candidates=(),
    )

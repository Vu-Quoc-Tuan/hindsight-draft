"""ADD_MEMBER remains a public blocked capability under the current partition contract."""

from __future__ import annotations

from tier2.counterfactual.models import (
    DomainStatus,
    Operation,
    ReviewIdentity,
    SearchMode,
)
from tier2.counterfactual.public_contract import public_review_result


def test_add_member_is_not_a_domain_operation() -> None:
    assert "ADD_MEMBER" not in {operation.value for operation in Operation}


def test_public_contract_keeps_add_member_blocked_even_for_calibrated_result() -> None:
    identity = ReviewIdentity(
        snapshot_id="SNAP_1",
        snapshot_version="1",
        chain_id="C1",
        alarm_universe_fingerprint="fp1",
        analysis_version="v1",
        engine_version="v1",
        config_version="v1",
        tier1b_artifact_fingerprint="t1",
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

    dummy = DummyResult()
    dummy.identity = identity
    dummy.remove = _operation_res(Operation.REMOVE_MEMBER)
    dummy.split = _operation_res(Operation.SPLIT_CHAIN)
    dummy.move = _operation_res(Operation.MOVE_MEMBER)
    dummy.merge = _operation_res(Operation.MERGE_CHAINS)

    add_status = public_review_result(dummy)["operation_status"]["ADD_MEMBER"]
    assert add_status == {
        "status": "BLOCKED",
        "reason": "UNKNOWN_UPSTREAM_SEMANTICS",
        "search_mode": "NOT_RUN",
        "candidate_count": 0,
        "evaluated_count": 0,
        "ceiling": None,
    }


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

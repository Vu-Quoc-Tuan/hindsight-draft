from __future__ import annotations

from tier2.counterfactual.public_contract import review_evaluation_completed


def test_review_with_zero_candidates_is_complete_when_all_searches_finished():
    operations = {
        name: {
            "status": "AVAILABLE",
            "search_mode": "BOUNDED",
            "candidate_count": 0,
            "evaluated_count": 0,
        }
        for name in ("REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS")
    }

    assert review_evaluation_completed(operations) is True


def test_review_is_incomplete_if_any_applicable_operation_did_not_run():
    operations = {
        name: {"status": "AVAILABLE", "search_mode": "BOUNDED"}
        for name in ("REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS")
    }
    operations["MERGE_CHAINS"] = {
        "status": "UNAVAILABLE",
        "search_mode": "NOT_RUN",
    }

    assert review_evaluation_completed(operations) is False


def test_not_applicable_operations_are_complete_but_missing_legacy_states_fail_closed():
    operations = {
        "REMOVE_MEMBER": {"status": "NOT_APPLICABLE", "search_mode": "NOT_RUN"},
        "SPLIT_CHAIN": {"status": "AVAILABLE", "search_mode": "BOUNDED"},
        "MOVE_MEMBER": {"status": "AVAILABLE", "search_mode": "BOUNDED"},
        "MERGE_CHAINS": {"status": "AVAILABLE", "search_mode": "BOUNDED"},
    }

    assert review_evaluation_completed(operations) is True
    assert review_evaluation_completed({"REMOVE_MEMBER": operations["REMOVE_MEMBER"]}) is False

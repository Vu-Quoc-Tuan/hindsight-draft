from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from benchmarks.benchmark_counterfactual import adjusted_mutual_info, adjusted_rand_index
from configuration import load_analysis_config
from libs.contracts import load_validated_package
from tier1b import analyze_chain_configured
from tier2 import Tier2JobManager
from tier2.counterfactual import CounterfactualJobManager, CounterfactualJobView
from tier2.counterfactual.jobs import JobStatus
from tier2.counterfactual.public_contract import public_review_result


MOCK_SYNTHETIC = (
    Path(__file__).resolve().parents[2]
    / "nocpro-mock"
    / "docs"
    / "examples"
    / "synthetic"
)
CONFIG = "config/thresholds/e2e-counterfactual.yaml"


def _run(payload, chain_id):
    package = load_validated_package(payload)
    config = load_analysis_config(CONFIG)
    tier1b = analyze_chain_configured(package, chain_id, analysis_config=config)
    with Tier2JobManager() as audit_jobs:
        audit_submission = audit_jobs.submit(
            package, chain_id, analysis_config=config
        )
        audit = audit_jobs.wait(audit_submission.job_id).result
    manager = CounterfactualJobManager()
    try:
        submission = manager.submit(
            package,
            chain_id,
            tier1b_artifact=tier1b,
            audit_artifact=audit,
            analysis_config=config,
        )
        return manager.wait(submission.job_id).result
    finally:
        manager.shutdown()


def run_fixture(name: str):
    directory = MOCK_SYNTHETIC / name
    payload = json.loads((directory / "snapshot_000.json").read_text())
    expected = yaml.safe_load((directory / "expected_assertions.yaml").read_text())
    return _run(payload, expected["mutated_chain_id"]), expected


@pytest.mark.parametrize(
    "name",
    [
        "counterfactual_remove",
        "counterfactual_split",
        "counterfactual_move",
        "counterfactual_merge",
    ],
)
def test_fixture_contract_is_explicitly_synthetic(name: str) -> None:
    payload = json.loads((MOCK_SYNTHETIC / name / "snapshot_000.json").read_text())
    expected = yaml.safe_load(
        (MOCK_SYNTHETIC / name / "expected_assertions.yaml").read_text()
    )
    assert payload["snapshot"]["source_kind"] == "SYNTHETIC_TEST"
    assert expected["validation_scope"] == "SYNTHETIC_CORRECTNESS_ONLY"
    assert "scenario_id=" + expected["scenario_id"] in payload["provenance_manifest"]["notes"]


def test_extra_member_mutation_recommends_expected_remove() -> None:
    result, expected = run_fixture("counterfactual_remove")
    assert result.recommendations
    recommendation = result.recommendations[0].candidate
    assert recommendation.operation.value == expected["expected_review"]["operation"]
    assert list(recommendation.member_ids) == expected["expected_review"]["member_ids"]


def test_overmerge_mutation_recommends_expected_split() -> None:
    result, expected = run_fixture("counterfactual_split")
    assert result.recommendations
    recommendation = result.recommendations[0].candidate
    assert recommendation.operation.value == expected["expected_review"]["operation"]
    proposed = {
        frozenset(members)
        for _, members in recommendation.partition_delta.after
    }
    truth = {
        frozenset(members) for members in expected["truth_partition"].values()
    }
    assert proposed == truth


def test_misassigned_member_move_is_an_accepted_pareto_recommendation() -> None:
    result, expected = run_fixture("counterfactual_move")
    review = expected["expected_review"]
    matching = [
        evaluation
        for evaluation in result.recommendations
        if evaluation.candidate.operation.value == review["operation"]
        and list(evaluation.candidate.member_ids) == review["member_ids"]
        and evaluation.candidate.source_chain_id == review["source_chain_id"]
        and evaluation.candidate.target_chain_id == review["target_chain_id"]
    ]

    assert matching, "expected MOVE_MEMBER was absent from the Pareto frontier"
    candidate = matching[0]
    assert candidate.status.value in {"BETTER_SUPPORTED", "EXTERNALLY_SUPPORTED"}
    assert dict(candidate.candidate.partition_delta.after) == {
        chain_id: tuple(sorted(members))
        for chain_id, members in expected["truth_partition"].items()
    }


def test_undermerge_mutation_is_an_accepted_pareto_merge_recommendation() -> None:
    result, expected = run_fixture("counterfactual_merge")
    review = expected["expected_review"]
    matching = [
        evaluation
        for evaluation in result.recommendations
        if evaluation.candidate.operation.value == review["operation"]
        and list(evaluation.candidate.merged_chain_ids or ())
        == review["merged_chain_ids"]
    ]

    assert matching, "expected MERGE_CHAINS was absent from the Pareto frontier"
    candidate = matching[0]
    assert candidate.status.value in {"BETTER_SUPPORTED", "EXTERNALLY_SUPPORTED"}
    assert candidate.candidate.edit_cost.membership_reassignments == 0
    assert candidate.candidate.merge_evidence is not None
    assert candidate.candidate.merge_evidence.cross_audit_edge_count >= 1


@pytest.mark.parametrize(
    "name, expected_operation",
    [
        ("counterfactual_remove", "REMOVE_MEMBER"),
        ("counterfactual_split", "SPLIT_CHAIN"),
        ("counterfactual_move", "MOVE_MEMBER"),
        ("counterfactual_merge", "MERGE_CHAINS"),
    ],
)
def test_public_contract_v1_is_persistence_stable_for_each_operation(
    name: str, expected_operation: str
) -> None:
    result, _expected = run_fixture(name)
    public = public_review_result(result)
    persisted = CounterfactualJobView(
        job_id="review-contract-test",
        chain_id=result.identity.chain_id,
        identity=result.identity,
        status=JobStatus.SUCCEEDED,
        progress_percent=100,
        cache_hit=False,
        result=result,
    ).persistence_payload()["result"]

    assert public == persisted
    assert public["contract_version"] == "counterfactual-review-v1"
    assert public["calibration_status"] == "SYNTHETIC_ONLY"
    assert public["operation_status"]["ADD_MEMBER"]["status"] == "BLOCKED"
    assert public["operation_status"]["ADD_MEMBER"]["reason"] == "UNKNOWN_UPSTREAM_SEMANTICS"
    candidate_ids = [item["candidate_id"] for item in public["evaluated_candidates"]]
    assert len(candidate_ids) == len(set(candidate_ids))
    assert all(
        item["candidate_id"] in candidate_ids for item in public["recommendations"]
    )
    expected = next(
        item for item in public["evaluated_candidates"] if item["operation"] == expected_operation
    )
    assert expected["metric_deltas"]
    assert expected["hard_gate_result"]["status"] == "PASSED"
    assert expected["pareto_state"] == "FRONTIER_SELECTED"
    assert expected["external_validation"] == "UNAVAILABLE"


def test_clean_truth_partition_abstains() -> None:
    directory = MOCK_SYNTHETIC / "counterfactual_remove"
    payload = json.loads((directory / "snapshot_000.json").read_text())
    expected = yaml.safe_load((directory / "expected_assertions.yaml").read_text())
    template = payload["chains"][0]
    payload["chains"] = [
        {**template, "chain_id": chain_id, "member_count": len(members)}
        for chain_id, members in expected["truth_partition"].items()
    ]
    membership_template = payload["memberships"][0]
    payload["memberships"] = [
        {**membership_template, "chain_id": chain_id, "alarm_id": alarm_id}
        for chain_id, members in expected["truth_partition"].items()
        for alarm_id in members
    ]

    result = _run(payload, "SYN-CHAIN-REMOVE-TRUTH")
    assert result.recommendations == ()
    assert result.recommendation_status.value == "NO_CLEAR_ALTERNATIVE"


def test_partition_benchmark_metrics_are_label_invariant() -> None:
    truth = ["A", "A", "B", "B"]
    renamed = ["left", "left", "right", "right"]
    assert adjusted_rand_index(truth, renamed) == pytest.approx(1.0)
    assert adjusted_mutual_info(truth, renamed) == pytest.approx(1.0)

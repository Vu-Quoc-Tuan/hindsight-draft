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
from tier2.counterfactual import CounterfactualJobManager


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


@pytest.mark.parametrize("name", ["counterfactual_remove", "counterfactual_split"])
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

"""Deterministic synthetic correctness/latency benchmark for Review P0.

This benchmark is not production calibration evidence.  It measures the two
explicitly-labelled mutation fixtures and one clean truth partition only.
"""

from __future__ import annotations

from collections import Counter
from math import comb, log
import json
from pathlib import Path
import statistics
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services/analysis-worker"))

from configuration import load_analysis_config
from libs.contracts import load_validated_package
from tier1b import analyze_chain_configured
from tier2 import Tier2JobManager
from tier2.counterfactual import CounterfactualJobManager


FIXTURES = ROOT.parent / "nocpro-mock" / "docs/examples/synthetic"
CONFIG = load_analysis_config(ROOT / "config/thresholds/e2e-counterfactual.yaml")


def _labels(partition, universe):
    owner = {
        alarm_id: chain_id
        for chain_id, members in partition
        for alarm_id in members
    }
    return [owner[alarm_id] for alarm_id in universe]


def adjusted_rand_index(truth, predicted) -> float:
    n = len(truth)
    if n < 2:
        return 1.0
    truth_counts = Counter(truth)
    predicted_counts = Counter(predicted)
    cells = Counter(zip(truth, predicted, strict=True))
    pairs = comb(n, 2)
    cell_sum = sum(comb(value, 2) for value in cells.values())
    truth_sum = sum(comb(value, 2) for value in truth_counts.values())
    predicted_sum = sum(comb(value, 2) for value in predicted_counts.values())
    expected = truth_sum * predicted_sum / pairs
    maximum = (truth_sum + predicted_sum) / 2
    return 1.0 if maximum == expected else (cell_sum - expected) / (maximum - expected)


def _entropy(counts, n):
    return -sum((value / n) * log(value / n) for value in counts.values() if value)


def _same_partition(truth, predicted) -> bool:
    """Compare cluster assignments without treating cluster labels as truth.

    A merge commonly creates a counterfactual chain identifier, so an all-one
    cluster truth/prediction pair has zero entropy while its labels naturally
    differ.  The degenerate AMI branch must preserve the same label-invariant
    partition semantics as the ordinary branch.
    """
    if len(truth) != len(predicted):
        return False
    truth_to_predicted = {}
    predicted_to_truth = {}
    for truth_label, predicted_label in zip(truth, predicted, strict=True):
        if truth_to_predicted.setdefault(truth_label, predicted_label) != predicted_label:
            return False
        if predicted_to_truth.setdefault(predicted_label, truth_label) != truth_label:
            return False
    return True


def adjusted_mutual_info(truth, predicted) -> float:
    """AMI with the arithmetic entropy mean, matching the common definition."""
    n = len(truth)
    truth_counts = Counter(truth)
    predicted_counts = Counter(predicted)
    cells = Counter(zip(truth, predicted, strict=True))
    mutual_info = sum(
        (value / n)
        * log((value * n) / (truth_counts[left] * predicted_counts[right]))
        for (left, right), value in cells.items()
        if value
    )
    expected_mi = 0.0
    for left_count in truth_counts.values():
        for right_count in predicted_counts.values():
            lower = max(1, left_count + right_count - n)
            upper = min(left_count, right_count)
            hypergeom_denominator = comb(n, right_count)
            for overlap in range(lower, upper + 1):
                probability = (
                    comb(left_count, overlap)
                    * comb(n - left_count, right_count - overlap)
                    / hypergeom_denominator
                )
                expected_mi += probability * (overlap / n) * log(
                    (overlap * n) / (left_count * right_count)
                )
    normalizer = (
        _entropy(truth_counts, n) + _entropy(predicted_counts, n)
    ) / 2 - expected_mi
    if abs(normalizer) < 1e-15:
        return 1.0 if _same_partition(truth, predicted) else 0.0
    return (mutual_info - expected_mi) / normalizer


def _review(payload, chain_id):
    package = load_validated_package(payload)
    tier1b = analyze_chain_configured(package, chain_id, analysis_config=CONFIG)
    with Tier2JobManager() as audit_jobs:
        audit_submission = audit_jobs.submit(
            package, chain_id, analysis_config=CONFIG
        )
        audit = audit_jobs.wait(audit_submission.job_id).result
    review_jobs = CounterfactualJobManager()
    try:
        submission = review_jobs.submit(
            package,
            chain_id,
            tier1b_artifact=tier1b,
            audit_artifact=audit,
            analysis_config=CONFIG,
        )
        return review_jobs.wait(submission.job_id).result
    finally:
        review_jobs.shutdown()


def _fixture(name):
    directory = FIXTURES / name
    return (
        json.loads((directory / "snapshot_000.json").read_text()),
        yaml.safe_load((directory / "expected_assertions.yaml").read_text()),
    )


def _expected_recommendation(result, expected):
    """Return the frozen synthetic operation, without imposing a rank policy.

    MOVE is intentionally required to be present on the bounded Pareto
    frontier, not necessarily the first recommendation.  Use the same
    operation-specific identity asserted by the regression suite so this
    benchmark measures fixture correctness rather than presentation ordering.
    """
    review = expected["expected_review"]
    operation = review["operation"]
    for evaluation in result.recommendations:
        candidate = evaluation.candidate
        if candidate.operation.value != operation:
            continue
        if operation in {"REMOVE_MEMBER", "MOVE_MEMBER"} and list(
            candidate.member_ids
        ) != review.get("member_ids", []):
            continue
        if operation == "MOVE_MEMBER" and (
            candidate.source_chain_id != review["source_chain_id"]
            or candidate.target_chain_id != review["target_chain_id"]
        ):
            continue
        if operation == "MERGE_CHAINS" and list(
            candidate.merged_chain_ids or ()
        ) != review["merged_chain_ids"]:
            continue
        return evaluation
    return None


def _clean_remove_payload(payload, expected):
    clean = json.loads(json.dumps(payload))
    template = clean["chains"][0]
    clean["chains"] = [
        {**template, "chain_id": chain_id, "member_count": len(members)}
        for chain_id, members in expected["truth_partition"].items()
    ]
    membership_template = clean["memberships"][0]
    clean["memberships"] = [
        {**membership_template, "chain_id": chain_id, "alarm_id": alarm_id}
        for chain_id, members in expected["truth_partition"].items()
        for alarm_id in members
    ]
    return clean


def run(repetitions: int = 5) -> dict:
    cases = []
    mutation_detected = 0
    repairs_exact = 0
    latencies = []
    ari_values = []
    ami_values = []
    member_level_reassignments = []
    fixture_names = (
        "counterfactual_remove",
        "counterfactual_split",
        "counterfactual_move",
        "counterfactual_merge",
    )
    for name in fixture_names:
        payload, expected = _fixture(name)
        runs = []
        result = None
        for _ in range(repetitions):
            started = time.perf_counter()
            result = _review(payload, expected["mutated_chain_id"])
            runs.append(time.perf_counter() - started)
        assert result is not None
        latencies.extend(runs)
        recommendation = _expected_recommendation(result, expected)
        detected = recommendation is not None
        mutation_detected += int(detected)
        truth_partition = tuple(
            (chain_id, tuple(members))
            for chain_id, members in expected["truth_partition"].items()
        )
        predicted_partition = (
            recommendation.candidate.partition_delta.after
            if recommendation is not None
            else ((expected["mutated_chain_id"], tuple(
                membership["alarm_id"] for membership in payload["memberships"]
            )),)
        )
        truth_sets = {frozenset(members) for _, members in truth_partition}
        predicted_sets = {frozenset(members) for _, members in predicted_partition}
        exact = truth_sets == predicted_sets
        repairs_exact += int(exact)
        universe = sorted({item for _, members in truth_partition for item in members})
        truth_labels = _labels(truth_partition, universe)
        predicted_labels = _labels(predicted_partition, universe)
        ari = adjusted_rand_index(truth_labels, predicted_labels)
        ami = adjusted_mutual_info(truth_labels, predicted_labels)
        ari_values.append(ari)
        ami_values.append(ami)
        member_level_reassignment_count = (
            recommendation.candidate.edit_cost.membership_reassignments
            if recommendation is not None
            else 0
        )
        member_level_reassignments.append(member_level_reassignment_count)
        cases.append({
            "fixture": name,
            "detected": detected,
            "repair_exact": exact,
            "operation": recommendation.candidate.operation.value if recommendation else None,
            "member_level_reassignments": member_level_reassignment_count,
            "ari": ari,
            "ami": ami,
            "latency_seconds": runs,
        })

    remove_payload, remove_expected = _fixture("counterfactual_remove")
    clean_result = _review(
        _clean_remove_payload(remove_payload, remove_expected),
        "SYN-CHAIN-REMOVE-TRUTH",
    )
    clean_abstained = not clean_result.recommendations
    return {
        "scope": "SYNTHETIC_CORRECTNESS_ONLY",
        "config_version": CONFIG.counterfactual.config_version,
        "case_count": len(fixture_names),
        "issue_detection_accuracy": mutation_detected / len(fixture_names),
        "repair_accuracy": repairs_exact / len(fixture_names),
        "false_recommendation_rate": 0.0 if clean_abstained else 1.0,
        "clean_abstention_rate": 1.0 if clean_abstained else 0.0,
        "mean_member_level_reassignments": statistics.mean(
            member_level_reassignments
        ),
        "mean_ari": statistics.mean(ari_values),
        "mean_ami": statistics.mean(ami_values),
        "latency_p50_seconds": statistics.median(latencies),
        "latency_max_seconds": max(latencies),
        "repetitions_per_mutation": repetitions,
        "cases": cases,
        "production_calibration": "NOT_ESTABLISHED",
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))

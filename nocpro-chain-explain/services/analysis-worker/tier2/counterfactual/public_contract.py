"""Stable, persistence-safe Counterfactual Review public contract v1."""

from __future__ import annotations

from dataclasses import asdict

from .models import CandidateStatus, CounterfactualResult, DomainStatus, Operation


CONTRACT_VERSION = "counterfactual-review-v1"


def _metric(value):
    return {"availability": value.availability.value, "value": value.value, "reason": value.reason}


def _metrics(vector):
    if vector is None:
        return None
    return {
        name: _metric(getattr(vector, name))
        for name in (
            "weak_member_count", "minimum_membership_support",
            "evidence_union_coverage", "component_count", "audit_conductance",
            "audit_verdict_severity", "eligible_external_contradiction_count",
        )
    }


def _operation_status(operation):
    return {
        "status": operation.status.value,
        "reason": operation.reason,
        "search_mode": (
            "BOUNDED_LOCAL_CANDIDATES"
            if operation.search_mode.value == "BOUNDED"
            and operation.operation in {Operation.MOVE_MEMBER, Operation.MERGE_CHAINS}
            else operation.search_mode.value
        ),
        "candidate_count": operation.discovered_candidate_count,
        "evaluated_count": operation.evaluated_candidate_count,
        "ceiling": operation.candidate_limit,
    }


def _pareto_state(evaluation, result: CounterfactualResult, selected: set[str]) -> str:
    if evaluation.status in {
        CandidateStatus.HARD_GATE_REJECTED,
        CandidateStatus.EXTERNALLY_CONTRADICTED,
    }:
        return "INELIGIBLE"
    candidate_id = evaluation.candidate.candidate_id
    if candidate_id in selected:
        return "FRONTIER_SELECTED"
    if candidate_id in result.frontier_candidate_ids:
        return "FRONTIER_TRUNCATED"
    if evaluation.status in {CandidateStatus.BETTER_SUPPORTED, CandidateStatus.EXTERNALLY_SUPPORTED}:
        return "DOMINATED"
    return "NOT_EVALUATED"


def _candidate(evaluation, result: CounterfactualResult, selected: set[str]):
    candidate = evaluation.candidate
    hard_gate_passed = evaluation.status not in {
        CandidateStatus.HARD_GATE_REJECTED,
        CandidateStatus.EXTERNALLY_CONTRADICTED,
    }
    return {
        "candidate_id": candidate.candidate_id,
        "operation": candidate.operation.value,
        "partition_delta": {
            "before": [(chain_id, list(members)) for chain_id, members in candidate.partition_delta.before],
            "after": [(chain_id, list(members)) for chain_id, members in candidate.partition_delta.after],
        },
        "edit_cost": asdict(candidate.edit_cost),
        "before_metrics": _metrics(evaluation.before),
        "after_metrics": _metrics(evaluation.after),
        "metric_deltas": dict(evaluation.metric_deltas),
        "hard_gate_result": {
            "status": "PASSED" if hard_gate_passed else "REJECTED",
            "reason": None if hard_gate_passed else evaluation.reason,
        },
        "pareto_state": _pareto_state(evaluation, result, selected),
        "external_validation": evaluation.external_validation,
        "semantic_effects": [item.value for item in evaluation.semantic_effects],
        "structural_facts": asdict(evaluation.move_structural_facts) if evaluation.move_structural_facts else None,
        "operation_specific_evidence": dict(candidate.operation_evidence),
        "debug_source_ref": candidate.source_ref,
        "evaluation_status": evaluation.status.value,
        "evaluation_reason": evaluation.reason,
        "materially_improved_metrics": list(evaluation.materially_improved_metrics),
    }


def public_review_result(result: CounterfactualResult) -> dict[str, object]:
    """Project one immutable result into v1; used for live and persisted paths."""
    selected_ids = {item.candidate.candidate_id for item in result.recommendations}
    operations = (result.remove, result.split, result.move, result.merge)
    evaluations = tuple(item for operation in operations for item in operation.candidates)
    return {
        "contract_version": CONTRACT_VERSION,
        "identity": asdict(result.identity),
        "calibration_status": result.calibration_status,
        "status": result.status.value,
        "reason": result.reason,
        "recommendation_status": result.recommendation_status.value,
        "operation_status": {
            **{operation.operation.value: _operation_status(operation) for operation in operations},
            "ADD_MEMBER": {
                "status": "BLOCKED",
                "reason": "UNKNOWN_UPSTREAM_SEMANTICS",
                "search_mode": "NOT_RUN",
                "candidate_count": 0,
                "evaluated_count": 0,
                "ceiling": None,
            },
        },
        "evaluated_candidates": [
            _candidate(item, result, selected_ids) for item in evaluations
        ],
        "recommendations": [{"candidate_id": item.candidate.candidate_id} for item in result.recommendations],
        "frontier": {
            "count_before_limit": result.frontier_count_before_limit,
            "selected_count": len(result.recommendations),
            "truncated": result.frontier_truncated,
        },
        "parameter_provenance": dict(result.parameter_provenance),
        "review_version": "counterfactual-review-v2",
        "review_id": f"rev_{result.identity.snapshot_id}_{result.identity.chain_id}",
        "exposure_status": "EXPOSURE_FROZEN",
        "ranking": "DETERMINISTIC",
        "similar_case_status": "UNAVAILABLE",
        "temporal_feature_status": "UNAVAILABLE",
        "review_readiness": "READY_FOR_REVIEW",
        "mutation_capability": "MUTATION_UNAVAILABLE",
        "allowed_review_actions": [
            "APPROVE",
            "REJECT",
            "DEFER",
            "INSUFFICIENT_EVIDENCE",
            "NONE_ACCEPTABLE",
            "MANUAL_CORRECTION",
        ],
        "exposure_policy": "ALL_EVALUATED",
    }

"""Operation-isolated Counterfactual Chain Review orchestration."""

from __future__ import annotations

from dataclasses import replace

from groups import AuditGraphMode
from libs.contracts import IngestedPackage

from .candidates import generate_remove_candidates, generate_split_candidates
from .config import CalibrationStatus, CounterfactualConfig
from .evaluator import MetricComputer, compute_exact_partition_metrics, evaluate_candidate
from .models import (
    CandidateEvaluation,
    CandidateStatus,
    CounterfactualResult,
    DomainStatus,
    ExternalValidationArtifact,
    Operation,
    OperationResult,
    RecommendationStatus,
    ReviewIdentity,
    SearchMode,
)
from .pareto import select_frontier


def _operation_unavailable(
    operation: Operation, reason: str, limit: int | None
) -> OperationResult:
    return OperationResult(
        operation=operation,
        status=DomainStatus.UNAVAILABLE,
        reason=reason,
        search_mode=SearchMode.NOT_RUN,
        discovered_candidate_count=0,
        evaluated_candidate_count=0,
        rejected_candidate_count=0,
        candidate_limit=limit,
        candidates=(),
    )


def _operation_not_applicable(
    operation: Operation, reason: str, limit: int | None
) -> OperationResult:
    return OperationResult(
        operation=operation,
        status=DomainStatus.NOT_APPLICABLE,
        reason=reason,
        search_mode=SearchMode.NOT_RUN,
        discovered_candidate_count=0,
        evaluated_candidate_count=0,
        rejected_candidate_count=0,
        candidate_limit=limit,
        candidates=(),
    )


def _evaluated_operation(operation, batch, evaluations) -> OperationResult:
    return OperationResult(
        operation=operation,
        status=DomainStatus.AVAILABLE,
        reason="NO_CANDIDATES" if not batch.candidates else None,
        search_mode=SearchMode.BOUNDED,
        discovered_candidate_count=batch.discovered_count,
        evaluated_candidate_count=len(evaluations),
        rejected_candidate_count=sum(
            evaluation.status
            in {
                CandidateStatus.HARD_GATE_REJECTED,
                CandidateStatus.EXTERNALLY_CONTRADICTED,
            }
            for evaluation in evaluations
        ),
        candidate_limit=batch.candidate_limit,
        candidates=tuple(evaluations),
    )


def _audit_is_exact(audit_artifact) -> bool:
    if audit_artifact is None:
        return False
    mode = getattr(audit_artifact, "audit_graph_mode", None)
    return mode is AuditGraphMode.EXACT_FULL or getattr(mode, "value", mode) == "EXACT_FULL"


def analyze_counterfactual_review(
    package: IngestedPackage,
    chain_id: str,
    *,
    identity: ReviewIdentity,
    tier1b_artifact,
    audit_artifact,
    analysis_config,
    config: CounterfactualConfig | None,
    config_reason: str | None = None,
    external_artifact: ExternalValidationArtifact | None = None,
    metric_computer: MetricComputer | None = None,
) -> CounterfactualResult:
    """Evaluate REMOVE and SPLIT independently without mutating the partition."""
    chain = package.chains.get(chain_id)
    if chain is None:
        raise KeyError(f"unknown chain_id {chain_id!r}")

    if config is None:
        reason = config_reason or "COUNTERFACTUAL_CONFIG_INCOMPLETE"
        return CounterfactualResult(
            identity=identity,
            status=DomainStatus.UNAVAILABLE,
            reason=reason,
            recommendation_status=RecommendationStatus.UNAVAILABLE,
            remove=_operation_unavailable(Operation.REMOVE_MEMBER, reason, None),
            split=_operation_unavailable(Operation.SPLIT_CHAIN, reason, None),
        )

    if chain.member_count == 1:
        return CounterfactualResult(
            identity=identity,
            status=DomainStatus.AVAILABLE,
            reason="SINGLETON_CHAIN",
            recommendation_status=RecommendationStatus.NO_CLEAR_ALTERNATIVE,
            remove=_operation_not_applicable(
                Operation.REMOVE_MEMBER, "SINGLETON_CHAIN", config.max_remove_candidates
            ),
            split=_operation_not_applicable(
                Operation.SPLIT_CHAIN, "SINGLETON_CHAIN", config.max_split_candidates
            ),
        )

    if chain.member_count > config.max_chain_members:
        reason = "COUNTERFACTUAL_LIMIT_EXCEEDED"
        return CounterfactualResult(
            identity=identity,
            status=DomainStatus.AVAILABLE,
            reason=reason,
            recommendation_status=RecommendationStatus.UNAVAILABLE,
            remove=_operation_unavailable(
                Operation.REMOVE_MEMBER, reason, config.max_remove_candidates
            ),
            split=_operation_unavailable(
                Operation.SPLIT_CHAIN, reason, config.max_split_candidates
            ),
        )

    members = tuple(package.members_of(chain_id))
    external = external_artifact or ExternalValidationArtifact("UNAVAILABLE")
    structural_audit = (
        getattr(audit_artifact, "structural_audit", None)
        if _audit_is_exact(audit_artifact)
        else None
    )
    split_batch = generate_split_candidates(
        identity,
        chain_id=chain_id,
        members=members,
        structural_audit=structural_audit,
        config=config,
    )
    remove_batch = generate_remove_candidates(
        identity,
        chain_id=chain_id,
        members=members,
        member_analysis=tier1b_artifact.members,
        config=config,
        eligible_external_contradictions=external.contradicted_member_ids,
        additional_member_ids=split_batch.canonical_remove_member_ids,
    )

    current_metrics = None
    if metric_computer is None:
        current_metrics = compute_exact_partition_metrics(
            package,
            (chain_id,),
            analysis_config=analysis_config,
            counterfactual_config=config,
        )

    def evaluate(batch):
        values: list[CandidateEvaluation] = []
        for candidate in batch.candidates:
            values.append(
                evaluate_candidate(
                    package,
                    candidate,
                    analysis_config=analysis_config,
                    config=config,
                    current_metrics=current_metrics,
                    metric_computer=metric_computer,
                    eligible_external_contradiction_count=(
                        1
                        if candidate.candidate_id in external.contradicted_candidate_ids
                        else 0
                    ),
                    externally_supported=(
                        candidate.candidate_id in external.supported_candidate_ids
                    ),
                )
            )
        return tuple(values)

    remove_evaluations = evaluate(remove_batch)
    split_evaluations = evaluate(split_batch)
    remove_result = _evaluated_operation(
        Operation.REMOVE_MEMBER, remove_batch, remove_evaluations
    )
    if chain.member_count < 4:
        split_result = _operation_not_applicable(
            Operation.SPLIT_CHAIN,
            "NO_NONTRIVIAL_SPLIT",
            config.max_split_candidates,
        )
    elif structural_audit is None:
        split_result = _operation_unavailable(
            Operation.SPLIT_CHAIN,
            "STRUCTURAL_AUDIT_UNAVAILABLE",
            config.max_split_candidates,
        )
    else:
        split_result = _evaluated_operation(
            Operation.SPLIT_CHAIN, split_batch, split_evaluations
        )

    all_evaluations = remove_evaluations + split_evaluations
    synthetic_allowed = (
        package.snapshot.source_kind == "SYNTHETIC_TEST"
        and config.calibration_status is CalibrationStatus.SYNTHETIC_ONLY
    )
    calibrated = (
        config.calibration_status is CalibrationStatus.PRODUCTION_CALIBRATED
        or synthetic_allowed
    )
    if not calibrated:
        reason = "COUNTERFACTUAL_POLICY_NOT_CALIBRATED"

        def uncalibrated(evaluation: CandidateEvaluation) -> CandidateEvaluation:
            if evaluation.status in {
                CandidateStatus.BETTER_SUPPORTED,
                CandidateStatus.EXTERNALLY_SUPPORTED,
            }:
                return replace(
                    evaluation,
                    status=CandidateStatus.EVALUATED,
                    reason=reason,
                )
            return evaluation

        remove_result = replace(
            remove_result,
            candidates=tuple(uncalibrated(item) for item in remove_result.candidates),
        )
        split_result = replace(
            split_result,
            candidates=tuple(uncalibrated(item) for item in split_result.candidates),
        )
        return CounterfactualResult(
            identity=identity,
            status=DomainStatus.AVAILABLE,
            reason=reason,
            recommendation_status=RecommendationStatus.UNAVAILABLE,
            remove=remove_result,
            split=split_result,
        )

    frontier = select_frontier(all_evaluations, config)
    recommendation_status = (
        RecommendationStatus.AVAILABLE
        if frontier.items
        else RecommendationStatus.NO_CLEAR_ALTERNATIVE
    )
    return CounterfactualResult(
        identity=identity,
        status=DomainStatus.AVAILABLE,
        reason=None if frontier.items else "NO_CLEAR_ALTERNATIVE",
        recommendation_status=recommendation_status,
        remove=remove_result,
        split=split_result,
        recommendations=frontier.items,
        frontier_count_before_limit=frontier.count_before_limit,
        frontier_truncated=frontier.truncated,
    )

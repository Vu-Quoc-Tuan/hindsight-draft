"""Operation-isolated Counterfactual Chain Review orchestration."""

from __future__ import annotations

from dataclasses import replace

from groups import AuditGraphMode
from libs.contracts import IngestedPackage

from .candidates import (
    generate_merge_candidates,
    generate_move_candidates,
    generate_remove_candidates,
    generate_split_candidates,
)
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
    if mode is AuditGraphMode.EXACT_FULL or getattr(mode, "value", mode) == "EXACT_FULL":
        return True
    return (
        getattr(audit_artifact, "status", None) == "AVAILABLE"
        and getattr(audit_artifact, "mode", None) == "EXACT"
    )


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
            move=_operation_unavailable(Operation.MOVE_MEMBER, reason, None),
            merge=_operation_unavailable(Operation.MERGE_CHAINS, reason, None),
            calibration_status=None,
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
            move=_operation_unavailable(
                Operation.MOVE_MEMBER, reason, config.max_move_candidates
            ),
            merge=_operation_unavailable(
                Operation.MERGE_CHAINS, reason, config.max_merge_candidates
            ),
            calibration_status=config.calibration_status.value,
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
    move_batch = (
        generate_move_candidates(
            identity,
            source_chain_id=chain_id,
            source_members=members,
            member_analysis=tier1b_artifact.members,
            local_candidates=tier1b_artifact.local_candidates,
            package=package,
            config=config,
        )
        if config.max_move_candidates is not None
        else None
    )
    merge_batch = (
        generate_merge_candidates(
            identity,
            review_chain_id=chain_id,
            local_candidates=tier1b_artifact.local_candidates,
            package=package,
            config=config,
        )
        if config.max_merge_candidates is not None
        else None
    )

    current_metrics = None
    if metric_computer is None and chain.member_count > 1:
        current_metrics = compute_exact_partition_metrics(
            package,
            (chain_id,),
            analysis_config=analysis_config,
            counterfactual_config=config,
        )

    def evaluate(batch, *, baseline_metrics=current_metrics):
        values: list[CandidateEvaluation] = []
        for candidate in batch.candidates:
            values.append(
                evaluate_candidate(
                    package,
                    candidate,
                    analysis_config=analysis_config,
                    config=config,
                    current_metrics=baseline_metrics,
                    metric_computer=metric_computer,
                    eligible_external_contradiction_count=(
                        1
                        if candidate.candidate_id in external.contradicted_candidate_ids
                        else 0
                    ),
                    externally_supported=(
                        candidate.candidate_id in external.supported_candidate_ids
                    ),
                    external_validation_available=(external_artifact is not None),
                    external_validation_conflict=(
                        candidate.candidate_id in external.supported_candidate_ids
                        and candidate.candidate_id in external.contradicted_candidate_ids
                    ),
                )
            )
        return tuple(values)

    remove_evaluations = evaluate(remove_batch)
    split_evaluations = evaluate(split_batch)
    move_evaluations = (
        evaluate(move_batch, baseline_metrics=None) if move_batch is not None else ()
    )
    merge_evaluations = (
        evaluate(merge_batch, baseline_metrics=None) if merge_batch is not None else ()
    )
    if chain.member_count == 1:
        remove_result = _operation_not_applicable(
            Operation.REMOVE_MEMBER, "SINGLETON_CHAIN", config.max_remove_candidates
        )
        split_result = _operation_not_applicable(
            Operation.SPLIT_CHAIN, "SINGLETON_CHAIN", config.max_split_candidates
        )
    else:
        remove_result = _evaluated_operation(
            Operation.REMOVE_MEMBER, remove_batch, remove_evaluations
        )
        split_result = None
    if chain.member_count > 1 and chain.member_count < 4:
        split_result = _operation_not_applicable(
            Operation.SPLIT_CHAIN,
            "NO_NONTRIVIAL_SPLIT",
            config.max_split_candidates,
        )
    elif chain.member_count > 1 and structural_audit is None:
        split_result = _operation_unavailable(
            Operation.SPLIT_CHAIN,
            "STRUCTURAL_AUDIT_UNAVAILABLE",
            config.max_split_candidates,
        )
    elif chain.member_count > 1:
        split_result = _evaluated_operation(
            Operation.SPLIT_CHAIN, split_batch, split_evaluations
        )
    assert split_result is not None
    move_result = (
        _evaluated_operation(Operation.MOVE_MEMBER, move_batch, move_evaluations)
        if move_batch is not None
        else _operation_unavailable(
            Operation.MOVE_MEMBER,
            config.move_reason or "MOVE_POLICY_NOT_CALIBRATED",
            None,
        )
    )
    merge_result = (
        _evaluated_operation(Operation.MERGE_CHAINS, merge_batch, merge_evaluations)
        if merge_batch is not None
        else _operation_unavailable(
            Operation.MERGE_CHAINS,
            config.merge_reason or "MERGE_POLICY_NOT_CALIBRATED",
            None,
        )
    )

    all_evaluations = (
        remove_evaluations + split_evaluations + move_evaluations + merge_evaluations
    )
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
        move_result = replace(
            move_result,
            candidates=tuple(uncalibrated(item) for item in move_result.candidates),
        )
        merge_result = replace(
            merge_result,
            candidates=tuple(uncalibrated(item) for item in merge_result.candidates),
        )
        return CounterfactualResult(
            identity=identity,
            status=DomainStatus.AVAILABLE,
            reason=reason,
            recommendation_status=RecommendationStatus.UNAVAILABLE,
            remove=remove_result,
            split=split_result,
            move=move_result,
            merge=merge_result,
            calibration_status=config.calibration_status.value,
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
        move=move_result,
        merge=merge_result,
        calibration_status=config.calibration_status.value,
        recommendations=frontier.items,
        frontier_count_before_limit=frontier.count_before_limit,
        frontier_truncated=frontier.truncated,
        frontier_candidate_ids=tuple(
            item.candidate.candidate_id for item in frontier.all_items
        ),
    )

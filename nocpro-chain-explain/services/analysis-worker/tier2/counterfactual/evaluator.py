"""Exact affected-region metric computation and counterfactual hard gates."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from audit import (
    AuditVerdict,
    StructuralRole,
    StructuralRoleResult,
    connected_components,
)
from channels import EMPTY_TAXONOMY
from descriptor import build_predicate_index
from graybox.singleton import MembershipVerdict
from libs.contracts import IngestedChain, IngestedPackage
from tier1b import analyze_chain_configured
from tier2.audit_analysis import AuditExecutionPolicy, analyze_structural_audit

from .config import CounterfactualConfig
from .models import (
    CandidateEvaluation,
    CandidateStatus,
    CounterfactualCandidate,
    MetricAvailability,
    MetricValue,
    MetricVector,
    MoveStructuralFacts,
    Operation,
    PartitionDelta,
    SemanticEffect,
)


MetricComputer = Callable[[IngestedPackage, tuple[str, ...]], MetricVector]


_LOWER_IS_BETTER = {
    "weak_member_count",
    "component_count",
    "audit_verdict_severity",
    "eligible_external_contradiction_count",
}

_HIGHER_IS_BETTER = {
    "minimum_membership_support",
    "evidence_union_coverage",
    "audit_conductance",
}

_METRIC_NAMES = tuple(sorted(_LOWER_IS_BETTER | _HIGHER_IS_BETTER))

_AUDIT_SEVERITY = {
    AuditVerdict.NO_LOW_CONDUCTANCE_CUT: 0,
    AuditVerdict.CANDIDATE_SPLIT: 1,
}


def apply_partition_delta(
    package: IngestedPackage, delta: PartitionDelta
) -> IngestedPackage:
    """Return a package view with only the affected memberships replaced."""
    before_ids = {chain_id for chain_id, _ in delta.before}
    chains = {
        chain_id: chain
        for chain_id, chain in package.chains.items()
        if chain_id not in before_ids
    }
    memberships = {
        chain_id: list(members)
        for chain_id, members in package.memberships.items()
        if chain_id not in before_ids
    }
    for chain_id, members in delta.after:
        chains[chain_id] = IngestedChain(
            chain_id=chain_id,
            snapshot_id=package.snapshot.snapshot_id,
            member_count=len(members),
            chain_name=None,
            event_span_seconds=None,
        )
        memberships[chain_id] = list(members)
    return IngestedPackage(
        snapshot=package.snapshot,
        alarms=package.alarms,
        chains=chains,
        memberships=memberships,
        system_metadata=package.system_metadata,
        topology=package.topology,
        operational_context=package.operational_context,
        provenance_manifest=package.provenance_manifest,
    )


def _unavailable_vector(reason: str) -> MetricVector:
    value = MetricValue.unavailable(reason)
    return MetricVector(
        weak_member_count=value,
        minimum_membership_support=value,
        evidence_union_coverage=value,
        component_count=value,
        audit_conductance=value,
        audit_verdict_severity=value,
        eligible_external_contradiction_count=value,
    )


def compute_exact_partition_metrics(
    package: IngestedPackage,
    chain_ids: tuple[str, ...],
    *,
    analysis_config,
    counterfactual_config: CounterfactualConfig,
    eligible_external_contradiction_count: int = 0,
    structural_roles_by_chain: dict[str, dict[str, StructuralRoleResult]] | None = None,
) -> MetricVector:
    """Compute approved conservative aggregates for affected non-singletons."""
    non_singletons = tuple(
        chain_id
        for chain_id in chain_ids
        if chain_id in package.chains and package.chains[chain_id].member_count > 1
    )
    if not non_singletons:
        return _unavailable_vector("NO_NON_SINGLETON_AFFECTED_CHAIN")

    if any(
        package.chains[chain_id].member_count
        > counterfactual_config.max_chain_members
        for chain_id in non_singletons
    ):
        return _unavailable_vector("COUNTERFACTUAL_LIMIT_EXCEEDED")

    predicate_index = build_predicate_index(list(package.alarms.values()))
    weak_count = 0
    supports: list[float] = []
    total_pairs = 0
    covered_pairs = 0
    component_counts: list[int] = []
    conductances: list[float] = []
    severities: list[int] = []
    audit_unavailable = False

    for chain_id in non_singletons:
        chain_analysis = analyze_chain_configured(
            package,
            chain_id,
            analysis_config=analysis_config,
            predicate_index=predicate_index,
        )
        weak_count += sum(
            1
            for member in chain_analysis.members.values()
            if member.role.verdict is MembershipVerdict.WEAK
        )
        supports.extend(
            float(member.support.support)
            for member in chain_analysis.members.values()
            if member.support.support is not None
        )

        tier2 = analyze_structural_audit(
            package,
            chain_id,
            policy=AuditExecutionPolicy(
                exact_max_members=counterfactual_config.max_chain_members
            ),
            mining_config=analysis_config.mining_config(),
            epsilon=float(analysis_config.value("audit.global_weak_baseline")),
            rho=float(analysis_config.value("audit.rho")),
            min_side_size=int(analysis_config.value("audit.min_side_size")),
            small_chain_threshold=int(
                analysis_config.value("audit.small_chain_threshold")
            ),
            delay_threshold=float(
                analysis_config.value("temporal.delay.support_threshold")
            ),
            d_max=int(analysis_config.value("dependency.max_hop")),
            silent_gap_seconds=int(
                analysis_config.value("temporal.burst.gap_seconds")
            ),
            taxonomy=EMPTY_TAXONOMY,
            similarity_context=None,
            attribution_evaluation_config=None,
        )
        attribution = tier2.evidence_attribution
        if (
            attribution.total_pair_count is None
            or attribution.covered_pair_count is None
        ):
            return _unavailable_vector("REQUIRED_METRIC_UNAVAILABLE")
        total_pairs += attribution.total_pair_count
        covered_pairs += attribution.covered_pair_count

        if tier2.graph is None:
            return _unavailable_vector("REQUIRED_METRIC_UNAVAILABLE")
        if structural_roles_by_chain is not None:
            structural_roles_by_chain[chain_id] = dict(tier2.structural_roles)
        component_counts.append(len(connected_components(tier2.graph)))
        audit = tier2.structural_audit
        if audit.verdict in {
            AuditVerdict.SKIPPED_SMALL_CHAIN,
            AuditVerdict.UNAVAILABLE,
        }:
            # A skipped audit is not evidence of either a clean cut or high
            # conductance. Preserve the other independently computed metrics.
            audit_unavailable = True
        else:
            severity = _AUDIT_SEVERITY.get(audit.verdict)
            if severity is None or audit.best_cut is None:
                return _unavailable_vector("REQUIRED_METRIC_UNAVAILABLE")
            phi = audit.best_cut.conductance.phi
            if phi is None or not audit.best_cut.conductance.feasible:
                return _unavailable_vector("REQUIRED_METRIC_UNAVAILABLE")
            severities.append(severity)
            conductances.append(float(phi))

    if not supports:
        return _unavailable_vector("REQUIRED_METRIC_UNAVAILABLE")

    coverage = (covered_pairs / total_pairs) if total_pairs > 0 else 1.0

    return MetricVector(
        weak_member_count=MetricValue.available(weak_count),
        minimum_membership_support=MetricValue.available(min(supports)),
        evidence_union_coverage=MetricValue.available(coverage),
        component_count=MetricValue.available(max(component_counts)),
        audit_conductance=(
            MetricValue.unavailable("STRUCTURAL_AUDIT_UNAVAILABLE")
            if audit_unavailable
            else MetricValue.available(min(conductances))
        ),
        audit_verdict_severity=(
            MetricValue.unavailable("STRUCTURAL_AUDIT_UNAVAILABLE")
            if audit_unavailable
            else MetricValue.available(max(severities))
        ),
        eligible_external_contradiction_count=MetricValue.available(
            eligible_external_contradiction_count
        ),
    )


def _singleton_structural_role(alarm_id: str) -> StructuralRoleResult:
    return StructuralRoleResult(
        alarm_id=alarm_id,
        role=StructuralRole.NOT_APPLICABLE,
        is_articulation_point=False,
        blocks_supported=0,
        reason="singleton chain: no pair to audit",
    )


def _move_structural_facts(
    package: IngestedPackage,
    candidate: CounterfactualCandidate,
    *,
    before_roles: dict[str, dict[str, StructuralRoleResult]],
    after_roles: dict[str, dict[str, StructuralRoleResult]],
) -> MoveStructuralFacts | None:
    """Project exact role facts for a MOVE without changing its acceptance."""
    if candidate.operation is not Operation.MOVE_MEMBER:
        return None
    if (
        len(candidate.member_ids) != 1
        or candidate.source_chain_id is None
        or candidate.target_chain_id is None
    ):
        return None
    alarm_id = candidate.member_ids[0]
    source = package.chains.get(candidate.source_chain_id)
    if source is None:
        return None
    before = (
        _singleton_structural_role(alarm_id)
        if source.member_count == 1
        else before_roles.get(candidate.source_chain_id, {}).get(alarm_id)
    )
    after = after_roles.get(candidate.target_chain_id, {}).get(alarm_id)
    if before is None or after is None:
        return None
    return MoveStructuralFacts(
        before_structural_role=before.role.value,
        after_structural_role=after.role.value,
        after_is_articulation_point=after.is_articulation_point,
        after_blocks_supported=after.blocks_supported,
    )


def _delta_for_metric(
    name: str, before: float | int, after: float | int
) -> float:
    if name in _LOWER_IS_BETTER:
        return float(before) - float(after)
    return float(after) - float(before)


def _minimum_improvement(name: str, config: CounterfactualConfig) -> float:
    if name == "minimum_membership_support":
        return config.minimum_membership_improvement
    if name == "evidence_union_coverage":
        return config.minimum_coverage_improvement
    if name == "audit_conductance":
        return config.minimum_conductance_improvement
    return 1.0


def compare_before_after(
    before: MetricVector,
    after: MetricVector,
    config: CounterfactualConfig,
) -> tuple[CandidateStatus, tuple[str, ...], str | None, dict[str, float]]:
    deltas: dict[str, float] = {}
    for name in _METRIC_NAMES:
        old = getattr(before, name)
        new = getattr(after, name)
        if (
            old.availability is not MetricAvailability.AVAILABLE
            or new.availability is not MetricAvailability.AVAILABLE
        ):
            return (
                CandidateStatus.HARD_GATE_REJECTED,
                (),
                "REQUIRED_METRIC_UNAVAILABLE",
                deltas,
            )
        assert old.value is not None and new.value is not None
        deltas[name] = _delta_for_metric(name, old.value, new.value)

    if int(after.eligible_external_contradiction_count.value or 0) > 0:
        return CandidateStatus.EXTERNALLY_CONTRADICTED, (), "EXTERNAL_CONTRADICTION", deltas
    if deltas["audit_verdict_severity"] < 0:
        return CandidateStatus.HARD_GATE_REJECTED, (), "AUDIT_SEVERITY_WORSENED", deltas
    if any(delta < -config.pareto_tolerance for delta in deltas.values()):
        return CandidateStatus.HARD_GATE_REJECTED, (), "PARETO_METRIC_WORSENED", deltas

    improved = tuple(
        name
        for name in _METRIC_NAMES
        if deltas[name] >= _minimum_improvement(name, config)
    )
    if not improved:
        return CandidateStatus.HARD_GATE_REJECTED, (), "NO_MATERIAL_IMPROVEMENT", deltas
    return CandidateStatus.BETTER_SUPPORTED, improved, None, deltas


def evaluate_candidate(
    package: IngestedPackage,
    candidate: CounterfactualCandidate,
    *,
    analysis_config,
    config: CounterfactualConfig,
    current_metrics: MetricVector | None = None,
    metric_computer: MetricComputer | None = None,
    eligible_external_contradiction_count: int = 0,
    externally_supported: bool = False,
    external_validation_available: bool = False,
    external_validation_conflict: bool = False,
) -> CandidateEvaluation:
    before_chain_ids = tuple(chain_id for chain_id, _ in candidate.partition_delta.before)
    after_chain_ids = tuple(chain_id for chain_id, _ in candidate.partition_delta.after)
    candidate_package = apply_partition_delta(package, candidate.partition_delta)
    structural_facts: MoveStructuralFacts | None = None
    if metric_computer is None:
        before_roles: dict[str, dict[str, StructuralRoleResult]] = {}
        after_roles: dict[str, dict[str, StructuralRoleResult]] = {}
        before = current_metrics or compute_exact_partition_metrics(
            package,
            before_chain_ids,
            analysis_config=analysis_config,
            counterfactual_config=config,
            structural_roles_by_chain=before_roles,
        )
        after = compute_exact_partition_metrics(
            candidate_package,
            after_chain_ids,
            analysis_config=analysis_config,
            counterfactual_config=config,
            eligible_external_contradiction_count=(
                eligible_external_contradiction_count
            ),
            structural_roles_by_chain=after_roles,
        )
        structural_facts = _move_structural_facts(
            package,
            candidate,
            before_roles=before_roles,
            after_roles=after_roles,
        )
    else:
        before = current_metrics or metric_computer(package, before_chain_ids)
        after = metric_computer(candidate_package, after_chain_ids)
        if eligible_external_contradiction_count:
            after = replace(
                after,
                eligible_external_contradiction_count=MetricValue.available(
                    eligible_external_contradiction_count
                ),
            )

    status, improved, reason, metric_deltas = compare_before_after(before, after, config)
    if external_validation_conflict:
        status = CandidateStatus.HARD_GATE_REJECTED
        improved = ()
        reason = "EXTERNAL_VALIDATION_CONFLICT"
    if status is CandidateStatus.BETTER_SUPPORTED and externally_supported:
        status = CandidateStatus.EXTERNALLY_SUPPORTED
    semantic_effects: tuple[SemanticEffect, ...] = ()
    if (
        status
        in {CandidateStatus.BETTER_SUPPORTED, CandidateStatus.EXTERNALLY_SUPPORTED}
        and structural_facts is not None
        and structural_facts.after_structural_role == StructuralRole.CONNECTOR.value
        and structural_facts.before_structural_role != StructuralRole.CONNECTOR.value
    ):
        semantic_effects = (SemanticEffect.BECOMES_CONNECTOR,)
    return CandidateEvaluation(
        candidate=candidate,
        status=status,
        before=before,
        after=after,
        materially_improved_metrics=improved,
        reason=reason,
        move_structural_facts=structural_facts,
        semantic_effects=semantic_effects,
        metric_deltas=metric_deltas,
        external_validation=(
            "UNAVAILABLE"
            if not external_validation_available
            else "NOT_APPLIED"
            if status is CandidateStatus.HARD_GATE_REJECTED
            else "CONTRADICTED"
            if reason == "EXTERNAL_CONTRADICTION"
            else "SUPPORTED"
            if externally_supported
            else "NO_FINDING"
        ),
    )


def metric_delta(
    name: str, left: MetricVector, right: MetricVector
) -> float | None:
    left_value = getattr(left, name)
    right_value = getattr(right, name)
    if (
        left_value.availability is not MetricAvailability.AVAILABLE
        or right_value.availability is not MetricAvailability.AVAILABLE
    ):
        return None
    assert left_value.value is not None and right_value.value is not None
    return _delta_for_metric(name, right_value.value, left_value.value)


def required_metric_names() -> tuple[str, ...]:
    return _METRIC_NAMES

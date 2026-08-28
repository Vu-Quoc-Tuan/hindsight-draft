"""Tier-2-only exact structural audit orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from audit import (
    AUDIT_EXACT_MAX_MEMBERS,
    AuditGraph,
    StructuralRoleResult,
    StructuralAuditResult,
    OverMergeVerdict,
    assess_over_merge,
    build_audit_graph,
    classify_structural_role,
    generate_candidates,
    run_structural_audit,
)
from channels import EMPTY_TAXONOMY, AlarmTaxonomy, evaluate_chain_channels
from descriptor import (
    DescriptorKind,
    MiningConfig,
    bitmap_of_members,
    build_predicate_index,
    mine_descriptors,
)
from groups import AuditGraphMode
from libs.contracts import IngestedPackage


class AuditPolicyRequired(RuntimeError):
    """Raised when exact audit is disallowed and no compressed policy exists."""


@dataclass(frozen=True)
class AuditExecutionPolicy:
    """Explicit exact-audit size bound selected by the caller."""

    exact_max_members: int

    def __post_init__(self) -> None:
        if self.exact_max_members <= 0:
            raise ValueError("exact_max_members must be positive")
        if self.exact_max_members > AUDIT_EXACT_MAX_MEMBERS:
            raise ValueError(
                f"exact_max_members exceeds implemented exact audit guard "
                f"{AUDIT_EXACT_MAX_MEMBERS}"
            )


@dataclass
class Tier2AuditAnalysis:
    chain_id: str
    audit_graph_mode: AuditGraphMode
    graph: AuditGraph | None
    structural_roles: dict[str, StructuralRoleResult]
    structural_audit: StructuralAuditResult
    over_merge: OverMergeVerdict
    reason: str | None = None


def analyze_structural_audit(
    package: IngestedPackage,
    chain_id: str,
    *,
    policy: AuditExecutionPolicy,
    mining_config: MiningConfig,
    epsilon: float,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    dependency_edges: list[tuple[str, str, float]] | None = None,
    failure_domains: list[tuple[str, frozenset[str]]] | None = None,
    cross_block_negative_evidence: bool = False,
) -> Tier2AuditAnalysis:
    """Run an exact audit only when the caller's configured policy permits it."""
    chain = package.chains.get(chain_id)
    if chain is None:
        raise KeyError(f"unknown chain_id {chain_id!r}")
    if chain.member_count > policy.exact_max_members:
        raise AuditPolicyRequired(
            f"chain {chain_id!r} with {chain.member_count} members exceeds exact "
            f"audit bound {policy.exact_max_members}; configure a benchmark-derived "
            "SPARSIFIED or SUPERNODE policy"
        )

    pair_count = chain.member_count * (chain.member_count - 1) // 2
    evidence = evaluate_chain_channels(
        package,
        chain_id,
        taxonomy=taxonomy,
        pair_detail_limit=pair_count,
    )
    graph = build_audit_graph(evidence.members, evidence.matrix.values)
    roles = {
        alarm_id: classify_structural_role(alarm_id, graph)
        for alarm_id in evidence.members
    }
    predicate_index = build_predicate_index(list(package.alarms.values()))
    target = bitmap_of_members(predicate_index, set(evidence.members))
    descriptors = tuple(
        mine_descriptors(
            predicate_index,
            target,
            config=mining_config,
            kind=DescriptorKind.IDENTITY,
        )
    )
    candidates = generate_candidates(
        alarms=package.alarms_of(chain_id),
        dependency_edges=dependency_edges or [],
        failure_domains=failure_domains or [],
        descriptors=descriptors,
        predicate_index=predicate_index,
    )
    structural_audit = run_structural_audit(
        chain_id, graph, candidates, epsilon=epsilon
    )
    over_merge = assess_over_merge(
        structural_audit,
        graph,
        index=predicate_index,
        mining_config=mining_config,
        cross_block_negative_evidence=cross_block_negative_evidence,
    )
    return Tier2AuditAnalysis(
        chain_id=chain_id,
        audit_graph_mode=AuditGraphMode.EXACT_FULL,
        graph=graph,
        structural_roles=roles,
        structural_audit=structural_audit,
        over_merge=over_merge,
    )

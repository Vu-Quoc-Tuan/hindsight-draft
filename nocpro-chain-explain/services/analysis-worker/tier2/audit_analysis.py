"""Tier-2-only exact structural audit orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from audit import (
    AUDIT_EXACT_MAX_MEMBERS,
    DEFAULT_RHO,
    MIN_SIDE_SIZE,
    SMALL_CHAIN_THRESHOLD,
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
from channels import (
    EMPTY_TAXONOMY,
    AlarmTaxonomy,
    evaluate_chain_channels,
    failure_domains_for_chain,
)
from descriptor import (
    DescriptorKind,
    MiningConfig,
    bitmap_of_members,
    build_predicate_index,
    mine_descriptors,
)
from configuration import P2TopologyConfig
from groups import AuditGraphMode
from libs.contracts import IngestedPackage
from similar_chains import (
    ChainFingerprint,
    SimilarChainResult,
    VersionedSimilarityIndex,
    build_fingerprint,
    find_similar_chains,
)
from similar_chains.temporal import CorpusPolicy, parse_time

from .topology_hypotheses import TopologyHypothesesResult, analyze_topology_hypotheses


class AuditPolicyRequired(RuntimeError):
    """Raised when exact audit is disallowed and no compressed policy exists."""


@dataclass(frozen=True)
class SimilarityQueryContext:
    """Immutable historical index selected for one query snapshot."""

    index: VersionedSimilarityIndex
    target_lineage_component_id: str | None = None

    @property
    def model(self):
        return self.index.model

    @property
    def corpus(self) -> tuple[ChainFingerprint, ...]:
        return self.index.corpus

    def validate_query_time(self, snapshot_time: str) -> None:
        model = self.model
        query_time = parse_time(snapshot_time)
        cutoff = parse_time(model.trained_until_exclusive)
        if model.corpus_policy == CorpusPolicy.HISTORY_BEFORE_SNAPSHOT.value:
            if query_time != cutoff:
                raise ValueError(
                    "snapshot-versioned SimilarityModel cutoff must equal the "
                    "query snapshot_time"
                )
        elif query_time < cutoff:
            raise ValueError(
                "offline query precedes the frozen model training cutoff"
            )


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
    topology_hypotheses: TopologyHypothesesResult
    reason: str | None = None
    config_version: str | None = None
    epsilon: float | None = None
    parameter_provenance: dict[str, str] | None = None
    similar_chains: tuple[SimilarChainResult, ...] = ()
    similarity_model_version: str | None = None
    similarity_trained_until_exclusive: str | None = None
    similarity_corpus_policy: str | None = None
    similarity_model_update_policy: str | None = None
    similarity_status: str = "UNAVAILABLE"
    similarity_unavailable_reason: str | None = None
    taxonomy_status: str | None = None
    taxonomy_reason: str | None = None
    active_fingerprint_blocks: tuple[str, ...] = ()


def analyze_structural_audit(
    package: IngestedPackage,
    chain_id: str,
    *,
    policy: AuditExecutionPolicy,
    mining_config: MiningConfig,
    epsilon: float,
    rho: float = DEFAULT_RHO,
    min_side_size: int = MIN_SIDE_SIZE,
    small_chain_threshold: int = SMALL_CHAIN_THRESHOLD,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    dependency_edges: list[tuple[str, str, float]] | None = None,
    failure_domains: list[tuple[str, frozenset[str]]] | None = None,
    cross_block_negative_evidence: bool = False,
    similarity_context: SimilarityQueryContext | None = None,
    similarity_top_k: int = 5,
    p2_topology_config: P2TopologyConfig | None = None,
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
    resolved_failure_domains = (
        failure_domains
        if failure_domains is not None
        else [
            (domain.failure_domain_id, domain.member_alarm_ids)
            for domain in failure_domains_for_chain(package, chain_id)
        ]
    )
    candidates = generate_candidates(
        alarms=package.alarms_of(chain_id),
        dependency_edges=dependency_edges or [],
        failure_domains=resolved_failure_domains,
        descriptors=descriptors,
        predicate_index=predicate_index,
    )
    structural_audit = run_structural_audit(
        chain_id,
        graph,
        candidates,
        epsilon=epsilon,
        rho=rho,
        min_side_size=min_side_size,
        small_chain_threshold=small_chain_threshold,
    )
    over_merge = assess_over_merge(
        structural_audit,
        graph,
        index=predicate_index,
        mining_config=mining_config,
        cross_block_negative_evidence=cross_block_negative_evidence,
    )
    similar_results: tuple[SimilarChainResult, ...] = ()
    similarity_model_version: str | None = None
    similarity_trained_until_exclusive: str | None = None
    similarity_corpus_policy: str | None = None
    similarity_model_update_policy: str | None = None
    similarity_unavailable_reason: str | None = None
    taxonomy_status: str | None = None
    taxonomy_reason: str | None = None
    active_fingerprint_blocks: tuple[str, ...] = ()
    if similarity_context is None:
        similarity_unavailable_reason = "LINEAGE_NOT_READY"
    else:
        similarity_context.validate_query_time(package.snapshot.snapshot_time)
        model = similarity_context.model
        target_fingerprint = build_fingerprint(
            chain_id,
            package.alarms_of(chain_id),
            lineage_component_id=similarity_context.target_lineage_component_id,
            taxonomy=taxonomy,
            identity_descriptors=descriptors,
            duration_seconds=chain.event_span_seconds,
            top_descriptor_predicates=model.top_descriptor_predicates,
            size_bin_edges=model.size_bin_edges,
            duration_bin_edges=model.duration_bin_edges,
        )
        taxonomy_status = model.taxonomy_status.value
        taxonomy_reason = model.taxonomy_reason
        active_fingerprint_blocks = target_fingerprint.active_blocks()
        similar_results = tuple(
            find_similar_chains(
                target_fingerprint,
                list(similarity_context.corpus),
                model=model,
                top_k=similarity_top_k,
                exclude_same_lineage=True,
            )
        )
        similarity_model_version = model.model_version
        similarity_trained_until_exclusive = model.trained_until_exclusive
        similarity_corpus_policy = model.corpus_policy
        similarity_model_update_policy = model.model_update_policy
    # P2 is an independent semantic branch.  It receives the immutable input
    # package and optional envelope, never the evidence/audit graph produced
    # above, so hypotheses cannot influence G*_audit or structural roles.
    topology_hypotheses = analyze_topology_hypotheses(
        package,
        chain_id,
        p2_topology_config,
    )
    return Tier2AuditAnalysis(
        chain_id=chain_id,
        audit_graph_mode=AuditGraphMode.EXACT_FULL,
        graph=graph,
        structural_roles=roles,
        structural_audit=structural_audit,
        over_merge=over_merge,
        topology_hypotheses=topology_hypotheses,
        config_version=mining_config.config_version,
        epsilon=epsilon,
        similar_chains=similar_results,
        similarity_model_version=similarity_model_version,
        similarity_trained_until_exclusive=similarity_trained_until_exclusive,
        similarity_corpus_policy=similarity_corpus_policy,
        similarity_model_update_policy=similarity_model_update_policy,
        similarity_status="AVAILABLE" if similarity_context is not None else "UNAVAILABLE",
        similarity_unavailable_reason=similarity_unavailable_reason,
        taxonomy_status=taxonomy_status,
        taxonomy_reason=taxonomy_reason,
        active_fingerprint_blocks=active_fingerprint_blocks,
    )

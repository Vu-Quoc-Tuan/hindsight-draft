"""Tier-1B chain analysis (§3, §4B, §5).

Wires the MVP pieces into one local analysis so role classification becomes
self-contained: ``Representativeness`` comes from mined IDENTITY descriptors and
``Margin_common`` from the contrastive comparison, instead of being supplied by a
caller.

Order matters and follows the spec's dependency chain:

    indexed statistics -> Fit_g -> descriptors -> Representativeness
             -> U_local -> contrastive -> Margin_common -> role
             -> REDUNDANCY role

Tier-1B never materializes the full audit graph or waits for Tier-2 (ADR-0014).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from libs.contracts import IngestedPackage

from audit.structural_role import StructuralRole, StructuralRoleResult
from channels import (
    DEFAULT_LAMBDA_DEP,
    DEFAULT_THETA_CD,
    DEFAULT_SILENT_GAP_SECONDS,
    DEFAULT_D_MAX,
    IndexedChainEvidence,
    RivalFitIndex,
    FailureDomainEvidence,
    evaluate_chain_indexed,
    failure_domains_for_chain,
)
from channels.base import ChannelValue
from channels.entity import evaluate_entity_channels
from channels.semantic import EMPTY_TAXONOMY, AlarmTaxonomy, evaluate_semantic_channel
from channels.temporal import evaluate_burst_channel, segment_bursts
from channels.dependency import (
    PHYSICAL_RELATIONS,
    ResourceResolver,
    build_topology_graph,
    evaluate_dep_hop_channel,
)
from descriptor import (
    Descriptor,
    DescriptorKind,
    DescriptorSet,
    MiningConfig,
    PredicateIndex,
    DEFAULT_MAX_VALUES_PER_FIELD,
    bitmap_of_members,
    build_predicate_index,
    mine_descriptors,
    representativeness,
)
from descriptor.contrastive import (
    DEFAULT_CONTRASTIVE_TOP_K,
    DEFAULT_G_MIN,
    DEFAULT_U_LOCAL_K,
    BlockingCandidate,
    MarginResult,
    blocking_candidates,
    local_universe_bitmap,
    margin_common,
    top_contrastive_candidates,
)
from graybox import GrayBoxMetadata, adapt_graybox_metadata
from graybox.singleton import build_singleton_report
from groups import (
    ChannelStatistics,
    GateResult,
    MembershipRole,
    MembershipSupport,
    RoleThresholds,
    classify_membership,
    membership_support_from_index,
)
from groups.redundancy import (
    DEFAULT_SMALL_DT_SECONDS,
    RedundancyResult,
    classify_redundancy_all,
)


@dataclass
class MemberAnalysis:
    """Per-member analysis result across all three role axes (§4B)."""

    alarm_id: str
    support: MembershipSupport
    #: MEMBERSHIP axis: CORE / PERIPHERAL / WEAK / INSUFFICIENT_DATA.
    role: MembershipRole
    representativeness: float | None
    #: WHY-4: Margin_common against each of the top-3 blocking candidates
    #: (§5, §11 "contrastive top-3"). One rival alone is not the contract;
    #: each candidate gets its own margin so the operator can see how a
    #: member reads against every plausible alternative chain, not just the
    #: single closest one.
    margins: tuple[MarginResult, ...] = ()
    #: STRUCTURAL axis is populated by Tier-2; singleton stays NOT_APPLICABLE.
    structural: StructuralRoleResult | None = None
    #: REDUNDANCY axis: NEAR_DUPLICATE_CANDIDATE / UNIQUE.
    redundancy: RedundancyResult | None = None
    #: H_domain memberships are set-valued context, never pair scores.
    failure_domains: tuple[FailureDomainEvidence, ...] = ()

    @property
    def margin(self) -> MarginResult | None:
        """The single closest candidate's margin, for callers that only need one.

        Kept for backward compatibility with call sites written against the
        old one-rival model; new code should read ``margins`` directly.
        """
        return self.margins[0] if self.margins else None


@dataclass
class ChainAnalysis:
    """Complete Tier-1B analysis for one chain."""

    chain_id: str
    member_count: int
    evidence: IndexedChainEvidence
    descriptors: DescriptorSet
    graybox: GrayBoxMetadata
    members: dict[str, MemberAnalysis] = field(default_factory=dict)
    local_candidates: tuple[BlockingCandidate, ...] = ()
    auto_title: str | None = None
    config_version: str | None = None
    #: Set for |C|=1, where pair-based analysis is NOT_APPLICABLE.
    singleton: bool = False
    #: Wall-clock phase timings for benchmark attribution, not methodology data.
    phase_durations: dict[str, float] = field(default_factory=dict)
    #: ADR-0025 registry snapshot: parameter path -> source category.
    parameter_provenance: dict[str, str] = field(default_factory=dict)
    failure_domains: tuple[FailureDomainEvidence, ...] = ()

    @property
    def audit_graph_mode(self):
        return self.evidence.audit_graph_mode

    def role_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for analysis in self.members.values():
            key = analysis.role.verdict.value
            counts[key] = counts.get(key, 0) + 1
        return counts


def _membership_support_rank_key(
    item: tuple[str, MembershipSupport],
) -> tuple[float, str]:
    """Rank computable zero support ahead of unavailable support."""
    alarm_id, membership = item
    support = membership.support
    return (-(support if support is not None else -1.0), alarm_id)


def _rival_statistics(
    package: IngestedPackage,
    alarm_id: str,
    rival_chain_id: str,
    *,
    taxonomy: AlarmTaxonomy,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
    d_max: int = DEFAULT_D_MAX,
) -> ChannelStatistics:
    """Accumulate ``Fit_g(x, C')`` statistics for one member against a rival chain.

    Only channels computable without extra inputs are used, so a rival comparison
    never fabricates topology or delay evidence.
    """
    rival_members = package.members_of(rival_chain_id)
    alarm = package.alarms[alarm_id]
    rival_alarms = [package.alarms[m] for m in rival_members if m in package.alarms]

    statistics = ChannelStatistics(
        chain_id=rival_chain_id,
        members=tuple([alarm_id, *(a.alarm_id for a in rival_alarms)]),
    )
    segmentation = segment_bursts(
        [alarm, *rival_alarms], silent_gap_seconds=silent_gap_seconds
    )
    topology = build_topology_graph(package, relation_types=PHYSICAL_RELATIONS)
    resolver = ResourceResolver.from_package(package)

    for other in rival_alarms:
        if other.alarm_id == alarm_id:
            continue
        values: list[ChannelValue] = evaluate_entity_channels(alarm, other)
        values.append(evaluate_semantic_channel(alarm, other, taxonomy))
        values.append(evaluate_burst_channel(alarm, other, segmentation))
        values.append(
            evaluate_dep_hop_channel(
                alarm,
                other,
                graph=topology,
                resolver=resolver,
                d_max=d_max,
            )
        )
        statistics.record(alarm_id, other.alarm_id, values)
        statistics.pairs_counted += 1

    return statistics


def analyze_chain(
    package: IngestedPackage,
    chain_id: str,
    *,
    thresholds: RoleThresholds,
    mining_config: MiningConfig,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    predicate_index: PredicateIndex | None = None,
    u_local_k: int = DEFAULT_U_LOCAL_K,
    g_min: int = DEFAULT_G_MIN,
    contrastive_top_k: int = DEFAULT_CONTRASTIVE_TOP_K,
    enable_contrastive: bool = True,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
    max_values_per_field: int = DEFAULT_MAX_VALUES_PER_FIELD,
    redundancy_small_dt_seconds: int = DEFAULT_SMALL_DT_SECONDS,
    d_max: int = DEFAULT_D_MAX,
    lambda_dep: float = DEFAULT_LAMBDA_DEP,
    common_dependency_threshold: float = DEFAULT_THETA_CD,
) -> ChainAnalysis:
    """Run Tier-1B analysis for one chain."""
    analysis_started = perf_counter()
    chain = package.chains.get(chain_id)
    if chain is None:
        raise KeyError(f"unknown chain_id {chain_id!r}")

    evidence = evaluate_chain_indexed(
        package,
        chain_id,
        taxonomy=taxonomy,
        silent_gap_seconds=silent_gap_seconds,
        d_max=d_max,
        lambda_dep=lambda_dep,
        common_dependency_threshold=common_dependency_threshold,
    )
    graybox = adapt_graybox_metadata(package, chain_id)
    domain_evidence = failure_domains_for_chain(package, chain_id)
    statistics_done = perf_counter()

    # Descriptors run over the whole ingested snapshot as the universe.
    index = predicate_index or build_predicate_index(
        list(package.alarms.values()),
        max_values_per_field=max_values_per_field,
    )
    member_ids = set(package.members_of(chain_id))
    target = bitmap_of_members(index, member_ids)

    candidates = (
        tuple(blocking_candidates(package, chain_id, k=u_local_k))
        if enable_contrastive
        else ()
    )
    u_local = (
        local_universe_bitmap(
            package, list(candidates), index, target_chain_id=chain_id
        )
        if candidates
        else None
    )

    identity = tuple(
        mine_descriptors(
            index,
            target,
            config=mining_config,
            kind=DescriptorKind.IDENTITY,
            local_universe=u_local,
        )
    )
    contrastive: tuple[Descriptor, ...] = ()
    if u_local:
        contrastive = tuple(
            mine_descriptors(
                index,
                target,
                config=mining_config,
                kind=DescriptorKind.CONTRASTIVE,
                local_universe=u_local,
            )
        )

    descriptors = DescriptorSet(
        chain_id=chain_id,
        identity=identity,
        contrastive=contrastive,
        config_version=mining_config.config_version,
        identity_insufficient=not identity,
    )
    descriptors_done = perf_counter()

    analysis = ChainAnalysis(
        chain_id=chain_id,
        member_count=chain.member_count,
        evidence=evidence,
        descriptors=descriptors,
        graybox=graybox,
        local_candidates=candidates,
        auto_title=auto_chain_title(chain_id, descriptors, mining_config),
        config_version=thresholds.config_version,
        singleton=chain.is_singleton,
        failure_domains=domain_evidence,
        phase_durations={
            "indexed_statistics": statistics_done - analysis_started,
            "descriptors": descriptors_done - statistics_done,
        },
    )

    if chain.is_singleton:
        # Pair-based membership is NOT_APPLICABLE, never WEAK. STRUCTURAL is
        # also NOT_APPLICABLE: an audit graph needs at least an edge to exist.
        report = build_singleton_report(package, chain_id)
        for alarm_id in package.members_of(chain_id):
            support = membership_support_from_index(alarm_id, evidence.statistics)
            analysis.members[alarm_id] = MemberAnalysis(
                alarm_id=alarm_id,
                support=support,
                role=MembershipRole(
                    alarm_id=alarm_id,
                    verdict=report.membership_verdict,
                    support=support.support,
                    gate=GateResult(
                        passed=False,
                        availability_coverage=0.0,
                        computable_groups=0,
                        reason="singleton chain: pair evidence not applicable",
                    ),
                    config_version=thresholds.config_version,
                    reason="singleton chain",
                ),
                representativeness=representativeness(alarm_id, identity, index),
                margins=(),
                structural=StructuralRoleResult(
                    alarm_id=alarm_id,
                    role=StructuralRole.NOT_APPLICABLE,
                    is_articulation_point=False,
                    blocks_supported=0,
                    reason="singleton chain: no pair to audit",
                ),
                redundancy=None,
                failure_domains=tuple(
                    domain
                    for domain in domain_evidence
                    if alarm_id in domain.member_alarm_ids
                ),
            )
        analysis.phase_durations["membership_and_roles"] = (
            perf_counter() - descriptors_done
        )
        analysis.phase_durations["total"] = perf_counter() - analysis_started
        return analysis

    # Rank members by support so the CORE quantile can be applied.
    supports = {
        alarm_id: membership_support_from_index(alarm_id, evidence.statistics)
        for alarm_id in evidence.members
    }
    ranked = sorted(
        supports.items(),
        key=_membership_support_rank_key,
    )
    quantiles = {
        alarm_id: (position / (len(ranked) - 1) if len(ranked) > 1 else 0.0)
        for position, (alarm_id, _) in enumerate(ranked)
    }
    membership_done = perf_counter()

    # WHY-4 contrastive rivals: top-3 candidates from the blocking index
    # (§5, §11), not just the single closest one. ``candidates`` is already
    # ranked by blocking overlap, so this is a prefix, not a re-sort.
    rivals = top_contrastive_candidates(candidates, top_k=contrastive_top_k)

    rival_indexes = {
        rival.chain_id: RivalFitIndex.from_chain(
            package,
            rival.chain_id,
            taxonomy=taxonomy,
            silent_gap_seconds=silent_gap_seconds,
            d_max=d_max,
            lambda_dep=lambda_dep,
            common_dependency_threshold=common_dependency_threshold,
        )
        for rival in rivals
    }

    margins_by_member: dict[str, tuple[MarginResult, ...]] = {}
    for alarm_id in supports:
        margins_by_member[alarm_id] = tuple(
            margin_common(
                alarm_id,
                supports[alarm_id].group_fits,
                rival_indexes[rival.chain_id].group_fits_for(
                    package.alarms[alarm_id]
                ),
                compared_chain_id=rival.chain_id,
                g_min=g_min,
            )
            for rival in rivals
        )
    contrastive_done = perf_counter()

    member_alarms = package.alarms_of(chain_id)
    redundancy_by_member = classify_redundancy_all(
        member_alarms,
        index=index,
        descriptors=identity,
        small_dt_seconds=redundancy_small_dt_seconds,
    )
    redundancy_done = perf_counter()

    for alarm_id, support in supports.items():
        member_representativeness = representativeness(alarm_id, identity, index)
        margins = margins_by_member[alarm_id]

        # Role classification uses the closest candidate's margin: it is the
        # "nearest miss" contrast that decides CORE vs WEAK (§4B), while the
        # full top-3 stays available for the WHY-4 panel.
        primary_margin = margins[0] if margins else None

        role = classify_membership(
            support,
            thresholds=thresholds,
            chain_size=len(evidence.members),
            support_rank_quantile=quantiles[alarm_id],
            representativeness=member_representativeness,
            margin_common=primary_margin.margin if primary_margin else None,
        )
        analysis.members[alarm_id] = MemberAnalysis(
            alarm_id=alarm_id,
            support=support,
            role=role,
            representativeness=member_representativeness,
            margins=margins,
            structural=None,
            redundancy=redundancy_by_member[alarm_id],
            failure_domains=tuple(
                domain
                for domain in domain_evidence
                if alarm_id in domain.member_alarm_ids
            ),
        )

    analysis.phase_durations.update(
        {
            "membership_statistics": membership_done - descriptors_done,
            "contrastive": contrastive_done - membership_done,
            "redundancy": redundancy_done - contrastive_done,
            "role_assembly": perf_counter() - redundancy_done,
            "total": perf_counter() - analysis_started,
        }
    )

    return analysis


def analyze_chain_configured(
    package: IngestedPackage,
    chain_id: str,
    *,
    analysis_config,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    predicate_index: PredicateIndex | None = None,
    enable_contrastive: bool = True,
) -> ChainAnalysis:
    """Run Tier-1B from one validated ADR-0025 parameter registry.

    ``analyze_chain`` remains the explicit, pure orchestration API used by unit
    tests and controlled experiments.  Production adapters should prefer this
    wrapper so thresholds cannot drift across independently-created objects.
    """
    result = analyze_chain(
        package,
        chain_id,
        thresholds=analysis_config.role_thresholds(),
        mining_config=analysis_config.mining_config(),
        taxonomy=taxonomy,
        predicate_index=predicate_index,
        u_local_k=int(analysis_config.value("contrastive.local_universe_k")),
        g_min=int(analysis_config.value("contrastive.g_min")),
        contrastive_top_k=int(analysis_config.value("contrastive.top_k")),
        enable_contrastive=enable_contrastive,
        silent_gap_seconds=int(analysis_config.value("temporal.burst.gap_seconds")),
        max_values_per_field=int(
            analysis_config.value("descriptor.max_values_per_field")
        ),
        redundancy_small_dt_seconds=int(
            analysis_config.value("redundancy.small_dt_seconds")
        ),
        d_max=int(analysis_config.value("dependency.max_hop")),
        lambda_dep=float(analysis_config.value("dependency.lambda_dep")),
        common_dependency_threshold=float(
            analysis_config.value("dependency.common_support_threshold")
        ),
    )
    result.parameter_provenance = {
        path: configured.source.value
        for path, configured in analysis_config.parameters.items()
    }
    return result


def auto_chain_title(
    chain_id: str, descriptors: DescriptorSet, config: MiningConfig
) -> str:
    """Auto chain title from the top IDENTITY descriptor (§5, P0).

    Falls back to the chain ID when precision is too low, so a weak rule never
    becomes a confident-looking title.
    """
    top = descriptors.top_identity
    if top is None or top.metrics.precision < config.precision_global_min:
        return f"Chain {chain_id}"
    return f"{top.label} ({top.metrics.coverage:.0%} of chain)"

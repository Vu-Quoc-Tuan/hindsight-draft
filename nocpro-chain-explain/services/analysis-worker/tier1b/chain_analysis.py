"""Tier-1B chain analysis (§3, §4B, §5).

Wires the MVP pieces into one local analysis so role classification becomes
self-contained: ``Representativeness`` comes from mined IDENTITY descriptors and
``Margin_common`` from the contrastive comparison, instead of being supplied by a
caller.

Order matters and follows the spec's dependency chain:

    channels -> exact statistics -> Fit_g -> descriptors -> Representativeness
             -> U_local -> contrastive -> Margin_common -> role
             -> audit graph -> STRUCTURAL role
             -> REDUNDANCY role

Tier-1B never waits for Tier-2 (ADR-0014), so nothing here triggers deep dive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from libs.contracts import IngestedPackage

from audit import build_audit_graph, classify_structural_role
from audit.structural_role import StructuralRole, StructuralRoleResult
from channels import ChainEvidence, evaluate_chain_channels
from channels.base import ChannelValue
from channels.entity import evaluate_entity_channels
from channels.semantic import EMPTY_TAXONOMY, AlarmTaxonomy, evaluate_semantic_channel
from channels.temporal import evaluate_burst_channel, segment_bursts
from descriptor import (
    Descriptor,
    DescriptorKind,
    DescriptorSet,
    MiningConfig,
    PredicateIndex,
    bitmap_of_members,
    build_predicate_index,
    mine_descriptors,
    representativeness,
)
from descriptor.contrastive import (
    DEFAULT_G_MIN,
    DEFAULT_U_LOCAL_K,
    BlockingCandidate,
    MarginResult,
    blocking_candidates,
    local_universe_bitmap,
    margin_common,
)
from graybox import GrayBoxMetadata, adapt_graybox_metadata
from graybox.singleton import MembershipVerdict, build_singleton_report
from groups import (
    ChannelStatistics,
    GateResult,
    MembershipRole,
    MembershipSupport,
    RoleThresholds,
    classify_membership,
    membership_support,
)
from groups.fit import group_fits
from groups.redundancy import RedundancyResult, RedundancyRole, classify_redundancy


@dataclass
class MemberAnalysis:
    """Per-member analysis result across all three role axes (§4B)."""

    alarm_id: str
    support: MembershipSupport
    #: MEMBERSHIP axis: CORE / PERIPHERAL / WEAK / INSUFFICIENT_DATA.
    role: MembershipRole
    representativeness: float | None
    margin: MarginResult | None
    #: STRUCTURAL axis: CONNECTOR / NON_CONNECTOR.
    structural: StructuralRoleResult | None = None
    #: REDUNDANCY axis: NEAR_DUPLICATE_CANDIDATE / UNIQUE.
    redundancy: RedundancyResult | None = None


@dataclass
class ChainAnalysis:
    """Complete Tier-1B analysis for one chain."""

    chain_id: str
    member_count: int
    evidence: ChainEvidence
    descriptors: DescriptorSet
    graybox: GrayBoxMetadata
    members: dict[str, MemberAnalysis] = field(default_factory=dict)
    local_candidates: tuple[BlockingCandidate, ...] = ()
    auto_title: str | None = None
    config_version: str | None = None
    #: Set for |C|=1, where pair-based analysis is NOT_APPLICABLE.
    singleton: bool = False

    def role_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for analysis in self.members.values():
            key = analysis.role.verdict.value
            counts[key] = counts.get(key, 0) + 1
        return counts


def _rival_statistics(
    package: IngestedPackage,
    alarm_id: str,
    rival_chain_id: str,
    *,
    taxonomy: AlarmTaxonomy,
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
    segmentation = segment_bursts([alarm, *rival_alarms])

    for other in rival_alarms:
        if other.alarm_id == alarm_id:
            continue
        values: list[ChannelValue] = evaluate_entity_channels(alarm, other)
        values.append(evaluate_semantic_channel(alarm, other, taxonomy))
        values.append(evaluate_burst_channel(alarm, other, segmentation))
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
    enable_contrastive: bool = True,
) -> ChainAnalysis:
    """Run Tier-1B analysis for one chain."""
    chain = package.chains.get(chain_id)
    if chain is None:
        raise KeyError(f"unknown chain_id {chain_id!r}")

    evidence = evaluate_chain_channels(package, chain_id, taxonomy=taxonomy)
    graybox = adapt_graybox_metadata(package, chain_id)

    # Descriptors run over the whole ingested snapshot as the universe.
    index = predicate_index or build_predicate_index(list(package.alarms.values()))
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
    )

    if chain.is_singleton:
        # Pair-based membership is NOT_APPLICABLE, never WEAK. STRUCTURAL is
        # also NOT_APPLICABLE: an audit graph needs at least an edge to exist.
        report = build_singleton_report(package, chain_id)
        for alarm_id in package.members_of(chain_id):
            support = membership_support(alarm_id, evidence.statistics)
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
                margin=None,
                structural=StructuralRoleResult(
                    alarm_id=alarm_id,
                    role=StructuralRole.NOT_APPLICABLE,
                    is_articulation_point=False,
                    blocks_supported=0,
                    reason="singleton chain: no pair to audit",
                ),
                redundancy=None,
            )
        return analysis

    # Rank members by support so the CORE quantile can be applied.
    supports = {
        alarm_id: membership_support(alarm_id, evidence.statistics)
        for alarm_id in evidence.members
    }
    ranked = sorted(
        supports.items(),
        key=lambda item: (-(item[1].support or -1.0), item[0]),
    )
    quantiles = {
        alarm_id: (position / (len(ranked) - 1) if len(ranked) > 1 else 0.0)
        for position, (alarm_id, _) in enumerate(ranked)
    }

    rival = candidates[0].chain_id if candidates else None

    # STRUCTURAL axis: built once from the same audit graph the Audit Engine
    # uses (never the top-K visualization graph), per the three-graph rule.
    audit_graph = build_audit_graph(evidence.members, evidence.matrix.values)
    member_alarms = package.alarms_of(chain_id)

    for alarm_id, support in supports.items():
        member_representativeness = representativeness(alarm_id, identity, index)

        margin: MarginResult | None = None
        if rival is not None:
            rival_stats = _rival_statistics(
                package, alarm_id, rival, taxonomy=taxonomy
            )
            margin = margin_common(
                alarm_id,
                support.group_fits,
                tuple(group_fits(alarm_id, rival_stats)),
                compared_chain_id=rival,
                g_min=g_min,
            )

        role = classify_membership(
            support,
            thresholds=thresholds,
            chain_size=len(evidence.members),
            support_rank_quantile=quantiles[alarm_id],
            representativeness=member_representativeness,
            margin_common=margin.margin if margin else None,
        )
        structural = classify_structural_role(alarm_id, audit_graph)
        redundancy = classify_redundancy(
            alarm_id, member_alarms, index=index, descriptors=identity
        )
        analysis.members[alarm_id] = MemberAnalysis(
            alarm_id=alarm_id,
            support=support,
            role=role,
            representativeness=member_representativeness,
            margin=margin,
            structural=structural,
            redundancy=redundancy,
        )

    return analysis


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

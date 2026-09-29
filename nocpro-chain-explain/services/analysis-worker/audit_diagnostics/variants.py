"""Leave-one-effective-group-out transforms of exact Audit evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Sequence

from audit import AuditGraph, build_audit_graph
from audit_diagnostics.contracts import (
    EdgeTransition,
    EdgeTransitionKind,
    EdgeTransitionSummary,
    CandidateRegionSummary,
    FrozenCandidate,
    GroupKey,
    InvariantResult,
    PopulationRegion,
    RemovedGroupState,
)
from channels.base import ChannelValue, EvidenceState
from libs.provenance import build_derivation_groups, normalize_pair_channels


class LogoInvariantError(ValueError):
    """Pure group deletion violated the canonical Audit graph invariants."""


@dataclass(frozen=True)
class LogoResult:
    pair_channel_values: Mapping[tuple[str, str], tuple[ChannelValue, ...]]
    baseline_pair_channel_values: Mapping[tuple[str, str], tuple[ChannelValue, ...]]
    graph: AuditGraph
    transitions: tuple[EdgeTransition, ...]
    summary: EdgeTransitionSummary
    removed_group_state_by_pair: Mapping[tuple[str, str], RemovedGroupState]
    invariants: tuple[InvariantResult, ...]


def apply_logo(
    members: Sequence[str],
    pair_channel_values: Mapping[tuple[str, str], Sequence[ChannelValue]],
    baseline_graph: AuditGraph,
    excluded_group: GroupKey,
    *,
    epsilon_num: float = 1e-12,
) -> LogoResult:
    """Remove exactly one full effective group, then rebuild the canonical graph."""
    if not excluded_group.audit_eligible:
        raise ValueError("LOGO can remove only an audit-eligible effective group")
    if epsilon_num <= 0:
        raise ValueError("epsilon_num must be positive")
    normalized_input: dict[tuple[str, str], tuple[ChannelValue, ...]] = {}
    for raw_pair, raw_values in pair_channel_values.items():
        if len(raw_pair) != 2 or raw_pair[0] == raw_pair[1]:
            raise ValueError(f"invalid unordered pair key {raw_pair!r}")
        key = tuple(sorted(raw_pair))
        if key in normalized_input:
            raise ValueError(f"duplicate unordered pair key {key!r}")
        normalized_input[key] = tuple(raw_values)
    canonical_baseline = build_audit_graph(list(members), normalized_input)
    if canonical_baseline.members != baseline_graph.members or canonical_baseline.edges != baseline_graph.edges:
        raise LogoInvariantError("supplied baseline graph does not match canonical pair evidence")

    transformed: dict[tuple[str, str], tuple[ChannelValue, ...]] = {}
    removed_by_pair: dict[tuple[str, str], RemovedGroupState] = {}
    for pair, raw_values in normalized_input.items():
        retained: list[ChannelValue] = []
        removed: list[ChannelValue] = []
        for value in raw_values:
            single = normalize_pair_channels((value,))[0]
            actual = GroupKey.from_effective_key(
                build_derivation_groups([single])[0].key
            )
            if actual == excluded_group:
                removed.append(value)
            else:
                retained.append(value)
        transformed[pair] = tuple(retained)
        removed_by_pair[pair] = _removed_state(removed)

    variant_graph = build_audit_graph(list(members), dict(transformed))
    baseline_edges = {_pair(edge.node_a, edge.node_b): edge for edge in baseline_graph.edges}
    variant_edges = {_pair(edge.node_a, edge.node_b): edge for edge in variant_graph.edges}
    all_edge_pairs = sorted(set(baseline_edges) | set(variant_edges))
    transitions: list[EdgeTransition] = []
    transition_counts: Counter[EdgeTransitionKind] = Counter()
    removed_weight = 0.0
    positive_delta = 0.0
    negative_delta_abs = 0.0
    added_edges: list[tuple[str, str]] = []
    support_increased: list[tuple[str, str]] = []

    for pair in all_edge_pairs:
        before = baseline_edges.get(pair)
        after = variant_edges.get(pair)
        before_available, before_support, before_keys = _pair_group_counts(
            normalized_input.get(pair, ())
        )
        after_values = transformed.get(pair, ())
        after_available, after_support, after_keys = _pair_group_counts(after_values)
        if after_support > before_support:
            support_increased.append(pair)
        if before is None and after is not None:
            added_edges.append(pair)
            kind = EdgeTransitionKind.ADDED
            before_weight = None
            after_weight = after.weight
            removed_state = removed_by_pair.get(pair, RemovedGroupState.ABSENT)
            reason = "pure LOGO cannot add an Audit edge"
        elif before is not None and after is None:
            if after_support >= 2:
                raise LogoInvariantError(
                    f"baseline edge {pair} disappeared with {after_support} supporting groups"
                )
            kind = EdgeTransitionKind.REMOVED_MIN_SUPPORT_GROUPS
            before_weight = before.weight
            after_weight = None
            removed_weight += before.weight
            removed_state = removed_by_pair.get(pair, RemovedGroupState.ABSENT)
            reason = "fewer than two audit-eligible supporting groups remain"
        else:
            assert before is not None and after is not None
            delta = after.weight - before.weight
            before_weight = before.weight
            after_weight = after.weight
            removed_state = removed_by_pair.get(pair, RemovedGroupState.ABSENT)
            if abs(delta) <= epsilon_num:
                kind = EdgeTransitionKind.RETAINED_UNCHANGED
                reason = None
            elif delta > 0:
                kind = EdgeTransitionKind.RETAINED_WEIGHT_INCREASED
                positive_delta += delta
                reason = (
                    "removed available neutral group reduced the edge denominator"
                    if removed_state is RemovedGroupState.NEUTRAL
                    else "canonical available-group denominator and support numerator changed"
                )
            else:
                kind = EdgeTransitionKind.RETAINED_WEIGHT_DECREASED
                negative_delta_abs += abs(delta)
                reason = "remaining group support changed under canonical rebuild"
        transition_counts[kind] += 1
        transitions.append(
            EdgeTransition(
                pair={"left": pair[0], "right": pair[1]},
                transition=kind,
                baseline_weight=before_weight,
                variant_weight=after_weight,
                baseline_available_group_count=before_available,
                variant_available_group_count=after_available,
                baseline_support_group_count=before_support,
                variant_support_group_count=after_support,
                removed_group_state=removed_state,
                baseline_group_keys=before_keys,
                variant_group_keys=after_keys,
                reason=reason,
            )
        )

    if added_edges or support_increased:
        raise LogoInvariantError(
            "pure LOGO invariant failed: "
            f"added_edges={len(added_edges)}, support_increases={len(support_increased)}"
        )
    if variant_graph.members != baseline_graph.members:
        raise LogoInvariantError("pure LOGO must preserve the member/isolate universe")

    boundary_pairs = [
        pair for pair, values in normalized_input.items()
        if _pair_group_counts(values)[1] == 2
    ]
    boundary_states = Counter(removed_by_pair.get(pair, RemovedGroupState.ABSENT) for pair in boundary_pairs)
    summary = EdgeTransitionSummary(
        counts=dict(transition_counts),
        removed_baseline_weight=removed_weight,
        retained_positive_weight_delta=positive_delta,
        retained_negative_weight_delta_absolute=negative_delta_abs,
        boundary_pair_count=len(boundary_pairs),
        boundary_population_count=len(members) * (len(members) - 1) // 2,
        boundary_removed_group_state_counts=dict(boundary_states),
    )
    invariants = (
        InvariantResult(invariant_id="logo_no_added_edges", passed=not added_edges),
        InvariantResult(invariant_id="logo_support_group_count_nonincreasing", passed=not support_increased),
        InvariantResult(
            invariant_id="logo_member_universe_preserved",
            passed=variant_graph.members == baseline_graph.members,
        ),
    )
    return LogoResult(
        pair_channel_values=transformed,
        baseline_pair_channel_values=normalized_input,
        graph=variant_graph,
        transitions=tuple(transitions),
        summary=summary,
        removed_group_state_by_pair=removed_by_pair,
        invariants=invariants,
    )


def summarize_candidate_regions(
    result: LogoResult,
    baseline_graph: AuditGraph,
    candidates: Sequence[FrozenCandidate],
) -> tuple[CandidateRegionSummary, ...]:
    """Aggregate graph transitions by fixed candidate and its four pair regions."""
    candidate_summaries: list[CandidateRegionSummary] = []
    transitions_by_pair = {
        (item.pair.left, item.pair.right): item for item in result.transitions
    }
    baseline_edges = {_pair(edge.node_a, edge.node_b) for edge in baseline_graph.edges}
    variant_edges = {_pair(edge.node_a, edge.node_b) for edge in result.graph.edges}

    for candidate in candidates:
        side_a, side_b = set(candidate.side_a), set(candidate.side_b)
        pair_regions = {
            PopulationRegion.ALL: tuple(combinations(candidate.members, 2)),
            PopulationRegion.WITHIN_A: tuple(combinations(candidate.side_a, 2)),
            PopulationRegion.WITHIN_B: tuple(combinations(candidate.side_b, 2)),
            PopulationRegion.CROSS: tuple(
                sorted(tuple(sorted((left, right))) for left in side_a for right in side_b)
            ),
        }
        for region, raw_pairs in pair_regions.items():
            pair_keys = tuple(sorted(tuple(sorted(pair)) for pair in raw_pairs))
            pair_set = set(pair_keys)
            region_transitions = [
                transitions_by_pair[pair]
                for pair in sorted(pair_set & set(transitions_by_pair))
            ]
            transition_counts = Counter(item.transition for item in region_transitions)
            removed_weight = sum(
                item.baseline_weight or 0.0
                for item in region_transitions
                if item.transition is EdgeTransitionKind.REMOVED_MIN_SUPPORT_GROUPS
            )
            positive_delta = sum(
                (item.variant_weight or 0.0) - (item.baseline_weight or 0.0)
                for item in region_transitions
                if item.transition is EdgeTransitionKind.RETAINED_WEIGHT_INCREASED
            )
            negative_delta = sum(
                (item.baseline_weight or 0.0) - (item.variant_weight or 0.0)
                for item in region_transitions
                if item.transition is EdgeTransitionKind.RETAINED_WEIGHT_DECREASED
            )
            boundary_pairs = [
                pair for pair in pair_keys
                if _pair_group_counts(result.baseline_pair_channel_values.get(pair, ()))[1] == 2
            ]
            boundary_states = Counter(
                result.removed_group_state_by_pair.get(pair, RemovedGroupState.ABSENT)
                for pair in boundary_pairs
            )
            baseline_region_edges = baseline_edges & pair_set
            variant_region_edges = variant_edges & pair_set
            region_nodes = (
                set(candidate.members)
                if region in (PopulationRegion.ALL, PopulationRegion.CROSS)
                else side_a if region is PopulationRegion.WITHIN_A else side_b
            )
            baseline_incident = {node for edge in baseline_region_edges for node in edge}
            variant_incident = {node for edge in variant_region_edges for node in edge}
            candidate_summaries.append(CandidateRegionSummary(
                candidate_id=candidate.partition_id,
                region=region,
                population_pair_count=len(pair_keys),
                baseline_region_edge_count=len(baseline_region_edges),
                variant_region_edge_count=len(variant_region_edges),
                baseline_region_isolate_count=len(region_nodes - baseline_incident),
                variant_region_isolate_count=len(region_nodes - variant_incident),
                edge_transitions=EdgeTransitionSummary(
                    counts=dict(transition_counts),
                    removed_baseline_weight=removed_weight,
                    retained_positive_weight_delta=positive_delta,
                    retained_negative_weight_delta_absolute=negative_delta,
                    boundary_pair_count=len(boundary_pairs),
                    boundary_population_count=len(pair_keys),
                    boundary_removed_group_state_counts=dict(boundary_states),
                ),
            ))
    return tuple(candidate_summaries)


def _pair_group_counts(
    values: Sequence[ChannelValue],
) -> tuple[int, int, tuple[GroupKey, ...]]:
    groups = build_derivation_groups(normalize_pair_channels(values))
    audit_groups = [group for group in groups if group.key.audit_eligible]
    available = [group for group in audit_groups if group.availability]
    supporting = [group for group in available if group.supports]
    available_keys = tuple(
        GroupKey.from_effective_key(group.key)
        for group in sorted(audit_groups, key=lambda item: _group_sort_key(GroupKey.from_effective_key(item.key)))
    )
    return len(available), len(supporting), available_keys


def _removed_state(values: Sequence[ChannelValue]) -> RemovedGroupState:
    if not values:
        return RemovedGroupState.ABSENT
    if any(value.availability and value.state is EvidenceState.SUPPORT for value in values):
        return RemovedGroupState.SUPPORT
    if any(value.availability for value in values):
        return RemovedGroupState.NEUTRAL
    return RemovedGroupState.UNAVAILABLE


def _pair(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def _group_sort_key(key: GroupKey) -> tuple[str, str, bool, bool, bool]:
    return (
        key.derivation_tag,
        key.provenance_class.value,
        key.explain_eligible,
        key.role_eligible,
        key.audit_eligible,
    )

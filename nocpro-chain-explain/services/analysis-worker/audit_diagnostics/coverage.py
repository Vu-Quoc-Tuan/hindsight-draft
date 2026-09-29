"""Exact, scope-aware coverage over the complete unordered pair population."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence

from audit_diagnostics.contracts import (
    ApplicabilityCounts,
    ComputationStatus,
    CoverageRatios,
    CoverageRow,
    FrozenCandidate,
    GroupKey,
    InvocationStatus,
    PairKey,
    PairUniverse,
    PopulationRegion,
    ScopeState,
    ScopeEvidenceStateCount,
)
from channels.base import ChannelValue, EvidenceState
from libs.provenance import build_derivation_groups, normalize_pair_channels

from .scope import ScopeEvaluatorInconsistency, ScopePolicy, classify_scope


@dataclass(frozen=True)
class CoverageResult:
    pair_universe: PairUniverse
    channel_rows_all: tuple[CoverageRow, ...]
    group_rows_all: tuple[CoverageRow, ...]
    by_candidate_region: Mapping[str, tuple[CoverageRow, ...]]
    channel_ids: tuple[str, ...]
    group_keys: tuple[GroupKey, ...]
    registry_complete: bool
    pair_matrix_complete: bool
    issues: tuple[str, ...]


def aggregate_coverage(
    members: Sequence[str],
    pair_channel_values: Mapping[tuple[str, str], Sequence[ChannelValue]],
    *,
    candidates: Sequence[FrozenCandidate],
    policy: ScopePolicy,
    expected_channel_ids: Sequence[str],
    expected_group_channels: Mapping[GroupKey, Sequence[str]] | None = None,
    pair_scope_metadata: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> CoverageResult:
    """Aggregate exact coverage without using edge presence as a denominator.

    ``expected_channel_ids`` comes from the pre-registered execution profile,
    including dynamic common-dependency providers resolved from the snapshot.
    An omitted invocation is retained as ``NOT_EVALUATED`` and makes the matrix
    partial; the runner must not publish such a result as exact.
    """
    member_tuple = tuple(members)
    if len(set(member_tuple)) != len(member_tuple):
        raise ValueError("duplicate member IDs in diagnostic population")
    if any(not isinstance(member, str) or not member for member in member_tuple):
        raise ValueError("member IDs must be non-empty strings")
    expected_pairs = tuple(
        PairKey(left=left, right=right)
        for left, right in combinations(sorted(member_tuple), 2)
    )
    expected_keys = {(pair.left, pair.right) for pair in expected_pairs}
    supplied_keys: set[tuple[str, str]] = set()
    normalized_values_by_pair: dict[tuple[str, str], Sequence[ChannelValue]] = {}
    for raw_key, values in pair_channel_values.items():
        if len(raw_key) != 2 or raw_key[0] == raw_key[1]:
            raise ValueError(f"invalid pair-matrix key {raw_key!r}")
        key = tuple(sorted(raw_key))
        if key in supplied_keys:
            raise ValueError(f"duplicate unordered pair in pair matrix {key!r}")
        if not set(key) <= set(member_tuple):
            raise ValueError(f"pair matrix has endpoints outside chain: {key!r}")
        supplied_keys.add(key)
        normalized_values_by_pair[key] = values
    pair_matrix_complete = supplied_keys == expected_keys
    pair_universe = PairUniverse(
        members=tuple(sorted(member_tuple)),
        # Membership defines the population even if invocation is incomplete;
        # absent rows stay NOT_EVALUATED rather than disappearing from N_total.
        pairs=expected_pairs,
        computation_status=(
            ComputationStatus.EXACT if pair_matrix_complete else ComputationStatus.PARTIAL
        ),
    )

    channels = tuple(sorted(set(expected_channel_ids)))
    if len(channels) != len(expected_channel_ids):
        raise ValueError("duplicate channel IDs in resolved execution registry")
    issues: list[str] = []
    observed_ids = {
        value.channel_id
        for values in normalized_values_by_pair.values()
        for value in values
    }
    registry_complete = True
    for channel_id in channels:
        if policy.definition_for(channel_id) is None:
            registry_complete = False
            issues.append(f"SCOPE_RULE_UNDEFINED:{channel_id}")
    unexpected = observed_ids - set(channels)
    missing_registry = set(channels) - observed_ids if expected_pairs else set()
    if unexpected:
        registry_complete = False
        issues.extend(f"CHANNEL_NOT_REGISTERED:{channel_id}" for channel_id in sorted(unexpected))
    if missing_registry:
        registry_complete = False
        issues.extend(f"EXPECTED_CHANNEL_NOT_OBSERVED:{channel_id}" for channel_id in sorted(missing_registry))

    key_to_channels: dict[GroupKey, set[str]] = {}
    expected_channel_to_group: dict[str, GroupKey] = {}
    for group, group_channels in (expected_group_channels or {}).items():
        channel_set = set(group_channels)
        if not channel_set:
            raise ValueError(f"registered effective group {group!r} has no channels")
        if not channel_set <= set(channels):
            raise ValueError(
                f"effective group registry contains unregistered channels: "
                f"{sorted(channel_set - set(channels))}"
            )
        key_to_channels[group] = channel_set
        for channel_id in channel_set:
            existing = expected_channel_to_group.setdefault(channel_id, group)
            if existing != group:
                raise ValueError(f"channel {channel_id!r} is assigned to more than one expected group")
    channel_to_group: dict[str, GroupKey] = {}
    for values in normalized_values_by_pair.values():
        normalized = normalize_pair_channels(values)
        pair_channel_ids = [channel.channel_id for channel in normalized]
        if len(pair_channel_ids) != len(set(pair_channel_ids)):
            raise ValueError("duplicate channel values for an unordered pair")
        for group in build_derivation_groups(normalized):
            group_key = GroupKey.from_effective_key(group.key)
            current = key_to_channels.setdefault(group_key, set())
            for channel in group.channels:
                if channel.channel_id not in channels:
                    continue
                if expected_group_channels is not None and group_key not in expected_group_channels:
                    registry_complete = False
                    issues.append(f"UNREGISTERED_EFFECTIVE_GROUP:{channel.channel_id}")
                expected_group = expected_channel_to_group.get(channel.channel_id)
                if expected_group is not None and expected_group != group_key:
                    registry_complete = False
                    issues.append(f"CHANNEL_GROUP_IDENTITY_DRIFT:{channel.channel_id}")
                current.add(channel.channel_id)
                previous = channel_to_group.setdefault(channel.channel_id, group_key)
                if previous != group_key:
                    registry_complete = False
                    issues.append(f"CHANNEL_GROUP_IDENTITY_DRIFT:{channel.channel_id}")
    group_keys = tuple(sorted(
        key_to_channels,
        key=lambda item: (
            item.derivation_tag, item.provenance_class.value, item.explain_eligible,
            item.role_eligible, item.audit_eligible,
        ),
    ))
    if expected_pairs:
        expected_groups_missing = [
            channel_id for channel_id in channels if channel_id not in channel_to_group
        ]
        if expected_groups_missing:
            registry_complete = False
            issues.extend(
                f"EXPECTED_GROUP_IDENTITY_MISSING:{channel_id}"
                for channel_id in expected_groups_missing
            )

    # All region populations partition the exact unordered universe.
    channel_rows_all = _aggregate_channel_rows(
        pair_universe.pairs,
        channels,
        normalized_values_by_pair,
        policy,
        pair_scope_metadata or {},
        pair_matrix_complete=pair_matrix_complete,
    )
    group_rows_all = _aggregate_group_rows(
        pair_universe.pairs,
        group_keys,
        key_to_channels,
        normalized_values_by_pair,
        policy,
        pair_scope_metadata or {},
        pair_matrix_complete=pair_matrix_complete,
    )

    by_candidate_region: dict[str, tuple[CoverageRow, ...]] = {}
    for candidate in candidates:
        side_a = set(candidate.side_a)
        side_b = set(candidate.side_b)
        partitions = {
            PopulationRegion.ALL: pair_universe.pairs,
            PopulationRegion.WITHIN_A: tuple(
                pair for pair in pair_universe.pairs
                if pair.left in side_a and pair.right in side_a
            ),
            PopulationRegion.WITHIN_B: tuple(
                pair for pair in pair_universe.pairs
                if pair.left in side_b and pair.right in side_b
            ),
            PopulationRegion.CROSS: tuple(
                pair for pair in pair_universe.pairs
                if (pair.left in side_a and pair.right in side_b)
                or (pair.left in side_b and pair.right in side_a)
            ),
        }
        all_region_rows: list[CoverageRow] = []
        for region, pairs in partitions.items():
            all_region_rows.extend(
                _aggregate_channel_rows(
                    pairs, channels, normalized_values_by_pair, policy,
                    pair_scope_metadata or {}, pair_matrix_complete=pair_matrix_complete,
                    population_id=candidate.partition_id, region=region,
                )
            )
            all_region_rows.extend(
                _aggregate_group_rows(
                    pairs, group_keys, key_to_channels, normalized_values_by_pair, policy,
                    pair_scope_metadata or {}, pair_matrix_complete=pair_matrix_complete,
                    population_id=candidate.partition_id, region=region,
                )
            )
        by_candidate_region[candidate.partition_id] = tuple(all_region_rows)

    if not pair_matrix_complete:
        issues.append("PAIR_MATRIX_INCOMPLETE")
    return CoverageResult(
        pair_universe=pair_universe,
        channel_rows_all=channel_rows_all,
        group_rows_all=group_rows_all,
        by_candidate_region=by_candidate_region,
        channel_ids=channels,
        group_keys=group_keys,
        registry_complete=registry_complete,
        pair_matrix_complete=pair_matrix_complete,
        issues=tuple(sorted(set(issues))),
    )


def _aggregate_channel_rows(
    pairs: Sequence[PairKey],
    channel_ids: Sequence[str],
    values_by_pair: Mapping[tuple[str, str], Sequence[ChannelValue]],
    policy: ScopePolicy,
    metadata: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    pair_matrix_complete: bool,
    population_id: str = "all",
    region: PopulationRegion = PopulationRegion.ALL,
) -> tuple[CoverageRow, ...]:
    rows: list[CoverageRow] = []
    for channel_id in channel_ids:
        decisions: list[tuple[ScopeState, EvidenceState | None, InvocationStatus, str | None]] = []
        primary_reasons: Counter[str] = Counter()
        invocation_counts: Counter[InvocationStatus] = Counter()
        evidence_state_counts: Counter[tuple[ScopeState, InvocationStatus, EvidenceState | None]] = Counter()
        for pair in pairs:
            pair_key = (pair.left, pair.right)
            channel = _find_channel(values_by_pair.get(pair_key, ()), channel_id)
            invocation = InvocationStatus.EVALUATED if channel is not None else InvocationStatus.NOT_EVALUATED
            evidence_state = channel.state if channel is not None else None
            decision = classify_scope(
                pair_key, channel_id, policy,
                invocation=invocation,
                evidence_state=evidence_state,
                pair_scope_metadata=metadata.get(pair_key),
            )
            if channel is not None and decision.scope is ScopeState.NOT_APPLICABLE and channel.availability:
                raise ScopeEvaluatorInconsistency(
                    f"{channel_id} produced available evidence outside registered scope for {pair_key}"
                )
            invocation_counts[invocation] += 1
            evidence_state_counts[(decision.scope, invocation, evidence_state)] += 1
            if decision.primary_reason is not None:
                primary_reasons[decision.primary_reason.code] += 1
            elif decision.scope is ScopeState.NOT_APPLICABLE:
                primary_reasons["NOT_APPLICABLE_BY_REGISTERED_RULE"] += 1
            elif channel is None:
                primary_reasons["CHANNEL_NOT_EVALUATED"] += 1
            elif channel.state is EvidenceState.UNAVAILABLE:
                primary_reasons[_evidence_reason_code(channel)] += 1
            decisions.append((decision.scope, evidence_state, invocation, channel.channel_id if channel else None))
        counts = _count_decisions(decisions)
        rows.append(_coverage_row(
            population_id, region, channel_id=channel_id, counts=counts,
            policy=policy, primary_reasons=primary_reasons,
            invocation_counts=invocation_counts,
            scope_evidence_state_counts=evidence_state_counts,
            computation_status=(
                ComputationStatus.EXACT
                if pair_matrix_complete and all(item[2] is InvocationStatus.EVALUATED for item in decisions)
                else ComputationStatus.PARTIAL
            ),
        ))
    return tuple(rows)


def _aggregate_group_rows(
    pairs: Sequence[PairKey],
    group_keys: Sequence[GroupKey],
    channels_by_group: Mapping[GroupKey, set[str]],
    values_by_pair: Mapping[tuple[str, str], Sequence[ChannelValue]],
    policy: ScopePolicy,
    metadata: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    pair_matrix_complete: bool,
    population_id: str = "all",
    region: PopulationRegion = PopulationRegion.ALL,
) -> tuple[CoverageRow, ...]:
    rows: list[CoverageRow] = []
    for group_key in group_keys:
        channel_ids = tuple(sorted(channels_by_group[group_key]))
        decisions: list[tuple[ScopeState, EvidenceState | None, InvocationStatus, int, int, int]] = []
        primary_reasons: Counter[str] = Counter()
        invocation_counts: Counter[InvocationStatus] = Counter()
        partial_observability: Counter[str] = Counter()
        evidence_state_counts: Counter[tuple[ScopeState, InvocationStatus, EvidenceState | None]] = Counter()
        for pair in pairs:
            pair_key = (pair.left, pair.right)
            channels = [
                value for value in values_by_pair.get(pair_key, ())
                if value.channel_id in channel_ids
            ]
            channel_by_id = {value.channel_id: value for value in channels}
            if len(channel_by_id) != len(channels):
                raise ValueError(f"duplicate group channel value for pair {pair_key!r}")
            scope_decisions = [
                classify_scope(
                    pair_key,
                    channel_id,
                    policy,
                    invocation=(InvocationStatus.EVALUATED if channel_id in channel_by_id else InvocationStatus.NOT_EVALUATED),
                    evidence_state=(channel_by_id[channel_id].state if channel_id in channel_by_id else None),
                    pair_scope_metadata=metadata.get(pair_key),
                )
                for channel_id in channel_ids
            ]
            for decision, value in zip(scope_decisions, (channel_by_id.get(x) for x in channel_ids)):
                if value is not None and decision.scope is ScopeState.NOT_APPLICABLE and value.availability:
                    raise ScopeEvaluatorInconsistency(
                        f"{value.channel_id} produced available evidence outside registered scope for {pair_key}"
                    )
            if any(decision.scope is ScopeState.APPLICABLE for decision in scope_decisions):
                scope_state = ScopeState.APPLICABLE
            elif any(decision.scope is ScopeState.UNKNOWN_APPLICABILITY for decision in scope_decisions):
                scope_state = ScopeState.UNKNOWN_APPLICABILITY
            else:
                scope_state = ScopeState.NOT_APPLICABLE
            observed_values = list(channel_by_id.values())
            if any(value.availability and value.state is EvidenceState.SUPPORT for value in channel_by_id.values()):
                group_evidence = EvidenceState.SUPPORT
            elif any(value.availability for value in channel_by_id.values()):
                group_evidence = EvidenceState.NEUTRAL
            elif channel_by_id:
                group_evidence = EvidenceState.UNAVAILABLE
            else:
                group_evidence = None
            invocation = (
                InvocationStatus.EVALUATED if channel_by_id else InvocationStatus.NOT_EVALUATED
            )
            available_channel_count = sum(value.availability for value in channel_by_id.values())
            expected_group_channel_count = len(channel_ids)
            applicable_channel_count = sum(
                decision.scope is ScopeState.APPLICABLE for decision in scope_decisions
            )
            unknown_channel_count = sum(
                decision.scope is ScopeState.UNKNOWN_APPLICABILITY for decision in scope_decisions
            )
            decisions.append((
                scope_state, group_evidence, invocation, available_channel_count,
                expected_group_channel_count, len(channel_by_id),
            ))
            invocation_counts[invocation] += 1
            evidence_state_counts[(scope_state, invocation, group_evidence)] += 1
            if group_evidence is EvidenceState.UNAVAILABLE and scope_state is ScopeState.APPLICABLE:
                reason_codes = [
                    _evidence_reason_code(value)
                    for value in channel_by_id.values()
                    if value.state is EvidenceState.UNAVAILABLE
                ]
                scope_reason_codes = [
                    decision.primary_reason.code
                    for decision in scope_decisions
                    if decision.scope is ScopeState.APPLICABLE and decision.primary_reason is not None
                ]
                selected = reason_codes or scope_reason_codes
                primary_reasons[sorted(selected)[0] if selected else "CHANNEL_NOT_EVALUATED"] += 1
            elif scope_state is ScopeState.UNKNOWN_APPLICABILITY:
                reason_codes = [
                    decision.primary_reason.code
                    for decision in scope_decisions
                    if decision.scope is ScopeState.UNKNOWN_APPLICABILITY
                    and decision.primary_reason is not None
                ]
                primary_reasons[sorted(reason_codes)[0] if reason_codes else "UNKNOWN_APPLICABILITY"] += 1
            elif scope_state is ScopeState.NOT_APPLICABLE:
                primary_reasons["NOT_APPLICABLE_BY_REGISTERED_RULE"] += 1
            if scope_state is ScopeState.NOT_APPLICABLE:
                partial_observability["NO_APPLICABLE_CHANNEL"] += 1
            elif unknown_channel_count and not applicable_channel_count:
                partial_observability["APPLICABILITY_UNKNOWN"] += 1
            elif len(channel_by_id) < expected_group_channel_count:
                partial_observability["INVOCATION_GAP"] += 1
            elif available_channel_count == applicable_channel_count:
                partial_observability["ALL_APPLICABLE_CHANNELS_AVAILABLE"] += 1
            elif available_channel_count > 0:
                partial_observability["PARTIALLY_AVAILABLE"] += 1
            else:
                partial_observability["NO_CHANNEL_AVAILABLE"] += 1
        counts = _count_decisions(decisions)
        status = (
            ComputationStatus.EXACT
            if pair_matrix_complete
            and all(item[2] is InvocationStatus.EVALUATED and item[5] == item[4] for item in decisions)
            else ComputationStatus.PARTIAL
        )
        rows.append(_coverage_row(
            population_id, region, effective_group_key=group_key,
            counts=counts, policy=policy, primary_reasons=primary_reasons,
            invocation_counts=invocation_counts,
            scope_evidence_state_counts=evidence_state_counts,
            partial_group_observability_counts=partial_observability,
            rule_ids=tuple(sorted({
                rule_id
                for channel_id in channel_ids
                if (definition := policy.definition_for(channel_id)) is not None
                for rule_id in (definition.scope_rule_id, *definition.not_applicable_rule_ids)
            })),
            computation_status=status,
        ))
    return tuple(rows)


def _count_decisions(decisions) -> ApplicabilityCounts:
    total = len(decisions)
    applicable = sum(scope is ScopeState.APPLICABLE for scope, *_ in decisions)
    not_applicable = sum(scope is ScopeState.NOT_APPLICABLE for scope, *_ in decisions)
    unknown = sum(scope is ScopeState.UNKNOWN_APPLICABILITY for scope, *_ in decisions)
    support = sum(evidence is EvidenceState.SUPPORT for scope, evidence, *_ in decisions if scope is ScopeState.APPLICABLE)
    neutral = sum(evidence is EvidenceState.NEUTRAL for scope, evidence, *_ in decisions if scope is ScopeState.APPLICABLE)
    available = support + neutral
    return ApplicabilityCounts(
        total=total,
        applicable=applicable,
        not_applicable=not_applicable,
        unknown_applicability=unknown,
        available=available,
        unavailable=applicable - available,
        support=support,
        neutral=neutral,
    )


def _coverage_row(
    population_id: str,
    region: PopulationRegion,
    *,
    counts: ApplicabilityCounts,
    policy: ScopePolicy,
    primary_reasons: Counter[str],
    invocation_counts: Counter[InvocationStatus],
    scope_evidence_state_counts: Counter[tuple[ScopeState, InvocationStatus, EvidenceState | None]],
    computation_status: ComputationStatus,
    channel_id: str | None = None,
    effective_group_key: GroupKey | None = None,
    rule_ids: tuple[str, ...] | None = None,
    partial_group_observability_counts: Counter[str] | None = None,
) -> CoverageRow:
    if rule_ids is not None:
        resolved_rule_ids = rule_ids
    elif channel_id is not None and policy.definition_for(channel_id) is not None:
        definition = policy.definition_for(channel_id)
        assert definition is not None
        resolved_rule_ids = tuple(sorted({
            definition.scope_rule_id, *definition.not_applicable_rule_ids,
        }))
    else:
        resolved_rule_ids = tuple(sorted({
            rule_id
            for item in policy.channels
            for rule_id in (item.scope_rule_id, *item.not_applicable_rule_ids)
        }))
    return CoverageRow(
        population_id=population_id,
        region=region,
        channel_id=channel_id,
        effective_group_key=effective_group_key,
        scope_policy_id=policy.policy_id,
        rule_ids=resolved_rule_ids,
        counts=counts,
        ratios=CoverageRatios.from_counts(counts),
        computation_status=computation_status,
        primary_reason_counts=dict(primary_reasons),
        invocation_status_counts=dict(invocation_counts),
        scope_evidence_state_counts=tuple(
            ScopeEvidenceStateCount(
                scope=scope,
                invocation=invocation,
                evidence_state=evidence_state,
                count=count,
            )
            for (scope, invocation, evidence_state), count
            in sorted(
                scope_evidence_state_counts.items(),
                key=lambda item: (
                    item[0][0].value,
                    item[0][1].value,
                    item[0][2].value if item[0][2] is not None else "",
                ),
            )
        ),
        partial_group_observability_counts=dict(partial_group_observability_counts or {}),
    )


def _find_channel(values: Sequence[ChannelValue], channel_id: str) -> ChannelValue | None:
    matching = [value for value in values if value.channel_id == channel_id]
    if len(matching) > 1:
        raise ValueError(f"duplicate channel value {channel_id!r} for one pair")
    return matching[0] if matching else None


def _evidence_reason_code(channel: ChannelValue) -> str:
    detail = (channel.detail or "").lower()
    if "mapping" in detail or "unmapped" in detail or "ambiguous" in detail:
        return "MAPPING_UNRESOLVED"
    if any(token in detail for token in ("topology", "hierarchy", "active-path", "active path", "no path")):
        return "CAPABILITY_UNAVAILABLE"
    if any(token in detail for token in ("missing", "unparseable", "no resolvable")):
        return "INPUT_UNAVAILABLE"
    return "EVIDENCE_UNAVAILABLE"

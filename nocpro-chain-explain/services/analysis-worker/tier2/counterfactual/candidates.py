"""Deterministic bounded candidate generation for Counterfactual Review P0."""

from __future__ import annotations

from hashlib import sha256
import json
from math import inf
from typing import Any, Mapping

from audit import StructuralAuditResult

from .config import CounterfactualConfig
from .models import (
    CandidateBatch,
    CounterfactualCandidate,
    EditCost,
    Operation,
    PartitionDelta,
    ReviewIdentity,
)


def _candidate_id(
    identity: ReviewIdentity,
    operation: Operation,
    delta: PartitionDelta,
) -> str:
    payload = json.dumps(
        [identity.cache_tuple(), operation.value, delta.canonical_tuple()],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _role_value(member: Any) -> str | None:
    role = getattr(member, "role", None)
    verdict = getattr(role, "verdict", None)
    return getattr(verdict, "value", verdict) if verdict is not None else None


def _membership_support(member: Any) -> float | None:
    support = getattr(getattr(member, "support", None), "support", None)
    return float(support) if support is not None else None


def _representativeness(member: Any) -> float | None:
    value = getattr(member, "representativeness", None)
    return float(value) if value is not None else None


def _worst_margin(member: Any) -> float | None:
    values = [
        float(margin.margin)
        for margin in getattr(member, "margins", ())
        if getattr(margin, "margin", None) is not None
    ]
    return min(values) if values else None


def generate_remove_candidates(
    identity: ReviewIdentity,
    *,
    chain_id: str,
    members: tuple[str, ...],
    member_analysis: Mapping[str, Any],
    config: CounterfactualConfig,
    eligible_external_contradictions: frozenset[str] = frozenset(),
    additional_member_ids: tuple[str, ...] = (),
) -> CandidateBatch:
    """Generate the approved bounded trigger union for `REMOVE_MEMBER`.

    Ranking is frozen as external contradiction, WEAK role, lower membership,
    lower representativeness, worse margin, then stable alarm ID. Missing
    metrics sort after available metrics and are never treated as zero.
    """
    canonical_members = tuple(sorted(members))
    if len(canonical_members) <= 1:
        return CandidateBatch(
            operation=Operation.REMOVE_MEMBER,
            discovered_count=0,
            evaluated_count=0,
            candidate_limit=config.max_remove_candidates,
            candidates=(),
        )

    triggered: dict[str, tuple[str, ...]] = {}
    ranking: dict[str, tuple[Any, ...]] = {}
    for alarm_id in canonical_members:
        analysis = member_analysis.get(alarm_id)
        external = alarm_id in eligible_external_contradictions
        weak = _role_value(analysis) == "WEAK" if analysis is not None else False
        support = _membership_support(analysis) if analysis is not None else None
        representativeness = (
            _representativeness(analysis) if analysis is not None else None
        )
        margin = _worst_margin(analysis) if analysis is not None else None
        reasons: list[str] = []
        if external:
            reasons.append("ELIGIBLE_EXTERNAL_CONTRADICTION")
        if weak:
            reasons.append("WEAK")
        if support is not None and support < config.membership_support_below:
            reasons.append("LOW_MEMBERSHIP_SUPPORT")
        if (
            representativeness is not None
            and representativeness < config.representativeness_below
        ):
            reasons.append("LOW_REPRESENTATIVENESS")
        if margin is not None and margin < config.adverse_margin_below:
            reasons.append("ADVERSE_MARGIN")
        if alarm_id in additional_member_ids:
            reasons.append("CANONICAL_SINGLETON_CUT")
        if not reasons:
            continue
        triggered[alarm_id] = tuple(reasons)
        ranking[alarm_id] = (
            not external,
            not weak,
            support is None,
            support if support is not None else inf,
            representativeness is None,
            representativeness if representativeness is not None else inf,
            margin is None,
            margin if margin is not None else inf,
            alarm_id,
        )

    ordered = sorted(triggered, key=ranking.__getitem__)
    selected = ordered[: config.max_remove_candidates]
    candidates: list[CounterfactualCandidate] = []
    for alarm_id in selected:
        remaining = tuple(member for member in canonical_members if member != alarm_id)
        delta = PartitionDelta(
            before=((chain_id, canonical_members),),
            after=(
                (chain_id, remaining),
                (f"{chain_id}::singleton::{alarm_id}", (alarm_id,)),
            ),
        )
        candidates.append(
            CounterfactualCandidate(
                candidate_id=_candidate_id(identity, Operation.REMOVE_MEMBER, delta),
                operation=Operation.REMOVE_MEMBER,
                partition_delta=delta,
                edit_cost=EditCost(1, 1, len(canonical_members)),
                source_ref="remove-trigger:" + ",".join(triggered[alarm_id]),
                member_ids=(alarm_id,),
            )
        )
    return CandidateBatch(
        operation=Operation.REMOVE_MEMBER,
        discovered_count=len(ordered),
        evaluated_count=len(candidates),
        candidate_limit=config.max_remove_candidates,
        candidates=tuple(candidates),
    )


def generate_split_candidates(
    identity: ReviewIdentity,
    *,
    chain_id: str,
    members: tuple[str, ...],
    structural_audit: StructuralAuditResult | None,
    config: CounterfactualConfig,
) -> CandidateBatch:
    """Reuse exact Audit cuts; never run a second partition search."""
    canonical_members = tuple(sorted(members))
    all_members = frozenset(canonical_members)
    if len(canonical_members) < 4 or structural_audit is None:
        return CandidateBatch(
            operation=Operation.SPLIT_CHAIN,
            discovered_count=0,
            evaluated_count=0,
            candidate_limit=config.max_split_candidates,
            candidates=(),
        )

    nontrivial: dict[
        tuple[tuple[str, ...], tuple[str, ...]], tuple[float, str]
    ] = {}
    canonical_remove: set[str] = set()
    for scored in structural_audit.scored_candidates:
        left_set = frozenset(scored.candidate.members).intersection(all_members)
        right_set = all_members - left_set
        if not left_set or not right_set:
            continue
        if min(len(left_set), len(right_set)) == 1:
            singleton = left_set if len(left_set) == 1 else right_set
            canonical_remove.update(singleton)
            continue
        result = scored.conductance
        if not result.feasible or result.phi is None:
            continue
        left = tuple(sorted(left_set))
        right = tuple(sorted(right_set))
        sides = (left, right) if left <= right else (right, left)
        previous = nontrivial.get(sides)
        value = (float(result.phi), scored.candidate.label)
        if previous is None or value < previous:
            nontrivial[sides] = value

    ordered = sorted(
        nontrivial.items(),
        key=lambda item: (item[1][0], item[1][1], item[0]),
    )
    selected = ordered[: config.max_split_candidates]
    candidates: list[CounterfactualCandidate] = []
    for (left, right), (phi, label) in selected:
        delta = PartitionDelta(
            before=((chain_id, canonical_members),),
            after=(
                (f"{chain_id}::split::0", left),
                (f"{chain_id}::split::1", right),
            ),
        )
        candidates.append(
            CounterfactualCandidate(
                candidate_id=_candidate_id(identity, Operation.SPLIT_CHAIN, delta),
                operation=Operation.SPLIT_CHAIN,
                partition_delta=delta,
                edit_cost=EditCost(1, min(len(left), len(right)), len(canonical_members)),
                source_ref=f"audit-cut:{label}:phi={phi:.12g}",
                member_ids=min(left, right),
            )
        )
    return CandidateBatch(
        operation=Operation.SPLIT_CHAIN,
        discovered_count=len(ordered),
        evaluated_count=len(candidates),
        candidate_limit=config.max_split_candidates,
        candidates=tuple(candidates),
        canonical_remove_member_ids=tuple(sorted(canonical_remove)),
    )


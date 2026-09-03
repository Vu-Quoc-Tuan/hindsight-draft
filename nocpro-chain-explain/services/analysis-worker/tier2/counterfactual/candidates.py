"""Deterministic bounded candidate generation for Counterfactual Review P0."""

from __future__ import annotations

from hashlib import sha256
import json
from math import inf
from typing import Any, Mapping

from audit import StructuralAuditResult
from channels import exact_cross_chain_evidence

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


def generate_move_candidates(
    identity: ReviewIdentity,
    *,
    source_chain_id: str,
    source_members: tuple[str, ...],
    member_analysis: Mapping[str, Any],
    local_candidates: tuple[Any, ...],
    package,
    config: CounterfactualConfig,
) -> CandidateBatch:
    """Generate bounded canonical transfers to Tier-1B local candidates.

    The destination pool is consumed verbatim from the source Tier-1B artifact.
    A missing Margin_common is neither zero nor a veto: it simply contributes
    no margin trigger and ranks after computable target-favoured margins.
    """
    limit = config.max_move_candidates
    if limit is None:
        return CandidateBatch(Operation.MOVE_MEMBER, 0, 0, 0, ())

    source = tuple(sorted(source_members))
    triggered: list[tuple[tuple[Any, ...], CounterfactualCandidate]] = []
    for destination in local_candidates:
        target_chain_id = destination.chain_id
        if target_chain_id == source_chain_id or target_chain_id not in package.chains:
            continue
        target = tuple(sorted(package.members_of(target_chain_id)))
        if not target:
            continue
        # MOVE v1 is source-local. For two singleton chains it may surface only
        # the globally canonical direction (stable-greater chain ->
        # stable-less chain); it never loads the peer's Tier-1B artifact to
        # recover that proposal when the less chain is under review. A
        # singleton/non-singleton pair is likewise canonical only from the
        # singleton into the existing non-singleton chain.
        if len(source) == 1 and len(target) == 1:
            if source_chain_id < target_chain_id:
                continue
        elif len(source) > 1 and len(target) == 1:
            continue
        for alarm_id in source:
            analysis = member_analysis.get(alarm_id)
            role = _role_value(analysis) if analysis is not None else None
            support = _membership_support(analysis) if analysis is not None else None
            representation = (
                _representativeness(analysis) if analysis is not None else None
            )
            margin_value = None
            if analysis is not None:
                for margin in getattr(analysis, "margins", ()):
                    if getattr(margin, "compared_chain_id", None) == target_chain_id:
                        margin_value = getattr(margin, "margin", None)
                        break
            reasons: list[str] = []
            if role == "WEAK":
                reasons.append("WEAK")
            if support is not None and support < config.membership_support_below:
                reasons.append("LOW_MEMBERSHIP_SUPPORT")
            if (
                representation is not None
                and representation < config.representativeness_below
            ):
                reasons.append("LOW_REPRESENTATIVENESS")
            if margin_value is not None and float(margin_value) < 0:
                reasons.append("TARGET_FAVORED_MARGIN")
            if not reasons:
                continue

            remaining = tuple(member for member in source if member != alarm_id)
            after = [(target_chain_id, tuple(sorted((*target, alarm_id))))]
            if remaining:
                after.append((source_chain_id, remaining))
            delta = PartitionDelta(
                before=((source_chain_id, source), (target_chain_id, target)),
                after=tuple(after),
            )
            candidate = CounterfactualCandidate(
                candidate_id=_candidate_id(identity, Operation.MOVE_MEMBER, delta),
                operation=Operation.MOVE_MEMBER,
                partition_delta=delta,
                edit_cost=EditCost(1, 1, len(source) + len(target)),
                source_ref="move-trigger:" + ",".join(reasons),
                member_ids=(alarm_id,),
                source_chain_id=source_chain_id,
                target_chain_id=target_chain_id,
            )
            if margin_value is not None and float(margin_value) < 0:
                margin_state = 0
            elif margin_value is None:
                margin_state = 1
            else:
                margin_state = 2
            triggered.append(
                (
                    (
                        margin_state,
                        float(margin_value) if margin_value is not None else inf,
                        -int(destination.overlap),
                        role != "WEAK",
                        support is None,
                        support if support is not None else inf,
                        representation is None,
                        representation if representation is not None else inf,
                        alarm_id,
                        target_chain_id,
                    ),
                    candidate,
                )
            )
    ordered = sorted(triggered, key=lambda item: item[0])
    selected = tuple(item[1] for item in ordered[:limit])
    return CandidateBatch(
        operation=Operation.MOVE_MEMBER,
        discovered_count=len(ordered),
        evaluated_count=len(selected),
        candidate_limit=limit,
        candidates=selected,
    )


def generate_merge_candidates(
    identity: ReviewIdentity,
    *,
    review_chain_id: str,
    local_candidates: tuple[Any, ...],
    package,
    config: CounterfactualConfig,
) -> CandidateBatch:
    """Generate bounded unordered MERGE candidates from local retrieval only.

    ``local_candidates`` is a retrieval artifact, not merge evidence.  A pair
    only enters the batch after the exact cross-chain primitive finds at least
    one canonical audit edge.  Singleton pairs are intentionally filtered: the
    canonical operation for them remains MOVE_MEMBER.
    """
    limit = config.max_merge_candidates
    if limit is None:
        return CandidateBatch(Operation.MERGE_CHAINS, 0, 0, 0, ())

    discovered: list[tuple[tuple[Any, ...], CounterfactualCandidate]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for destination in local_candidates:
        candidate_chain_id = getattr(destination, "chain_id", None)
        if (
            not isinstance(candidate_chain_id, str)
            or candidate_chain_id == review_chain_id
            or candidate_chain_id not in package.chains
        ):
            continue
        left_chain_id, right_chain_id = sorted((review_chain_id, candidate_chain_id))
        pair = (left_chain_id, right_chain_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        left = tuple(sorted(package.members_of(left_chain_id)))
        right = tuple(sorted(package.members_of(right_chain_id)))
        if not left or not right or min(len(left), len(right)) == 1:
            continue
        merged_members = tuple(sorted((*left, *right)))
        if len(merged_members) > config.max_chain_members:
            continue

        evidence = exact_cross_chain_evidence(package, left_chain_id, right_chain_id)
        if evidence.cross_audit_edge_count < 1:
            continue
        merged_chain_id = f"CF-MERGE-{_candidate_id_for_merge(identity, pair)}"
        delta = PartitionDelta(
            before=((left_chain_id, left), (right_chain_id, right)),
            after=((merged_chain_id, merged_members),),
        )
        candidate = CounterfactualCandidate(
            candidate_id=_candidate_id(identity, Operation.MERGE_CHAINS, delta),
            operation=Operation.MERGE_CHAINS,
            partition_delta=delta,
            # Merge is a block-level edit.  New counterfactual chain identity
            # never turns its member rows into member-level reassignments.
            edit_cost=EditCost(1, 0, len(merged_members)),
            source_ref=(
                "cross-audit:"
                f"edges={evidence.cross_audit_edge_count};"
                f"coverage={evidence.cross_audit_edge_coverage:.12g}"
            ),
            member_ids=(),
            merged_chain_ids=pair,
            merge_evidence=evidence,
        )
        discovered.append(
            (
                (
                    -evidence.cross_audit_edge_coverage,
                    -evidence.cross_supported_group_count,
                    -evidence.cross_evidence_union_coverage,
                    -int(getattr(destination, "overlap", 0)),
                    left_chain_id,
                    right_chain_id,
                ),
                candidate,
            )
        )
    ordered = sorted(discovered, key=lambda item: item[0])
    selected = tuple(item[1] for item in ordered[:limit])
    return CandidateBatch(
        operation=Operation.MERGE_CHAINS,
        discovered_count=len(ordered),
        evaluated_count=len(selected),
        candidate_limit=limit,
        candidates=selected,
    )


def _candidate_id_for_merge(
    identity: ReviewIdentity, pair: tuple[str, str]
) -> str:
    """Stable synthetic after-chain suffix without choosing a surviving source."""
    payload = json.dumps(
        [identity.cache_tuple(), Operation.MERGE_CHAINS.value, pair],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


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
                # SPLIT is a structural block edit, just like MERGE. Both
                # after-block identities are counterfactual representations;
                # neither side is an individual member-level reassignment.
                edit_cost=EditCost(1, 0, len(canonical_members)),
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

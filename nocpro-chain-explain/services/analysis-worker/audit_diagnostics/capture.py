"""Exact capture of the canonical Tier-2 Audit inputs for one frozen chain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from audit import (
    AUDIT_EXACT_MAX_MEMBERS,
    AuditGraph,
    build_audit_graph,
    generate_candidates,
)
from audit_diagnostics.comparison import (
    CandidateSetError,
    freeze_candidates,
    production_baseline_winner,
    score_frozen_candidates,
)
from audit_diagnostics.contracts import (
    CandidateScore,
    FrozenCandidate,
    GroupKey,
    ResourceLimits,
)
from audit_diagnostics.registry import ResolvedChannelRegistry, resolve_execution_registry
from audit_diagnostics.scope import ScopePolicy
from channels import EMPTY_TAXONOMY, evaluate_chain_channels, failure_domains_for_chain
from configuration import AnalysisConfig
from descriptor import DescriptorKind, bitmap_of_members, build_predicate_index, mine_descriptors
from groups.statistics import pair_iterator
from libs.contracts import IngestedPackage
from libs.provenance import build_derivation_groups, normalize_pair_channels


class DiagnosticInputError(ValueError):
    """Frozen package does not support a complete exact diagnostic run."""


class DiagnosticLimitError(ValueError):
    """Declared technical limit prevents exact computation."""


@dataclass(frozen=True)
class ExactAuditInputs:
    chain_id: str
    members: tuple[str, ...]
    pair_channel_values: Mapping[tuple[str, str], tuple]
    graph: AuditGraph
    candidates: tuple[FrozenCandidate, ...]
    baseline_scores: tuple[CandidateScore, ...]
    production_baseline_winner_id: str | None
    production_baseline_verdict: str
    channel_registry: ResolvedChannelRegistry
    candidate_set_digest: str
    pair_count: int
    chain_member_order: tuple[str, ...]


def capture_exact_audit_inputs(
    package: IngestedPackage,
    chain_id: str,
    *,
    analysis_config: AnalysisConfig,
    scope_policy: ScopePolicy,
    limits: ResourceLimits,
    epsilon_phi: float,
) -> ExactAuditInputs:
    """Evaluate exactly the same channels/graph/candidates used by Tier-2 Audit.

    This narrow path mirrors ``analyze_structural_audit``'s descriptor and
    candidate preparation but does not invoke its unrelated topology, history,
    visualisation, or explanation components.
    """
    chain = package.chains.get(chain_id)
    if chain is None:
        raise DiagnosticInputError(f"unknown chain_id {chain_id!r}")
    if not package.snapshot.is_complete:
        raise DiagnosticInputError("diagnostic requires a COMPLETE canonical snapshot")
    member_order = tuple(package.members_of(chain_id))
    if len(member_order) != chain.member_count:
        raise DiagnosticInputError(
            f"chain member_count={chain.member_count} differs from membership rows={len(member_order)}"
        )
    if not member_order or len(set(member_order)) != len(member_order):
        raise DiagnosticInputError("chain membership must be non-empty and contain unique alarm IDs")
    missing_alarms = [member for member in member_order if member not in package.alarms]
    if missing_alarms:
        raise DiagnosticInputError(f"chain references missing alarm IDs: {missing_alarms[:5]}")
    canonical_exact_max = min(
        AUDIT_EXACT_MAX_MEMBERS,
        int(analysis_config.value("audit.exact_max_members")),
    )
    max_members = min(limits.max_members, canonical_exact_max)
    if len(member_order) > max_members:
        raise DiagnosticLimitError(
            f"chain has {len(member_order)} members, exceeding exact diagnostic cap {max_members}"
        )
    pair_count = len(member_order) * (len(member_order) - 1) // 2
    if pair_count > limits.max_pairs:
        raise DiagnosticLimitError(
            f"chain has {pair_count} unordered pairs, exceeding max_pairs={limits.max_pairs}"
        )

    registry = resolve_execution_registry(package, scope_policy)
    if not registry.complete:
        raise DiagnosticInputError(
            "scope/execution registry could not be fully resolved: " + ", ".join(registry.issues)
        )
    audit_eligible_groups = tuple(
        group for group in registry.group_channels if group.audit_eligible
    )
    if 1 + len(audit_eligible_groups) > limits.max_variants:
        raise DiagnosticLimitError(
            f"baseline plus {len(audit_eligible_groups)} LOGO variants exceeds "
            f"max_variants={limits.max_variants}; declare a group subset before prepare"
        )

    evidence = evaluate_chain_channels(
        package,
        chain_id,
        taxonomy=EMPTY_TAXONOMY,
        delay_threshold=float(analysis_config.value("temporal.delay.support_threshold")),
        d_max=int(analysis_config.value("dependency.max_hop")),
        silent_gap_seconds=int(analysis_config.value("temporal.burst.gap_seconds")),
        pair_detail_limit=pair_count,
    )
    if not evidence.statistics_exact or evidence.statistics.pairs_counted != pair_count:
        raise DiagnosticInputError("canonical exact chain evaluator did not count the complete pair universe")
    if evidence.detail_truncated or evidence.detail_pairs != pair_count or len(evidence.matrix) != pair_count:
        raise DiagnosticInputError("canonical pair matrix is truncated; exact diagnostic refused")
    # PairChannelMatrix stores unordered pairs in sorted-key form, while the
    # exact evaluator visits pairs in chain membership order. Compare the same
    # unordered identity on both sides rather than treating that order as data.
    expected_pairs = {
        tuple(sorted(pair)) for pair in pair_iterator(list(evidence.members))
    }
    actual_pairs = {tuple(sorted(pair)) for pair in evidence.matrix.values}
    if actual_pairs != expected_pairs:
        raise DiagnosticInputError("canonical pair matrix does not match the unordered member universe")

    actual_channel_sets = {
        tuple(sorted(value.channel_id for value in values))
        for values in evidence.matrix.values.values()
    }
    if len(actual_channel_sets) > 1:
        raise DiagnosticInputError("channel invocation registry differs between pairs")
    actual_channel_ids = next(iter(actual_channel_sets), tuple())
    if pair_count and set(actual_channel_ids) != set(registry.channel_ids):
        raise DiagnosticInputError(
            "pre-resolved execution registry differs from exact evaluator output: "
            f"missing={sorted(set(registry.channel_ids) - set(actual_channel_ids))}, "
            f"unexpected={sorted(set(actual_channel_ids) - set(registry.channel_ids))}"
        )
    if pair_count:
        for pair_key, pair_values in evidence.matrix.values.items():
            for group in build_derivation_groups(normalize_pair_channels(pair_values)):
                actual_group = GroupKey.from_effective_key(group.key)
                for channel in group.channels:
                    if registry.channel_groups.get(channel.channel_id) != actual_group:
                        raise DiagnosticInputError(
                            "pre-resolved full effective group key differs from exact evaluator output "
                            f"for {channel.channel_id!r} on pair {pair_key!r}"
                        )

    graph = build_audit_graph(evidence.members, evidence.matrix.values)
    predicate_index = build_predicate_index(list(package.alarms.values()))
    target = bitmap_of_members(predicate_index, set(member_order))
    descriptors = tuple(
        mine_descriptors(
            predicate_index,
            target,
            config=analysis_config.mining_config(),
            kind=DescriptorKind.IDENTITY,
        )
    )
    # Match Tier-2's current candidate inputs exactly: explicit empty dependency
    # pair edges, package failure-domain hyperedges, and canonical descriptors.
    domains = [
        (domain.failure_domain_id, domain.member_alarm_ids)
        for domain in failure_domains_for_chain(package, chain_id)
        if domain.eligible_for_candidate
    ]
    base_candidates = generate_candidates(
        alarms=package.alarms_of(chain_id),
        dependency_edges=[],
        failure_domains=domains,
        descriptors=descriptors,
        predicate_index=predicate_index,
        include_derived=False,
    )
    # Bound the pairwise-derived search before the O(base_candidates^2) step.
    freeze_candidates(base_candidates, member_order, max_candidates=limits.max_candidates)
    raw_candidates = generate_candidates(
        alarms=package.alarms_of(chain_id),
        dependency_edges=[],
        failure_domains=domains,
        descriptors=descriptors,
        predicate_index=predicate_index,
    )
    frozen_candidates = freeze_candidates(
        raw_candidates,
        member_order,
        max_candidates=limits.max_candidates,
    )
    epsilon_phi = float(epsilon_phi)
    rho = float(analysis_config.value("audit.rho"))
    min_side_size = int(analysis_config.value("audit.min_side_size"))
    small_chain_threshold = int(analysis_config.value("audit.small_chain_threshold"))
    winner_id, verdict = production_baseline_winner(
        chain_id,
        graph,
        frozen_candidates,
        epsilon_phi=epsilon_phi,
        rho=rho,
        min_side_size=min_side_size,
        small_chain_threshold=small_chain_threshold,
    )
    baseline_scores = score_frozen_candidates(
        graph,
        frozen_candidates,
        rho=rho,
        min_side_size=min_side_size,
        small_chain_threshold=small_chain_threshold,
    )
    candidate_digest = _digest(
        [candidate.model_dump(mode="json") for candidate in frozen_candidates]
    )
    return ExactAuditInputs(
        chain_id=chain_id,
        members=tuple(evidence.members),
        pair_channel_values={
            pair: tuple(values) for pair, values in evidence.matrix.values.items()
        },
        graph=graph,
        candidates=frozen_candidates,
        baseline_scores=baseline_scores,
        production_baseline_winner_id=winner_id,
        production_baseline_verdict=verdict,
        channel_registry=registry,
        candidate_set_digest=candidate_digest,
        pair_count=pair_count,
        chain_member_order=member_order,
    )


def candidate_generation_config_digest(analysis_config: AnalysisConfig) -> str:
    return _digest(
        {
            "generator": "audit.candidates.generate_candidates",
            "theta_dep": 0.5,
            "include_derived": True,
            "dependency_edges": "empty_default_used_by_tier2",
            "failure_domains": "failure_domains_for_chain(package, chain_id)",
            "descriptor": {
                "config_version": analysis_config.mining_config().config_version,
                "max_depth": analysis_config.mining_config().max_depth,
                "beam_width": analysis_config.mining_config().beam_width,
                "top_k": analysis_config.mining_config().top_k,
                "candidate_descriptor_top_k": 5,
                "precision_global_min": analysis_config.mining_config().precision_global_min,
                "precision_local_min": analysis_config.mining_config().precision_local_min,
                "redundancy_jaccard": analysis_config.mining_config().redundancy_jaccard,
            },
        }
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()

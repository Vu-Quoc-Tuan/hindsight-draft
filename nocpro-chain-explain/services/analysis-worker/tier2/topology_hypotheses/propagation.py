"""Deterministic configured RWR over an admissible direct alarm DAG."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, fsum, isfinite
from types import MappingProxyType
from typing import Mapping

from configuration import ConfiguredValue, PropagationConfig
from libs.contracts import IngestedPackage
from topology_source import has_missing_topology_source

from .dominator import _eligible_directed_edges, build_directed_universes
from .models import (
    DirectedUniverse,
    HypothesisStatus,
    PropagationEdgeHypothesis,
    PropagationNodeScore,
    PropagationResult,
    TopologyHypothesisReason,
)
from libs.contracts.topology_mapping import resolve_resource_ids


SEED_POLICY = "ALL_SOURCE_NODES_UNIFORM"
DANGLING_POLICY = "REDISTRIBUTE_TO_RESTART"


@dataclass(frozen=True)
class _NumericConfig:
    config_version: str
    restart_probability: float
    convergence_tolerance: float
    max_iterations: int
    decay_parameter: float
    score_threshold: float
    max_candidate_edges: int
    parameter_provenance: Mapping[str, str]


@dataclass(frozen=True)
class _RwrOutcome:
    reason: TopologyHypothesisReason | None
    iterations: int
    final_l1_distance: float | None
    scores: Mapping[str, float] | None
    transitions: Mapping[tuple[str, str], float]


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        normalized = float(value)
    except (OverflowError, ValueError):
        return None
    return normalized if isfinite(normalized) else None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _configured_values(config: PropagationConfig | None) -> _NumericConfig | None:
    """Validate the complete low-level contract without supplying any default."""
    if config is None or not isinstance(config.config_version, str):
        return None
    config_version = config.config_version.strip()
    if not config_version or config.decay_type != "exponential":
        return None

    configured = (
        config.restart_probability,
        config.convergence_tolerance,
        config.max_iterations,
        config.decay_parameter,
        config.score_threshold,
        config.max_candidate_edges,
    )
    if any(not isinstance(value, ConfiguredValue) for value in configured):
        return None
    if any(not isinstance(value.path, str) or not value.path for value in configured):
        return None
    if len({value.path for value in configured}) != len(configured):
        return None

    alpha = _finite_float(config.restart_probability.value)
    tolerance = _finite_float(config.convergence_tolerance.value)
    max_iterations = _positive_int(config.max_iterations.value)
    decay_parameter = _finite_float(config.decay_parameter.value)
    threshold = _finite_float(config.score_threshold.value)
    max_candidate_edges = _positive_int(config.max_candidate_edges.value)
    if (
        alpha is None
        or not 0.0 < alpha < 1.0
        or tolerance is None
        or tolerance <= 0.0
        or max_iterations is None
        or decay_parameter is None
        or decay_parameter <= 0.0
        or threshold is None
        or not 0.0 <= threshold <= 1.0
        or max_candidate_edges is None
    ):
        return None

    try:
        provenance = {
            value.path: value.source.value
            for value in configured
        }
    except AttributeError:
        return None
    return _NumericConfig(
        config_version=config_version,
        restart_probability=alpha,
        convergence_tolerance=tolerance,
        max_iterations=max_iterations,
        decay_parameter=decay_parameter,
        score_threshold=threshold,
        max_candidate_edges=max_candidate_edges,
        parameter_provenance=MappingProxyType(dict(sorted(provenance.items()))),
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an explicitly timezone-qualified canonical timestamp as UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _is_dag(nodes: tuple[str, ...], edges: tuple[tuple[str, str], ...]) -> bool:
    """Validate acyclicity with deterministic Kahn traversal."""
    node_set = set(nodes)
    if not nodes or len(node_set) != len(nodes):
        return False
    successors: dict[str, list[str]] = {node: [] for node in nodes}
    indegree = {node: 0 for node in nodes}
    seen_edges: set[tuple[str, str]] = set()
    for source, target in edges:
        if source not in node_set or target not in node_set:
            return False
        if (source, target) in seen_edges:
            continue
        seen_edges.add((source, target))
        successors[source].append(target)
        indegree[target] += 1

    frontier = sorted(node for node in nodes if indegree[node] == 0)
    visited = 0
    while frontier:
        node = frontier.pop(0)
        visited += 1
        for successor in sorted(successors[node]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                frontier.append(successor)
                frontier.sort()
    return visited == len(nodes)


def _run_configured_rwr(
    nodes: tuple[str, ...],
    edge_deltas: tuple[tuple[str, str, float], ...],
    config: PropagationConfig,
) -> _RwrOutcome:
    """Run configured RWR, returning no scores unless convergence is proven."""
    numeric = _configured_values(config)
    if numeric is None:
        return _RwrOutcome(
            reason=TopologyHypothesisReason.PROPAGATION_CONFIG_INCOMPLETE,
            iterations=0,
            final_l1_distance=None,
            scores=None,
            transitions=MappingProxyType({}),
        )

    nodes = tuple(sorted(nodes))
    edge_delta_by_pair: dict[tuple[str, str], float] = {}
    for source, target, raw_delta in edge_deltas:
        delta = _finite_float(raw_delta)
        if delta is None or delta <= 0.0:
            return _RwrOutcome(
                reason=TopologyHypothesisReason.INVALID_DAG,
                iterations=0,
                final_l1_distance=None,
                scores=None,
                transitions=MappingProxyType({}),
            )
        pair = (source, target)
        if pair in edge_delta_by_pair and edge_delta_by_pair[pair] != delta:
            return _RwrOutcome(
                reason=TopologyHypothesisReason.INVALID_DAG,
                iterations=0,
                final_l1_distance=None,
                scores=None,
                transitions=MappingProxyType({}),
            )
        edge_delta_by_pair[pair] = delta
    pairs = tuple(sorted(edge_delta_by_pair))
    if not _is_dag(nodes, pairs):
        return _RwrOutcome(
            reason=TopologyHypothesisReason.INVALID_DAG,
            iterations=0,
            final_l1_distance=None,
            scores=None,
            transitions=MappingProxyType({}),
        )

    outgoing_deltas: dict[str, list[tuple[str, float]]] = {node: [] for node in nodes}
    indegree = {node: 0 for node in nodes}
    for source, target in pairs:
        outgoing_deltas[source].append((target, edge_delta_by_pair[(source, target)]))
        indegree[target] += 1
    sources = tuple(node for node in nodes if indegree[node] == 0)
    if not sources:
        return _RwrOutcome(
            reason=TopologyHypothesisReason.INVALID_DAG,
            iterations=0,
            final_l1_distance=None,
            scores=None,
            transitions=MappingProxyType({}),
        )

    transitions: dict[tuple[str, str], float] = {}
    for source in nodes:
        outgoing = sorted(outgoing_deltas[source])
        if not outgoing:
            continue
        # Subtracting the smallest exponent preserves the exact normalized
        # exponential ratios while avoiding an all-zero underflow denominator.
        minimum_delta = min(delta for _, delta in outgoing)
        weights = [
            (target, exp(-(delta - minimum_delta) / numeric.decay_parameter))
            for target, delta in outgoing
        ]
        denominator = fsum(weight for _, weight in weights)
        if not isfinite(denominator) or denominator <= 0.0:
            return _RwrOutcome(
                reason=TopologyHypothesisReason.RWR_NOT_CONVERGED,
                iterations=0,
                final_l1_distance=None,
                scores=None,
                transitions=MappingProxyType({}),
            )
        for target, weight in weights:
            transitions[(source, target)] = weight / denominator

    restart_mass = 1.0 / len(sources)
    restart = {
        node: restart_mass if node in sources else 0.0
        for node in nodes
    }
    pi = dict(restart)
    one_minus_alpha = 1.0 - numeric.restart_probability
    final_l1: float | None = None
    for iteration in range(1, numeric.max_iterations + 1):
        next_pi = {
            node: numeric.restart_probability * restart[node]
            for node in nodes
        }
        dangling_mass = 0.0
        for source in nodes:
            outgoing = sorted(outgoing_deltas[source])
            if not outgoing:
                dangling_mass += pi[source]
                continue
            for target, _ in outgoing:
                next_pi[target] += (
                    one_minus_alpha
                    * pi[source]
                    * transitions[(source, target)]
                )
        redistributed = one_minus_alpha * dangling_mass
        if redistributed:
            for node in nodes:
                next_pi[node] += redistributed * restart[node]

        final_l1 = fsum(abs(next_pi[node] - pi[node]) for node in nodes)
        pi = next_pi
        if final_l1 <= numeric.convergence_tolerance:
            return _RwrOutcome(
                reason=None,
                iterations=iteration,
                final_l1_distance=final_l1,
                scores=MappingProxyType(dict(pi)),
                transitions=MappingProxyType(dict(sorted(transitions.items()))),
            )

    return _RwrOutcome(
        reason=TopologyHypothesisReason.RWR_NOT_CONVERGED,
        iterations=numeric.max_iterations,
        final_l1_distance=final_l1,
        scores=None,
        transitions=MappingProxyType(dict(sorted(transitions.items()))),
    )


def _candidate_edges(
    alarm_ids: tuple[str, ...],
    resources: Mapping[str, str],
    times: Mapping[str, datetime],
    universe: DirectedUniverse,
) -> tuple[tuple[str, str, float], ...]:
    """Construct only direct topology edges with strict temporal precedence."""
    candidates: list[tuple[str, str, float]] = []
    for source_alarm_id in alarm_ids:
        source_resource_id = resources[source_alarm_id]
        direct_targets = universe.successors[source_resource_id]
        for target_alarm_id in alarm_ids:
            if resources[target_alarm_id] not in direct_targets:
                continue
            delta = (times[target_alarm_id] - times[source_alarm_id]).total_seconds()
            if delta > 0.0:
                candidates.append((source_alarm_id, target_alarm_id, delta))
    return tuple(sorted(candidates))


def _empty_result(
    reason: TopologyHypothesisReason,
    *,
    numeric: _NumericConfig | None,
    universe: DirectedUniverse | None = None,
    candidate_node_count: int = 0,
    candidate_edge_count: int = 0,
    iterations: int = 0,
    final_l1_distance: float | None = None,
) -> PropagationResult:
    return PropagationResult(
        status=HypothesisStatus.UNAVAILABLE,
        reason=reason,
        semantic=None,
        source_ref=universe.source_ref if universe else None,
        relation_type=universe.relation_type if universe else None,
        provenance_class=universe.provenance_class if universe else None,
        provenance_subtype=universe.provenance_subtype if universe else None,
        source_kind=universe.source_kind if universe else None,
        config_version=numeric.config_version if numeric else None,
        parameter_provenance=(numeric.parameter_provenance if numeric else {}),
        candidate_node_count=candidate_node_count,
        candidate_edge_count=candidate_edge_count,
        iterations=iterations,
        final_l1_distance=final_l1_distance,
        convergence_tolerance=(numeric.convergence_tolerance if numeric else None),
        restart_probability=(numeric.restart_probability if numeric else None),
        seed_policy=SEED_POLICY if numeric else None,
        dangling_policy=DANGLING_POLICY if numeric else None,
        node_scores=(),
        hypotheses=(),
        source_id=universe.source_id if universe else None,
        source_version=universe.source_version if universe else None,
        scenario_id=universe.scenario_id if universe else None,
        generator_version=universe.generator_version if universe else None,
    )


def analyze_propagation(
    package: IngestedPackage,
    chain_id: str,
    config: PropagationConfig | None,
) -> PropagationResult:
    """Rank one chain's admissible alarm DAG or fail closed with diagnostics."""
    numeric = _configured_values(config)
    if numeric is None:
        return _empty_result(
            TopologyHypothesisReason.PROPAGATION_CONFIG_INCOMPLETE,
            numeric=None,
        )

    eligible_edges = _eligible_directed_edges(package)
    if eligible_edges and has_missing_topology_source(eligible_edges):
        return _empty_result(
            TopologyHypothesisReason.TOPOLOGY_SOURCE_VERSION_MISSING,
            numeric=numeric,
        )

    alarm_ids = tuple(sorted(set(package.members_of(chain_id))))
    if not alarm_ids:
        return _empty_result(
            TopologyHypothesisReason.RESOURCE_MAPPING_UNAVAILABLE,
            numeric=numeric,
        )

    mappings = resolve_resource_ids(package.topology.get("mappings") or (), alarm_ids, require_all=True)
    if mappings is None:
        return _empty_result(
            TopologyHypothesisReason.RESOURCE_MAPPING_UNAVAILABLE,
            numeric=numeric,
            candidate_node_count=len(alarm_ids),
        )
    mapped_resources = mappings

    times: dict[str, datetime] = {}
    for alarm_id in alarm_ids:
        alarm = package.alarms.get(alarm_id)
        parsed = _parse_timestamp(alarm.canonical_start_time if alarm else None)
        if parsed is None:
            return _empty_result(
                TopologyHypothesisReason.TEMPORAL_ORDERING_UNAVAILABLE,
                numeric=numeric,
                candidate_node_count=len(alarm_ids),
            )
        times[alarm_id] = parsed

    universes = build_directed_universes(package)
    required_resources = set(mapped_resources.values())
    covering_universes = tuple(
        universe
        for universe in universes
        if required_resources <= set(universe.nodes)
    )
    # A single result must never splice edges or provenance across independent
    # source/version/relation universes, and no lexical source preference exists.
    if len(covering_universes) != 1:
        return _empty_result(
            TopologyHypothesisReason.DIRECTED_TOPOLOGY_UNAVAILABLE,
            numeric=numeric,
            candidate_node_count=len(alarm_ids),
        )
    universe = covering_universes[0]

    candidates = _candidate_edges(
        alarm_ids,
        mapped_resources,
        times,
        universe,
    )
    candidate_count = len(candidates)
    if candidate_count > numeric.max_candidate_edges:
        return _empty_result(
            TopologyHypothesisReason.CANDIDATE_LIMIT_EXCEEDED,
            numeric=numeric,
            universe=universe,
            candidate_node_count=len(alarm_ids),
            candidate_edge_count=candidate_count,
        )

    assert config is not None  # Established by _configured_values above.
    outcome = _run_configured_rwr(alarm_ids, candidates, config)
    if outcome.reason is not None or outcome.scores is None:
        return _empty_result(
            outcome.reason or TopologyHypothesisReason.RWR_NOT_CONVERGED,
            numeric=numeric,
            universe=universe,
            candidate_node_count=len(alarm_ids),
            candidate_edge_count=candidate_count,
            iterations=outcome.iterations,
            final_l1_distance=outcome.final_l1_distance,
        )

    node_scores = tuple(
        PropagationNodeScore(alarm_id=alarm_id, score=outcome.scores[alarm_id])
        for alarm_id in alarm_ids
    )
    deltas = {(source, target): delta for source, target, delta in candidates}
    hypotheses: list[PropagationEdgeHypothesis] = []
    for source, target in sorted(outcome.transitions):
        transition = outcome.transitions[(source, target)]
        flow = (
            (1.0 - numeric.restart_probability)
            * outcome.scores[source]
            * transition
        )
        if flow >= numeric.score_threshold:
            hypotheses.append(
                PropagationEdgeHypothesis(
                    source_alarm_id=source,
                    target_alarm_id=target,
                    score=flow,
                    transition_probability=transition,
                    temporal_delta_seconds=deltas[(source, target)],
                )
            )

    return PropagationResult(
        status=HypothesisStatus.AVAILABLE,
        reason=None,
        semantic="PROPAGATION_HYPOTHESIS",
        source_ref=universe.source_ref,
        relation_type=universe.relation_type,
        provenance_class=universe.provenance_class,
        provenance_subtype=universe.provenance_subtype,
        source_kind=universe.source_kind,
        config_version=numeric.config_version,
        parameter_provenance=numeric.parameter_provenance,
        candidate_node_count=len(alarm_ids),
        candidate_edge_count=candidate_count,
        iterations=outcome.iterations,
        final_l1_distance=outcome.final_l1_distance,
        convergence_tolerance=numeric.convergence_tolerance,
        restart_probability=numeric.restart_probability,
        seed_policy=SEED_POLICY,
        dangling_policy=DANGLING_POLICY,
        node_scores=node_scores,
        hypotheses=tuple(hypotheses),
        source_id=universe.source_id,
        source_version=universe.source_version,
        scenario_id=universe.scenario_id,
        generator_version=universe.generator_version,
    )

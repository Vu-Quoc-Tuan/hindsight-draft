"""Immutable public contracts for fail-closed P2 topology hypotheses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from libs.provenance import ProvenanceClass, ProvenanceSubtype


class HypothesisStatus(str, Enum):
    """A topology capability is either available or explicitly unavailable."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class TopologyHypothesisReason(str, Enum):
    """Stable fail-closed reasons shared by the independent P2 capabilities."""

    DIRECTED_TOPOLOGY_UNAVAILABLE = "DIRECTED_TOPOLOGY_UNAVAILABLE"
    RESOURCE_MAPPING_UNAVAILABLE = "RESOURCE_MAPPING_UNAVAILABLE"
    TEMPORAL_ORDERING_UNAVAILABLE = "TEMPORAL_ORDERING_UNAVAILABLE"
    PROPAGATION_CONFIG_INCOMPLETE = "PROPAGATION_CONFIG_INCOMPLETE"
    INVALID_DAG = "INVALID_DAG"
    CANDIDATE_LIMIT_EXCEEDED = "CANDIDATE_LIMIT_EXCEEDED"
    RWR_NOT_CONVERGED = "RWR_NOT_CONVERGED"
    COMMON_DOMINATOR_UNAVAILABLE = "COMMON_DOMINATOR_UNAVAILABLE"
    AMBIGUOUS_DOMINATOR_WITNESS = "AMBIGUOUS_DOMINATOR_WITNESS"
    DEPENDENCY_SCOPE_UNAVAILABLE = "DEPENDENCY_SCOPE_UNAVAILABLE"
    SCOPE_LIMIT_EXCEEDED = "SCOPE_LIMIT_EXCEEDED"
    MATERIALIZATION_LIMIT_EXCEEDED = "MATERIALIZATION_LIMIT_EXCEEDED"
    TOPOLOGY_SOURCE_VERSION_MISSING = "TOPOLOGY_SOURCE_VERSION_MISSING"


@dataclass(frozen=True)
class DirectedUniverse:
    """One non-mixable directed topology source/relation universe.

    ``source_ref`` is the source ID plus its version when supplied.  Its pair
    with ``relation_type`` is the universe identity; callers must never join
    predecessor/successor information across two instances.
    """

    source_ref: str
    relation_type: str
    nodes: tuple[str, ...]
    predecessors: Mapping[str, tuple[str, ...]]
    successors: Mapping[str, tuple[str, ...]]
    provenance_class: ProvenanceClass
    provenance_subtype: ProvenanceSubtype | None
    source_kind: str | None
    source_version: str | None
    source_id: str | None = None
    scenario_id: str | None = None
    generator_version: str | None = None

    def __post_init__(self) -> None:
        """Normalize every public collection to deterministic immutable values."""
        nodes = tuple(sorted(self.nodes))
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(
            self,
            "predecessors",
            MappingProxyType(
                {
                    node: tuple(sorted(self.predecessors.get(node, ())))
                    for node in nodes
                }
            ),
        )
        object.__setattr__(
            self,
            "successors",
            MappingProxyType(
                {
                    node: tuple(sorted(self.successors.get(node, ())))
                    for node in nodes
                }
            ),
        )


@dataclass(frozen=True)
class DominatorResult:
    """Exact P2 annotation, deliberately separate from normalized evidence."""

    status: HypothesisStatus
    reason: TopologyHypothesisReason | None
    semantic: str | None
    witness_resource_id: str | None
    covered_resource_ids: tuple[str, ...]
    source_ref: str | None
    relation_type: str | None
    provenance_class: ProvenanceClass | None
    provenance_subtype: ProvenanceSubtype | None
    source_kind: str | None
    #: Retains the exact non-mixed universe for later scope analysis.
    universe: DirectedUniverse | None = None
    source_id: str | None = None
    source_version: str | None = None
    scenario_id: str | None = None
    generator_version: str | None = None

    def __post_init__(self) -> None:
        """Retain one deterministic immutable resource set in the public result."""
        object.__setattr__(
            self, "covered_resource_ids", tuple(sorted(set(self.covered_resource_ids)))
        )


@dataclass(frozen=True)
class PropagationNodeScore:
    """One alarm's converged stationary mass in the configured RWR."""

    alarm_id: str
    score: float


@dataclass(frozen=True)
class PropagationEdgeHypothesis:
    """Accepted graph-following flow on one direct admissible alarm edge."""

    source_alarm_id: str
    target_alarm_id: str
    score: float
    transition_probability: float
    temporal_delta_seconds: float


@dataclass(frozen=True)
class PropagationResult:
    """Configured RWR result with explicit capability and convergence state."""

    status: HypothesisStatus
    reason: TopologyHypothesisReason | None
    semantic: str | None
    source_ref: str | None
    relation_type: str | None
    provenance_class: ProvenanceClass | None
    provenance_subtype: ProvenanceSubtype | None
    source_kind: str | None
    config_version: str | None
    parameter_provenance: Mapping[str, str]
    candidate_node_count: int
    candidate_edge_count: int
    iterations: int
    final_l1_distance: float | None
    convergence_tolerance: float | None
    restart_probability: float | None
    seed_policy: str | None
    dangling_policy: str | None
    node_scores: tuple[PropagationNodeScore, ...]
    hypotheses: tuple[PropagationEdgeHypothesis, ...]
    source_id: str | None = None
    source_version: str | None = None
    scenario_id: str | None = None
    generator_version: str | None = None

    def __post_init__(self) -> None:
        """Freeze mappings and sort all public numerical output by alarm ID."""
        object.__setattr__(
            self,
            "parameter_provenance",
            MappingProxyType(dict(sorted(self.parameter_provenance.items()))),
        )
        object.__setattr__(
            self,
            "node_scores",
            tuple(sorted(self.node_scores, key=lambda node: node.alarm_id)),
        )
        object.__setattr__(
            self,
            "hypotheses",
            tuple(
                sorted(
                    self.hypotheses,
                    key=lambda edge: (edge.source_alarm_id, edge.target_alarm_id),
                )
            ),
        )


@dataclass(frozen=True)
class ResourceDetails:
    """Optional complete resource lists for a dependency-scope result.

    Detail materialization is deliberately independent from aggregate
    computation.  ``None`` means that no list was emitted, never an empty
    (and potentially misleading) partial list.
    """

    status: HypothesisStatus
    reason: TopologyHypothesisReason | None
    missing_resources: tuple[str, ...] | None
    extra_resources: tuple[str, ...] | None

    def __post_init__(self) -> None:
        for field_name in ("missing_resources", "extra_resources"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, tuple(sorted(set(value))))


@dataclass(frozen=True)
class DependencyScopeResult:
    """Exact overlap statistics anchored to the selected dominator witness."""

    status: HypothesisStatus
    reason: TopologyHypothesisReason | None
    semantic: str | None
    witness_resource_id: str | None
    source_ref: str | None
    relation_type: str | None
    provenance_class: ProvenanceClass | None
    provenance_subtype: ProvenanceSubtype | None
    source_kind: str | None
    observed_resource_count: int | None
    scope_resource_count: int | None
    intersection_count: int | None
    union_count: int | None
    observed_coverage: float | None
    scope_precision: float | None
    jaccard: float | None
    missing_resource_count: int | None
    extra_resource_count: int | None
    max_scope_resources: int | None
    max_materialized_resources: int | None
    parameter_provenance: Mapping[str, str]
    resource_details: ResourceDetails
    source_id: str | None = None
    source_version: str | None = None
    scenario_id: str | None = None
    generator_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameter_provenance",
            MappingProxyType(dict(sorted(self.parameter_provenance.items()))),
        )

    @property
    def observed_count(self) -> int | None:
        """Compact alias for clients using count terminology."""
        return self.observed_resource_count

    @property
    def scope_count(self) -> int | None:
        """Compact alias for clients using count terminology."""
        return self.scope_resource_count

    @property
    def missing_count(self) -> int | None:
        return self.missing_resource_count

    @property
    def extra_count(self) -> int | None:
        return self.extra_resource_count


@dataclass(frozen=True)
class TopologyHypothesesResult:
    """Independent Tier-2 topology capability results."""

    dominator: DominatorResult
    propagation: PropagationResult
    dependency_scope: DependencyScopeResult

    @property
    def scope(self) -> DependencyScopeResult:
        """Short alias retained for callers that refer to scope directly."""
        return self.dependency_scope

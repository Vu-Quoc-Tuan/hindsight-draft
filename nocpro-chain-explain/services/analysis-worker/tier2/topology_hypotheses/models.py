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

    def __post_init__(self) -> None:
        """Retain one deterministic immutable resource set in the public result."""
        object.__setattr__(
            self, "covered_resource_ids", tuple(sorted(set(self.covered_resource_ids)))
        )

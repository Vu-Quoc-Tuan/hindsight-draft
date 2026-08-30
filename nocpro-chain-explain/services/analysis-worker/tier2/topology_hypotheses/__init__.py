"""Fail-closed Tier-2 topology hypothesis primitives."""

from .dominator import analyze_common_dominator, build_directed_universes
from .models import (
    DependencyScopeResult,
    DirectedUniverse,
    DominatorResult,
    HypothesisStatus,
    PropagationEdgeHypothesis,
    PropagationNodeScore,
    PropagationResult,
    ResourceDetails,
    TopologyHypothesesResult,
    TopologyHypothesisReason,
)
from .analysis import analyze_topology_hypotheses
from .propagation import analyze_propagation
from .scope_overlap import analyze_dependency_scope, analyze_dependency_scope_for_chain

__all__ = [
    "DirectedUniverse",
    "DependencyScopeResult",
    "DominatorResult",
    "HypothesisStatus",
    "PropagationEdgeHypothesis",
    "PropagationNodeScore",
    "PropagationResult",
    "ResourceDetails",
    "TopologyHypothesesResult",
    "TopologyHypothesisReason",
    "analyze_common_dominator",
    "analyze_propagation",
    "analyze_dependency_scope",
    "analyze_dependency_scope_for_chain",
    "analyze_topology_hypotheses",
    "build_directed_universes",
]

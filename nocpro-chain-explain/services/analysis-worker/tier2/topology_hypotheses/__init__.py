"""Fail-closed Tier-2 topology hypothesis primitives."""

from .dominator import analyze_common_dominator, build_directed_universes
from .models import (
    DirectedUniverse,
    DominatorResult,
    HypothesisStatus,
    PropagationEdgeHypothesis,
    PropagationNodeScore,
    PropagationResult,
    TopologyHypothesisReason,
)
from .propagation import analyze_propagation

__all__ = [
    "DirectedUniverse",
    "DominatorResult",
    "HypothesisStatus",
    "PropagationEdgeHypothesis",
    "PropagationNodeScore",
    "PropagationResult",
    "TopologyHypothesisReason",
    "analyze_common_dominator",
    "analyze_propagation",
    "build_directed_universes",
]

"""Fail-closed Tier-2 topology hypothesis primitives."""

from .dominator import analyze_common_dominator, build_directed_universes
from .models import (
    DirectedUniverse,
    DominatorResult,
    HypothesisStatus,
    TopologyHypothesisReason,
)

__all__ = [
    "DirectedUniverse",
    "DominatorResult",
    "HypothesisStatus",
    "TopologyHypothesisReason",
    "analyze_common_dominator",
    "build_directed_universes",
]

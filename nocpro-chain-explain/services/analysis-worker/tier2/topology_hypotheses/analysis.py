"""Independent orchestration for the P2 topology hypothesis capabilities."""

from __future__ import annotations

from typing import Any

from configuration import P2TopologyConfig
from libs.contracts import IngestedPackage

from .dominator import analyze_common_dominator
from .models import (
    DependencyScopeResult,
    TopologyHypothesesResult,
    TopologyHypothesisReason,
)
from .propagation import analyze_propagation
from .scope_overlap import analyze_dependency_scope_for_chain


def _unavailable_scope() -> DependencyScopeResult:
    """Create the structured result for an absent optional scope config."""
    from .scope_overlap import _unavailable

    return _unavailable(TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE)


def _topology_config(config: Any) -> P2TopologyConfig | None:
    """Accept either the P2 envelope or a full AnalysisConfig object."""
    if isinstance(config, P2TopologyConfig):
        return config
    candidate = getattr(config, "p2_topology", None)
    return candidate if isinstance(candidate, P2TopologyConfig) else None


def analyze_topology_hypotheses(
    package: IngestedPackage,
    chain_id: str,
    config: P2TopologyConfig | Any | None,
) -> TopologyHypothesesResult:
    """Run dominator, propagation and scope independently for one chain.

    Propagation configuration failures are returned by its own analyzer.  The
    scope analyzer is anchored only to the dominator output and therefore does
    not depend on propagation succeeding.
    """
    topology_config = _topology_config(config)
    propagation_config = topology_config.propagation if topology_config else None
    scope_config = topology_config.dependency_scope if topology_config else None

    dominator = analyze_common_dominator(package, chain_id)
    propagation = analyze_propagation(package, chain_id, propagation_config)
    if scope_config is None:
        scope = _unavailable_scope()
    else:
        scope = analyze_dependency_scope_for_chain(
            package, chain_id, dominator, scope_config
        )
    return TopologyHypothesesResult(
        dominator=dominator,
        propagation=propagation,
        dependency_scope=scope,
    )

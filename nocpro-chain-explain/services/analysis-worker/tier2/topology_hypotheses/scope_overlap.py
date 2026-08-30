"""Exact dependency-scope overlap statistics with bounded detail output."""

from __future__ import annotations

from collections import deque
from types import MappingProxyType
from typing import Mapping

from configuration import ConfiguredValue, DependencyScopeConfig
from libs.contracts import IngestedPackage

from .models import (
    DependencyScopeResult,
    DirectedUniverse,
    DominatorResult,
    HypothesisStatus,
    ResourceDetails,
    TopologyHypothesisReason,
)


def _limits(
    config: DependencyScopeConfig | None,
) -> tuple[int, int, Mapping[str, str]] | None:
    """Validate scope limits without inventing defaults."""
    if config is None or not isinstance(config, DependencyScopeConfig):
        return None
    values = (config.max_scope_resources, config.max_materialized_resources)
    if any(not isinstance(value, ConfiguredValue) for value in values):
        return None
    if any(not isinstance(value.path, str) or not value.path for value in values):
        return None
    if len({value.path for value in values}) != len(values):
        return None
    if any(
        isinstance(value.value, bool)
        or not isinstance(value.value, int)
        or value.value <= 0
        for value in values
    ):
        return None
    if config.max_materialized_resources.value > config.max_scope_resources.value:
        return None
    try:
        provenance = MappingProxyType(
            dict(sorted((value.path, value.source.value) for value in values))
        )
    except AttributeError:
        return None
    return (
        config.max_scope_resources.value,
        config.max_materialized_resources.value,
        provenance,
    )


def _details_unavailable(
    reason: TopologyHypothesisReason,
) -> ResourceDetails:
    return ResourceDetails(
        status=HypothesisStatus.UNAVAILABLE,
        reason=reason,
        missing_resources=None,
        extra_resources=None,
    )


def _unavailable(
    reason: TopologyHypothesisReason,
    *,
    dominator: DominatorResult | None = None,
    observed_resource_count: int | None = None,
    scope_resource_count: int | None = None,
    max_scope_resources: int | None = None,
    max_materialized_resources: int | None = None,
    parameter_provenance: Mapping[str, str] | None = None,
) -> DependencyScopeResult:
    parameter_provenance = parameter_provenance or {}
    return DependencyScopeResult(
        status=HypothesisStatus.UNAVAILABLE,
        reason=reason,
        semantic=None,
        witness_resource_id=(dominator.witness_resource_id if dominator else None),
        source_ref=(dominator.source_ref if dominator else None),
        relation_type=(dominator.relation_type if dominator else None),
        provenance_class=(dominator.provenance_class if dominator else None),
        provenance_subtype=(dominator.provenance_subtype if dominator else None),
        source_kind=(dominator.source_kind if dominator else None),
        observed_resource_count=observed_resource_count,
        scope_resource_count=scope_resource_count,
        intersection_count=None,
        union_count=None,
        observed_coverage=None,
        scope_precision=None,
        jaccard=None,
        missing_resource_count=None,
        extra_resource_count=None,
        max_scope_resources=max_scope_resources,
        max_materialized_resources=max_materialized_resources,
        parameter_provenance=parameter_provenance,
        resource_details=_details_unavailable(reason),
    )


def _reachable_dependents(universe: DirectedUniverse, witness: str) -> set[str]:
    """Return every real node reachable from ``witness``, excluding witness."""
    node_set = set(universe.nodes)
    seen: set[str] = {witness}
    dependents: set[str] = set()
    queue: deque[str] = deque([witness])
    while queue:
        source = queue.popleft()
        for target in universe.successors.get(source, ()):
            if target not in node_set:
                continue
            if target in seen:
                continue
            seen.add(target)
            dependents.add(target)
            queue.append(target)
    return dependents


def analyze_dependency_scope(
    package: IngestedPackage,
    dominator: DominatorResult,
    config: DependencyScopeConfig | None,
) -> DependencyScopeResult:
    """Compare exact observed resources with dependents of the chosen witness.

    The supplied dominator result is authoritative.  This function never
    searches for another witness, including when the supplied result is over a
    universe that cannot satisfy a configured limit.
    """
    configured = _limits(config)
    if configured is None:
        return _unavailable(
            TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE,
            dominator=dominator,
        )
    max_scope, max_materialized, provenance = configured

    if (
        dominator.status is not HypothesisStatus.AVAILABLE
        or not dominator.witness_resource_id
        or dominator.universe is None
    ):
        return _unavailable(
            TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE,
            dominator=dominator,
            max_scope_resources=max_scope,
            max_materialized_resources=max_materialized,
            parameter_provenance=provenance,
        )

    return _analyze_dependency_scope_with_members(
        package,
        dominator,
        config,
        max_scope,
        max_materialized,
        provenance,
    )


def _analyze_dependency_scope_with_members(
    package: IngestedPackage,
    dominator: DominatorResult,
    config: DependencyScopeConfig,
    max_scope: int,
    max_materialized: int,
    provenance: Mapping[str, str],
    chain_id: str | None = None,
) -> DependencyScopeResult:
    """Implementation helper; chain members come from the package contract."""
    # DominatorResult deliberately stores covered resources, which are the
    # exact mapped chain set selected by analyze_common_dominator.  Use those
    # resources as the observed set so no alternate mapping or witness can be
    # introduced here.
    observed = set(dominator.covered_resource_ids)
    if not observed:
        return _unavailable(
            TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE,
            dominator=dominator,
            observed_resource_count=0,
            max_scope_resources=max_scope,
            max_materialized_resources=max_materialized,
            parameter_provenance=provenance,
        )

    universe = dominator.universe
    assert universe is not None
    witness = dominator.witness_resource_id
    if witness not in universe.nodes:
        return _unavailable(
            TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE,
            dominator=dominator,
            observed_resource_count=len(observed),
            max_scope_resources=max_scope,
            max_materialized_resources=max_materialized,
            parameter_provenance=provenance,
        )
    scope = _reachable_dependents(universe, witness)
    scope_count = len(scope)
    if scope_count > max_scope:
        return _unavailable(
            TopologyHypothesisReason.SCOPE_LIMIT_EXCEEDED,
            dominator=dominator,
            observed_resource_count=len(observed),
            scope_resource_count=scope_count,
            max_scope_resources=max_scope,
            max_materialized_resources=max_materialized,
            parameter_provenance=provenance,
        )
    if scope_count == 0:
        return _unavailable(
            TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE,
            dominator=dominator,
            observed_resource_count=len(observed),
            scope_resource_count=0,
            max_scope_resources=max_scope,
            max_materialized_resources=max_materialized,
            parameter_provenance=provenance,
        )

    intersection = observed & scope
    union = observed | scope
    missing = observed - scope
    extra = scope - observed
    details_count = len(missing) + len(extra)
    if details_count <= max_materialized:
        details = ResourceDetails(
            status=HypothesisStatus.AVAILABLE,
            reason=None,
            missing_resources=tuple(sorted(missing)),
            extra_resources=tuple(sorted(extra)),
        )
    else:
        details = _details_unavailable(
            TopologyHypothesisReason.MATERIALIZATION_LIMIT_EXCEEDED
        )

    return DependencyScopeResult(
        status=HypothesisStatus.AVAILABLE,
        reason=None,
        semantic="DEPENDENCY_SCOPE_OVERLAP_SIGNAL",
        witness_resource_id=witness,
        source_ref=dominator.source_ref,
        relation_type=dominator.relation_type,
        provenance_class=dominator.provenance_class,
        provenance_subtype=dominator.provenance_subtype,
        source_kind=dominator.source_kind,
        observed_resource_count=len(observed),
        scope_resource_count=scope_count,
        intersection_count=len(intersection),
        union_count=len(union),
        observed_coverage=len(intersection) / len(observed),
        scope_precision=len(intersection) / len(scope),
        jaccard=len(intersection) / len(union),
        missing_resource_count=len(missing),
        extra_resource_count=len(extra),
        max_scope_resources=max_scope,
        max_materialized_resources=max_materialized,
        parameter_provenance=provenance,
        resource_details=details,
    )


def analyze_dependency_scope_for_chain(
    package: IngestedPackage,
    chain_id: str,
    dominator: DominatorResult,
    config: DependencyScopeConfig | None,
) -> DependencyScopeResult:
    """Chain-aware scope entry point used by orchestration."""
    configured = _limits(config)
    if configured is None:
        return _unavailable(
            TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE,
            dominator=dominator,
        )
    max_scope, max_materialized, provenance = configured
    if (
        dominator.status is not HypothesisStatus.AVAILABLE
        or not dominator.witness_resource_id
        or dominator.universe is None
    ):
        return _unavailable(
            TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE,
            dominator=dominator,
            max_scope_resources=max_scope,
            max_materialized_resources=max_materialized,
            parameter_provenance=provenance,
        )
    # ``covered_resource_ids`` is the exact mapped chain set produced by the
    # already selected dominator.  Keep that result anchored: re-resolving
    # mappings here could silently change the observed set between analyses.
    return _analyze_dependency_scope_with_members(
        package,
        dominator,
        config,
        max_scope,
        max_materialized,
        provenance,
    )

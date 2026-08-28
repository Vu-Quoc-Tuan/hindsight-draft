"""Exact bitmap sufficient statistics for ``DEP_UPSTREAM`` providers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from groups.indexed_statistics import ChannelFitFromIndex
from libs.contracts import IngestedAlarm, IngestedPackage
from libs.provenance import ProvenanceClass, ProvenanceSubtype

from .common_dependency import (
    DepUpstreamActivePath,
    DepUpstreamAncestor,
    DependencyProvider,
    build_dep_upstream_providers,
    specificity,
)
from .dependency import ResourceResolver


def _fit(
    provider: DependencyProvider,
    *,
    domain: int,
    supporting: int,
) -> ChannelFitFromIndex:
    return ChannelFitFromIndex(
        channel_id=provider.channel_id,
        derivation_tag=f"dependency:{provider.source_ref}",
        provenance_class=(
            provider.hierarchy.provenance_class
            if isinstance(provider, DepUpstreamAncestor) and provider.hierarchy
            else provider.path_index.provenance_class
            if isinstance(provider, DepUpstreamActivePath) and provider.path_index
            else ProvenanceClass.EXTERNAL_OPERATIONAL
        ),
        fit=supporting / domain if domain else None,
        domain_size=domain,
        supporting=supporting,
    )


def _provider_provenance(
    provider: DependencyProvider,
) -> tuple[ProvenanceClass, ProvenanceSubtype | None]:
    source = (
        provider.hierarchy
        if isinstance(provider, DepUpstreamAncestor)
        else provider.path_index
    )
    if source is None:
        return (
            ProvenanceClass.EXTERNAL_OPERATIONAL,
            ProvenanceSubtype.TOPOLOGY_EXTERNAL,
        )
    return source.provenance_class, source.provenance_subtype


@dataclass
class _AncestorIndex:
    provider: DepUpstreamAncestor
    resolver: ResourceResolver
    peer_positions: dict[str, int]
    distance_bitmaps: dict[str, dict[int, int]]

    @classmethod
    def build(
        cls,
        provider: DepUpstreamAncestor,
        resolver: ResourceResolver,
        peers: list[IngestedAlarm],
    ) -> "_AncestorIndex":
        positions = {alarm.alarm_id: index for index, alarm in enumerate(peers)}
        postings: dict[str, dict[int, int]] = {}
        hierarchy = provider.hierarchy
        if hierarchy is not None and hierarchy.is_valid:
            for alarm in peers:
                resource = resolver.resource_of(alarm.alarm_id)
                if resource is None:
                    continue
                bit = 1 << positions[alarm.alarm_id]
                for distance, ancestor in enumerate(
                    hierarchy.ancestors_of(resource), start=1
                ):
                    by_distance = postings.setdefault(ancestor, {})
                    by_distance[distance] = by_distance.get(distance, 0) | bit
        return cls(provider, resolver, positions, postings)

    def query(self, alarm: IngestedAlarm) -> ChannelFitFromIndex:
        hierarchy = self.provider.hierarchy
        resource = self.resolver.resource_of(alarm.alarm_id)
        if hierarchy is None or not hierarchy.is_valid or resource is None:
            return _fit(self.provider, domain=0, supporting=0)

        available = 0
        supporting = 0
        universe = hierarchy.total_resources
        for distance_i, ancestor in enumerate(
            hierarchy.ancestors_of(resource), start=1
        ):
            by_distance = self.distance_bitmaps.get(ancestor, {})
            for distance_j, bitmap in by_distance.items():
                available |= bitmap
                score = specificity(
                    len(hierarchy.descendants_of(ancestor)) or 1, universe
                ) * math.exp(
                    -(distance_i + distance_j) / self.provider.lambda_dep
                )
                if score >= self.provider.theta:
                    supporting |= bitmap

        own_position = self.peer_positions.get(alarm.alarm_id)
        if own_position is not None:
            own_mask = ~(1 << own_position)
            available &= own_mask
            supporting &= own_mask
        return _fit(
            self.provider,
            domain=available.bit_count(),
            supporting=supporting.bit_count(),
        )


@dataclass
class _ActivePathIndex:
    provider: DepUpstreamActivePath
    resolver: ResourceResolver
    peer_positions: dict[str, int]
    distance_bitmaps: dict[str, dict[int, int]]

    @classmethod
    def build(
        cls,
        provider: DepUpstreamActivePath,
        resolver: ResourceResolver,
        peers: list[IngestedAlarm],
    ) -> "_ActivePathIndex":
        positions = {alarm.alarm_id: index for index, alarm in enumerate(peers)}
        postings: dict[str, dict[int, int]] = {}
        path_index = provider.path_index
        if path_index is not None and path_index.is_valid:
            for alarm in peers:
                resource = resolver.resource_of(alarm.alarm_id)
                if resource is None:
                    continue
                bit = 1 << positions[alarm.alarm_id]
                nodes = {
                    node
                    for path in path_index.paths_of.get(resource, ())
                    for node in path.nodes
                }
                for node in nodes:
                    distance = path_index.min_hop_distance(resource, node)
                    if distance is None:
                        continue
                    by_distance = postings.setdefault(node, {})
                    by_distance[distance] = by_distance.get(distance, 0) | bit
        return cls(provider, resolver, positions, postings)

    def query(self, alarm: IngestedAlarm) -> ChannelFitFromIndex:
        path_index = self.provider.path_index
        resource = self.resolver.resource_of(alarm.alarm_id)
        if (
            path_index is None
            or not path_index.is_valid
            or resource is None
            or not path_index.paths_of.get(resource)
        ):
            return _fit(self.provider, domain=0, supporting=0)

        available = 0
        supporting = 0
        nodes = {
            node
            for path in path_index.paths_of[resource]
            for node in path.nodes
        }
        for node in nodes:
            distance_i = path_index.min_hop_distance(resource, node)
            if distance_i is None:
                continue
            for distance_j, bitmap in self.distance_bitmaps.get(node, {}).items():
                available |= bitmap
                score = specificity(
                    len(path_index.traversing_resources(node)) or 1,
                    path_index.observed_resource_count,
                ) * math.exp(
                    -(distance_i + distance_j) / self.provider.lambda_dep
                )
                if score >= self.provider.theta:
                    supporting |= bitmap

        own_position = self.peer_positions.get(alarm.alarm_id)
        if own_position is not None:
            own_mask = ~(1 << own_position)
            available &= own_mask
            supporting &= own_mask
        return _fit(
            self.provider,
            domain=available.bit_count(),
            supporting=supporting.bit_count(),
        )


class DepUpstreamFitIndex:
    """Reusable exact provider queries for one peer universe."""

    def __init__(
        self,
        package: IngestedPackage,
        peers: list[IngestedAlarm],
        *,
        lambda_dep: float,
        theta: float,
    ) -> None:
        self.resolver = ResourceResolver.from_package(package)
        self.providers = build_dep_upstream_providers(
            package,
            resolver=self.resolver,
            lambda_dep=lambda_dep,
            theta=theta,
        )
        self._indexes = tuple(
            _AncestorIndex.build(provider, self.resolver, peers)
            if isinstance(provider, DepUpstreamAncestor)
            else _ActivePathIndex.build(provider, self.resolver, peers)
            for provider in self.providers
        )

    @property
    def channel_meta(
        self,
    ) -> dict[str, tuple[str, ProvenanceClass, ProvenanceSubtype | None]]:
        result = {}
        for provider in self.providers:
            provenance_class, provenance_subtype = _provider_provenance(provider)
            result[provider.channel_id] = (
                f"dependency:{provider.source_ref}",
                provenance_class,
                provenance_subtype,
            )
        return result

    def fits_for(self, alarm: IngestedAlarm) -> tuple[ChannelFitFromIndex, ...]:
        return tuple(index.query(alarm) for index in self._indexes)

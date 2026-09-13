"""Alarm -> topology resource mapping.

Fail-closed by construction (ADR-MOCK-0005, docs 04/06). The default
production-shaped mapper accepts only exact device/resource identity.  topoIT
join fields are useful for structural navigation, but are not an authoritative
alarm-to-resource mapping table and therefore are not enabled by this adapter.

Prefix/fuzzy similarity is never a mapping method. This matters concretely: the
real ``topoIP`` export contains no ``DEHL01`` / ``DEHT01`` / ``HLC9102DEA01`` /
``HHT9603DEA01``, yet 122 ``HLC9102*`` and 266 ``HHT9603*`` rows do exist. Those
prefixes are a trap, not permission to map, so this module offers no prefix API.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..contract import AlarmResourceMapping, MappingMethod, MappingStatus
from .topology import TOPOLOGY_LAYER_IP


@dataclass(frozen=True)
class AliasEntry:
    """One unambiguous source-field alias with auditable provenance.

    The verified_by value names the source table/column, not a human or
    business authority. This type must not claim production mapping validation
    by itself.
    """

    alias: str
    resource_id: str
    verified_by: str
    note: str | None = None


class ResourceMapper:
    """Maps alarm device identifiers to topology resources."""

    def __init__(
        self,
        known_resources: set[str],
        *,
        aliases: dict[str, AliasEntry] | None = None,
        ambiguous_aliases: set[str] | None = None,
        topology_layer: str | None = None,
        source_version: str | None = None,
    ) -> None:
        self.known_resources = known_resources
        self.aliases = aliases or {}
        self.ambiguous_aliases = ambiguous_aliases or set()
        self.topology_layer = topology_layer
        self.source_version = source_version

    def map_identifier(self, identifier: str | None) -> tuple[
        str | None, MappingStatus, MappingMethod, float | None
    ]:
        """Resolve one identifier to ``(resource_id, status, method, confidence)``."""
        key = (identifier or "").strip()
        if not key:
            return None, MappingStatus.UNMAPPED, MappingMethod.NONE, None

        if key in self.known_resources:
            return key, MappingStatus.EXACT, MappingMethod.EXACT_IDENTITY, 1.0

        if key in self.ambiguous_aliases:
            return None, MappingStatus.AMBIGUOUS, MappingMethod.NONE, None

        alias = self.aliases.get(key)
        if alias is not None:
            if alias.resource_id in self.known_resources:
                return (
                    alias.resource_id,
                    MappingStatus.VERIFIED_ALIAS,
                    MappingMethod.VERIFIED_ALIAS_TABLE,
                    1.0,
                )
            # An alias pointing at an absent resource resolves nothing.
            return None, MappingStatus.UNMAPPED, MappingMethod.NONE, None

        return None, MappingStatus.UNMAPPED, MappingMethod.NONE, None

    def map_alarm(
        self, alarm_id: str, *, device_code: str | None, node_reference: str | None = None
    ) -> AlarmResourceMapping:
        """Map an alarm, preferring ``device_code`` then ``node_reference``.

        If both resolve to different resources the result is AMBIGUOUS: the mock
        does not pick a winner.
        """
        candidates: list[tuple[str, MappingStatus, MappingMethod, float | None]] = []
        saw_ambiguous = False
        for identifier in (device_code, node_reference):
            resource_id, status, method, confidence = self.map_identifier(identifier)
            if resource_id is not None:
                candidates.append((resource_id, status, method, confidence))
            elif status is MappingStatus.AMBIGUOUS:
                saw_ambiguous = True

        if saw_ambiguous:
            return AlarmResourceMapping(
                alarm_id=alarm_id,
                resource_id=None,
                mapping_status=MappingStatus.AMBIGUOUS,
                mapping_method=MappingMethod.NONE,
                mapping_confidence=None,
                topology_layer=self.topology_layer,
                source_version=self.source_version,
            )

        distinct = {c[0] for c in candidates}
        if len(distinct) > 1:
            return AlarmResourceMapping(
                alarm_id=alarm_id,
                resource_id=None,
                mapping_status=MappingStatus.AMBIGUOUS,
                mapping_method=MappingMethod.NONE,
                mapping_confidence=None,
                topology_layer=self.topology_layer,
                source_version=self.source_version,
            )

        if candidates:
            resource_id, status, method, confidence = candidates[0]
            return AlarmResourceMapping(
                alarm_id=alarm_id,
                resource_id=resource_id,
                mapping_status=status,
                mapping_method=method,
                mapping_confidence=confidence,
                topology_layer=self.topology_layer,
                source_version=self.source_version,
            )

        return AlarmResourceMapping(
            alarm_id=alarm_id,
            resource_id=None,
            mapping_status=MappingStatus.UNMAPPED,
            mapping_method=MappingMethod.NONE,
            mapping_confidence=None,
            topology_layer=self.topology_layer,
            source_version=self.source_version,
        )
    def map_real_alarm(
        self,
        alarm_id: str,
        *,
        device_code: str | None = None,
        node_reference: str | None = None,
        device_ip: str | None = None,
        component: str | None = None,
    ) -> AlarmResourceMapping:
        """Map a real alarm from all exact source identifiers.

        Multiple distinct exact hits are deliberately reported as ambiguous;
        this is not a first-match priority resolver.
        """
        identifiers_to_try = [device_code, node_reference]
        if device_ip:
            clean_ip = device_ip.strip().split("/")[0]
            identifiers_to_try.append(clean_ip)
            identifiers_to_try.append(f"it:instance:{clean_ip}")
        if component:
            identifiers_to_try.append(component.strip())
            identifiers_to_try.append(f"it:service:{component.strip()}")

        saw_ambiguous = False
        candidates: list[tuple[str, MappingStatus, MappingMethod, float | None]] = []
        for ident in identifiers_to_try:
            if not ident:
                continue
            res_id, status, method, conf = self.map_identifier(ident)
            if res_id is not None:
                candidates.append((res_id, status, method, conf))
            elif status is MappingStatus.AMBIGUOUS:
                saw_ambiguous = True

        if saw_ambiguous or len({candidate[0] for candidate in candidates}) > 1:
            return AlarmResourceMapping(
                alarm_id=alarm_id,
                resource_id=None,
                mapping_status=MappingStatus.AMBIGUOUS,
                mapping_method=MappingMethod.NONE,
                mapping_confidence=None,
                topology_layer=self.topology_layer,
                source_version=self.source_version,
            )

        if candidates:
            res_id, status, method, conf = candidates[0]
            return AlarmResourceMapping(
                alarm_id=alarm_id,
                resource_id=res_id,
                mapping_status=status,
                mapping_method=method,
                mapping_confidence=conf,
                topology_layer=self.topology_layer,
                source_version=self.source_version,
            )

        return AlarmResourceMapping(
            alarm_id=alarm_id,
            resource_id=None,
            mapping_status=MappingStatus.UNMAPPED,
            mapping_method=MappingMethod.NONE,
            mapping_confidence=None,
            topology_layer=self.topology_layer,
            source_version=self.source_version,
        )


def build_it_resource_mapper(
    topo_it_dir: str | Path,
    *,
    source_version: str | None = None,
) -> ResourceMapper:
    """Build a fail-closed IT mapper.

    topoIT aliases intentionally remain outside this mapper: their CSV columns
    establish source-record joins for navigation only, not an authoritative
    relationship between a production alarm and a topology resource.  Keeping
    them here would turn an implementation convenience into a false
    ``VERIFIED_ALIAS`` claim.  Exact canonical resource IDs can still resolve.
    """
    from ..loaders.topology_it_csv import ITTopologyLoader

    loader = ITTopologyLoader(topo_it_dir)
    graph = loader.load_graph()
    known_resources = {node.resource_id for node in graph.nodes}
    return ResourceMapper(
        known_resources=known_resources,
        topology_layer="IT",
        source_version=source_version or graph.source_version,
    )


def build_ip_resource_mapper(
    topo_ip_path: str | Path,
    *,
    source_version: str | None = None,
) -> ResourceMapper:
    """Build an IP ResourceMapper with network device codes."""
    from ..loaders.topology_ip_csv import TopoIPLoader

    loader = TopoIPLoader(topo_ip_path)
    known_resources = set(loader.device_codes())
    return ResourceMapper(
        known_resources=known_resources,
        topology_layer="IP",
        source_version=source_version or loader.source_version(),
    )

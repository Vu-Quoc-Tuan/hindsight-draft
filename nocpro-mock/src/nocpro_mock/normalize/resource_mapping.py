"""Alarm -> topology resource mapping.

Fail-closed by construction (ADR-MOCK-0005, docs 04/06). Resolution order:
  1. exact device/resource identity,
  2. verified alias table,
  3. otherwise UNMAPPED.

Prefix/fuzzy similarity is never a mapping method. This matters concretely: the
real ``topoIP`` export contains no ``DEHL01`` / ``DEHT01`` / ``HLC9102DEA01`` /
``HHT9603DEA01``, yet 122 ``HLC9102*`` and 266 ``HHT9603*`` rows do exist. Those
prefixes are a trap, not permission to map, so this module offers no prefix API.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contract import AlarmResourceMapping, MappingMethod, MappingStatus


@dataclass(frozen=True)
class AliasEntry:
    """One human-verified alias. ``verified_by``/``note`` keep it auditable."""

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
        topology_layer: str | None = None,
        source_version: str | None = None,
    ) -> None:
        self.known_resources = known_resources
        self.aliases = aliases or {}
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
        for identifier in (device_code, node_reference):
            resource_id, status, method, confidence = self.map_identifier(identifier)
            if resource_id is not None:
                candidates.append((resource_id, status, method, confidence))

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

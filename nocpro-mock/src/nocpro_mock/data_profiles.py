"""Named, non-interchangeable real-export input profiles.

The profile is deliberately one atomic choice: it selects the correct alarm
export and its only matching topology source.  Consumers may not silently mix
an IP alarm export with the IT relation archive, or vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TopologyKind = Literal["UNAVAILABLE", "UNDIRECTED_ADJACENCY", "DIRECTED_SOURCE_RELATIONS"]
AlarmResourceMappingCapability = Literal["UNAVAILABLE", "PARTIAL_EXACT_ONLY"]
NavigationMappingCapability = Literal[
    "UNAVAILABLE",
    "PARTIAL_EXACT_IDENTITY",
    "PARTIAL_SOURCE_FIELD_EXACT",
]


@dataclass(frozen=True)
class DatasetProfile:
    profile_id: Literal["ALARM_ONLY", "IP_NETWORK", "IT_SERVICES"]
    display_name: str
    alarm_csv: str
    topology_path: str | None
    topology_kind: TopologyKind
    direction_kind: Literal["NONE", "SOURCE_RELATION"] | None
    dependency_semantics: Literal["UNVERIFIED", "UNAVAILABLE"] | None
    # Navigation mappings deliberately have a separate capability from P2.
    # A source-field match can open a record in the tree without becoming an
    # alarm-to-operational-resource mapping.
    navigation_mapping: NavigationMappingCapability
    alarm_resource_mapping: AlarmResourceMappingCapability


_PROFILES: dict[str, DatasetProfile] = {
    "ALARM_ONLY": DatasetProfile(
        "ALARM_ONLY", "Alarm only", "datasets/raw/alarm/alarm_data.csv", None,
        "UNAVAILABLE", None, None, "UNAVAILABLE", "UNAVAILABLE",
    ),
    "IP_NETWORK": DatasetProfile(
        "IP_NETWORK", "IP network adjacency", "datasets/raw/alarm/alarmIP.csv",
        "datasets/raw/topo/topoIP.csv", "UNDIRECTED_ADJACENCY", "NONE", "UNAVAILABLE",
        "PARTIAL_EXACT_IDENTITY", "PARTIAL_EXACT_ONLY",
    ),
    "IT_SERVICES": DatasetProfile(
        "IT_SERVICES", "IT source relations", "datasets/raw/alarm/alarmIT.csv",
        "datasets/raw/topo/topoIT", "DIRECTED_SOURCE_RELATIONS", "SOURCE_RELATION", "UNVERIFIED",
        "PARTIAL_SOURCE_FIELD_EXACT", "UNAVAILABLE",
    ),
}


def dataset_profiles() -> tuple[DatasetProfile, ...]:
    return tuple(_PROFILES.values())


def resolve_dataset_profile(profile_id: str) -> DatasetProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        valid = ", ".join(_PROFILES)
        raise ValueError(f"unknown dataset profile {profile_id!r}; expected one of: {valid}") from exc

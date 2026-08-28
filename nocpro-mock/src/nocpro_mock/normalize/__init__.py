"""Normalization: raw loader records -> canonical contract objects."""

from .alarms import build_chains, normalize_alarm
from .resource_mapping import AliasEntry, ResourceMapper
from .topology import (
    TOPOLOGY_LAYER_IP,
    freshness_quality,
    normalize_topo_ip,
)

__all__ = [
    "TOPOLOGY_LAYER_IP",
    "AliasEntry",
    "ResourceMapper",
    "build_chains",
    "freshness_quality",
    "normalize_alarm",
    "normalize_topo_ip",
]

"""Topology Hierarchy and Directionality Normalizer.

Transforms undirected adjacency sources (like topoIP) and multi-table IT relations
into hierarchical directed representations for P2 propagation and dominator analysis.

Network hierarchy levels for IP:
  0: CORE / BACKBONE
  1: AGG_DISTRICT / AGGREGATION / METRO
  2: SITE_ROUTER / ACCESS / SWITCH / CLIENT

Service hierarchy levels for IT:
  0: SERVICE
  1: MODULE
  2: INSTANCE
  3: DATABASE / STORAGE
"""

from __future__ import annotations

from typing import Literal, Mapping

IP_NETWORK_CLASS_RANKS: dict[str, int] = {
    "CORE": 0,
    "IP_CORE": 0,
    "BACKBONE": 0,
    "AGG_DISTRICT": 1,
    "AGG": 1,
    "METRO": 1,
    "SITE_ROUTER": 2,
    "ACCESS": 2,
    "INTERNAL_SW_LAYER": 2,
    "CLIENT": 3,
}

IT_RESOURCE_TYPE_RANKS: dict[str, int] = {
    "SERVICE": 0,
    "MODULE": 1,
    "INSTANCE": 2,
    "DATABASE": 3,
    "STORAGE": 3,
}


def ip_device_rank(network_class_name: str | None) -> int:
    """Return numeric hierarchy rank for an IP device (lower is closer to core)."""
    if not network_class_name:
        return 2  # default to access/edge
    upper = network_class_name.strip().upper()
    for key, rank in IP_NETWORK_CLASS_RANKS.items():
        if key in upper:
            return rank
    return 2


def orient_ip_edge(
    source_device: str,
    source_class: str | None,
    target_device: str,
    target_class: str | None,
) -> tuple[str, str, bool]:
    """Orient an edge between two IP devices based on network hierarchy.

    Returns:
        (upstream_device, downstream_device, is_hierarchical)
        If both have same rank, returns (source, target, False) representing peer adjacency.
    """
    rank_src = ip_device_rank(source_class)
    rank_tgt = ip_device_rank(target_class)

    if rank_src < rank_tgt:
        # source is upstream (e.g. CORE -> AGG)
        return source_device, target_device, True
    elif rank_tgt < rank_src:
        # target is upstream (e.g. AGG -> SITE_ROUTER)
        return target_device, source_device, True
    else:
        # Peer connection at same tier
        return source_device, target_device, False


def it_resource_rank(resource_type: str | None) -> int:
    """Return numeric hierarchy rank for IT resource."""
    if not resource_type:
        return 2
    return IT_RESOURCE_TYPE_RANKS.get(resource_type.strip().upper(), 2)

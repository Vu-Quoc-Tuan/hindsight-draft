"""Bounded Subgraph Extraction for IP Topology.

Extracts a lightweight, localized subnetwork around a set of seed device codes
(e.g., devices with active alarms in a snapshot package) rather than embedding
the entire 100,000-node network.

Preserves exact undirected adjacency without manufacturing fake directions
or breaking fail-closed boundaries (ADR-MOCK-0005).
"""

from __future__ import annotations

from typing import Iterable, Sequence

from ..loaders.topology_ip_csv import TopoIPRelation


def extract_bounded_ip_subgraph(
    relations: Sequence[TopoIPRelation],
    seed_device_codes: Iterable[str | None],
    *,
    max_hops: int = 1,
    max_relations: int = 500,
) -> tuple[TopoIPRelation, ...]:
    """Extract 1-hop (or k-hop) neighborhood of relations around seed devices.

    Args:
        relations: Full list/sequence of TopoIPRelation from TopoIPLoader.
        seed_device_codes: Device codes of interest (e.g. from alarms).
        max_hops: Maximum graph distance from seed devices (default: 1).
        max_relations: Safety ceiling to prevent unbounded explosion in dense core.

    Returns:
        tuple of TopoIPRelation containing only seed devices and their neighbors.
    """
    seeds = {
        code.strip()
        for code in seed_device_codes
        if code and isinstance(code, str) and code.strip()
    }
    if not seeds:
        return ()

    current_devices = set(seeds)
    selected_relations: list[TopoIPRelation] = []
    seen_relation_ids: set[str] = set()

    for _ in range(max_hops):
        next_devices = set()
        for rel in relations:
            d1 = (rel.device_code or "").strip()
            d2 = (rel.device_code_relation or "").strip()

            # Check if this edge touches our current boundary
            if d1 in current_devices or d2 in current_devices:
                if rel.relation_id not in seen_relation_ids:
                    seen_relation_ids.add(rel.relation_id)
                    selected_relations.append(rel)
                    if d1:
                        next_devices.add(d1)
                    if d2:
                        next_devices.add(d2)

                if len(selected_relations) >= max_relations:
                    break

        current_devices.update(next_devices)
        if len(selected_relations) >= max_relations:
            break

    return tuple(selected_relations)

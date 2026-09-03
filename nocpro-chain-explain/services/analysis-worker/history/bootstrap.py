"""Build frozen H episodes from a verified lineage-DAG prefix."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from evolution import GlobalEpisodeDag, LineageNodeKey
from libs.contracts import IngestedPackage

from .evidence import HistoricalChainState, HistoricalEpisode, HistoricalTaxonomy


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def episodes_from_lineage_prefix(
    packages: list[IngestedPackage],
    *,
    dag: GlobalEpisodeDag,
    cutoff: str,
    taxonomy: HistoricalTaxonomy,
) -> tuple[tuple[HistoricalEpisode, ...], str]:
    """Return weak components and immutable prefix fingerprint before cutoff.

    Component aliases in a later DAG state are ignored.  Connectivity is rebuilt
    strictly from nodes and lineage edges that existed before ``cutoff`` so a
    future merge cannot alter a model already frozen for an earlier query.
    """
    cutoff_time = _time(cutoff)
    package_by_identity = {
        (item.snapshot.snapshot_id, item.snapshot.snapshot_version): item
        for item in packages
        if _time(item.snapshot.snapshot_time) < cutoff_time
    }
    nodes = {
        key
        for key, node in dag.nodes.items()
        if (key.snapshot_id, key.snapshot_version) in package_by_identity
        and _time(node.snapshot_time) < cutoff_time
    }
    adjacency = {key: set() for key in nodes}
    included_edges = []
    for edge in dag.edges.values():
        if edge.parent in nodes and edge.child in nodes:
            adjacency[edge.parent].add(edge.child)
            adjacency[edge.child].add(edge.parent)
            included_edges.append((edge.parent, edge.child, edge.edge_type))

    components: list[list[LineageNodeKey]] = []
    remaining = set(nodes)
    while remaining:
        start = min(remaining)
        stack, component = [start], []
        remaining.remove(start)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))

    episodes = []
    for component in components:
        states_by_identity: dict[tuple[str, str], list[LineageNodeKey]] = {}
        for key in component:
            states_by_identity.setdefault((key.snapshot_id, key.snapshot_version), []).append(key)
        states = []
        for identity, chain_keys in sorted(
            states_by_identity.items(),
            key=lambda item: (_time(package_by_identity[item[0]].snapshot.snapshot_time), item[0]),
        ):
            package = package_by_identity[identity]
            chains = []
            for key in sorted(chain_keys, key=lambda item: item.snapshot_chain_id):
                chains.append(
                    tuple(
                        resolved
                        for alarm in package.alarms_of(key.snapshot_chain_id)
                        if (resolved := taxonomy.resolve(alarm)) is not None
                    )
                )
            states.append(
                HistoricalChainState(
                    package.snapshot.snapshot_id,
                    package.snapshot.snapshot_version,
                    package.snapshot.snapshot_time,
                    tuple(chains),
                )
            )
        seed = "\0".join(
            f"{key.snapshot_id}:{key.snapshot_version}:{key.snapshot_chain_id}"
            for key in component
        ).encode()
        episodes.append(HistoricalEpisode(f"episode_{hashlib.sha256(seed).hexdigest()[:24]}", tuple(states)))

    fingerprint_material = {
        "cutoff": cutoff,
        "nodes": [
            (key.snapshot_id, key.snapshot_version, key.snapshot_chain_id)
            for key in sorted(nodes)
        ],
        "edges": [
            (
                parent.snapshot_id,
                parent.snapshot_version,
                parent.snapshot_chain_id,
                child.snapshot_id,
                child.snapshot_version,
                child.snapshot_chain_id,
                edge_type,
            )
            for parent, child, edge_type in sorted(included_edges, key=lambda item: (item[0], item[1], item[2]))
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return tuple(episodes), fingerprint

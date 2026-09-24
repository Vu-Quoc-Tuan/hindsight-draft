"""Bounded structural shortest paths over one caller-selected relation graph.

The caller supplies relation eligibility and traversal direction. A returned
path is structural reachability, never causal or directed-dependency proof.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any


def shortest_paths_to_targets(
    adjacency: dict[str, set[str]],
    source: str,
    targets: set[str],
    *,
    max_hops: int,
) -> dict[str, list[str]]:
    """One deterministic BFS for all requested destinations up to ``max_hops``."""
    results = {source: [source]} if source in targets else {}
    pending = targets - {source}
    if not pending or source not in adjacency or max_hops < 1:
        return results
    previous: dict[str, str | None] = {source: None}
    queue: deque[tuple[str, int]] = deque([(source, 0)])
    while queue:
        node, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for neighbour in sorted(adjacency.get(node, ())):
            if neighbour in previous:
                continue
            previous[neighbour] = node
            if neighbour in pending:
                path = [neighbour]
                while previous[path[-1]] is not None:
                    path.append(previous[path[-1]])
                results[neighbour] = list(reversed(path))
                pending.remove(neighbour)
                if not pending:
                    return results
            queue.append((neighbour, depth + 1))
    return results


def shortest_path(
    adjacency: dict[str, set[str]],
    source: str,
    target: str,
    *,
    max_hops: int,
) -> list[str] | None:
    """Deterministic unweighted BFS with an inclusive hop cutoff."""
    return shortest_paths_to_targets(adjacency, source, {target}, max_hops=max_hops).get(target)


def select_path_forest(paths: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Choose deterministic real path witnesses that connect each component.

    This is a presentation projection only. Callers must keep their full path
    set for connectivity counts and quality calculations.
    """
    candidates: list[dict[str, Any]] = []
    resources: set[str] = set()
    for path in paths:
        if not isinstance(path, dict):
            continue
        nodes = path.get("path")
        source = path.get("source")
        target = path.get("target")
        relation = path.get("relation_type")
        hops = path.get("hop_count")
        if (
            not isinstance(nodes, list)
            or len(nodes) < 2
            or not all(isinstance(node, str) and node for node in nodes)
            or not isinstance(source, str)
            or not isinstance(target, str)
            or not isinstance(relation, str)
            or not relation
            or not isinstance(hops, int)
            or isinstance(hops, bool)
            or hops != len(nodes) - 1
            or nodes[0] != source
            or nodes[-1] != target
        ):
            continue
        candidates.append(path)
        resources.update((source, target))

    candidates.sort(key=lambda item: (
        item["hop_count"],
        item["source"],
        item["target"],
        item["relation_type"],
        tuple(item["path"]),
    ))
    parents = {resource: resource for resource in resources}
    ranks = {resource: 0 for resource in resources}

    def find(resource: str) -> str:
        root = resource
        while parents[root] != root:
            root = parents[root]
        while parents[resource] != root:
            parent = parents[resource]
            parents[resource] = root
            resource = parent
        return root

    forest: list[dict[str, Any]] = []
    for candidate in candidates:
        source_root = find(candidate["source"])
        target_root = find(candidate["target"])
        if source_root == target_root:
            continue
        if ranks[source_root] < ranks[target_root]:
            source_root, target_root = target_root, source_root
        parents[target_root] = source_root
        if ranks[source_root] == ranks[target_root]:
            ranks[source_root] += 1
        forest.append(candidate)
    return forest

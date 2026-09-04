"""Read-model payloads for topology navigation clients.

This module stays outside snapshot contract construction.  Its relations are
for source navigation and cannot be consumed by Explain dependency/P2 code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any

from ..data_profiles import DatasetProfile, resolve_dataset_profile
from ..loaders.topology_ip_csv import TopoIPLoader
from ..loaders.topology_it_csv import ITTopologyLoader, TopologyRelationNode
from .topology_projection import NavigationRelationEdge, TopologyTreeProjection, project_adjacency_tree, project_relation_tree


@dataclass(frozen=True)
class _CachedTopologyGraph:
    nodes: tuple[TopologyRelationNode, ...]
    edges: tuple[Any, ...]
    source_version: str


_GRAPH_CACHE: dict[tuple[str, str, tuple[tuple[str, int, int], ...]], _CachedTopologyGraph] = {}


def _mock_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _path(profile: DatasetProfile, root: Path) -> Path | None:
    return root / profile.topology_path if profile.topology_path else None


def _capability_artifact(profile: DatasetProfile, *, topology_available: bool) -> dict[str, str]:
    """Describe this profile's topology boundary without deriving it from a path.

    The artifact is deliberately independent of the navigation projection.  In
    particular, a directed *source* relation is not operational dependency
    evidence and an available raw topology never establishes an alarm mapping.
    """
    if not topology_available:
        return {"availability": "UNAVAILABLE"}
    if profile.profile_id == "IT_SERVICES":
        dependency_semantics = "UNVERIFIED"
    else:
        # IP rows state adjacency only; they do not provide dependency meaning.
        dependency_semantics = "UNAVAILABLE"
    return {
        "availability": "AVAILABLE",
        "relation_model": profile.topology_kind,
        "direction_kind": profile.direction_kind or "NONE",
        "dependency_semantics": dependency_semantics,
        "alarm_resource_mapping": profile.alarm_resource_mapping,
    }


def _content_version(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _source_signature(profile: DatasetProfile, path: Path) -> tuple[tuple[str, int, int], ...]:
    files = (path / name for name in ("service_module_server.csv", "module_database.csv", "database.csv", "storage.csv")) if profile.profile_id == "IT_SERVICES" else (path,)
    return tuple((str(file), file.stat().st_size, file.stat().st_mtime_ns) for file in files)


def _cached_graph(profile: DatasetProfile, path: Path) -> _CachedTopologyGraph:
    signature = _source_signature(profile, path)
    key = (profile.profile_id, str(path.resolve()), signature)
    cached = _GRAPH_CACHE.get(key)
    if cached is not None:
        return cached
    # A changed source must invalidate all older cached models for that profile.
    for old_key in tuple(_GRAPH_CACHE):
        if old_key[:2] == key[:2] and old_key != key:
            del _GRAPH_CACHE[old_key]
    if profile.profile_id == "IT_SERVICES":
        graph = ITTopologyLoader(path).load_graph()
        cached = _CachedTopologyGraph(graph.nodes, graph.edges, graph.source_version)
    else:
        relations = TopoIPLoader(path).load()
        source_version = _content_version(path)
        labels: dict[str, str] = {}
        adjacency: list[NavigationRelationEdge] = []
        seen_pairs: set[tuple[str, str]] = set()
        for relation in relations:
            if not relation.device_code or not relation.device_code_relation or relation.device_code == relation.device_code_relation:
                continue
            pair = tuple(sorted((relation.device_code, relation.device_code_relation)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            labels.setdefault(relation.device_code, relation.device_code)
            labels.setdefault(relation.device_code_relation, relation.device_code_relation)
            adjacency.append(NavigationRelationEdge(relation.device_code, relation.device_code_relation, "ADJACENT_TO", "topoIP.csv", source_version))
        nodes = tuple(TopologyRelationNode(resource_id, "DEVICE", label, ("topoIP.csv",)) for resource_id, label in sorted(labels.items()))  # type: ignore[arg-type]
        cached = _CachedTopologyGraph(nodes, tuple(adjacency), source_version)
    _GRAPH_CACHE[key] = cached
    return cached


def projection_payload(
    profile_id: str,
    *,
    root_id: str | None = None,
    source_root: str | Path | None = None,
    max_depth: int = 3,
    max_children: int = 50,
) -> dict[str, Any]:
    """Build the public JSON-ready tree payload for one explicit profile."""
    profile = resolve_dataset_profile(profile_id)
    base = Path(source_root) if source_root is not None else _mock_root()
    topology_path = _path(profile, base)
    if topology_path is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE",
            "profile": profile.profile_id,
            "dataset_profile": profile.profile_id,
            "topology_kind": profile.topology_kind,
            "topology": _capability_artifact(profile, topology_available=False),
        }
    if not topology_path.exists():
        return {
            "status": "UNAVAILABLE",
            "reason": "TOPOLOGY_SOURCE_FILE_MISSING",
            "profile": profile.profile_id,
            "dataset_profile": profile.profile_id,
            "topology_kind": profile.topology_kind,
            "topology": _capability_artifact(profile, topology_available=False),
            "topology_path": str(topology_path),
        }
    projection = _build_projection(profile, topology_path, root_id, max_depth, max_children)
    return {
        "status": "AVAILABLE",
        "profile": profile.profile_id,
        "dataset_profile": profile.profile_id,
        "topology_kind": profile.topology_kind,
        "direction_kind": projection.direction_kind,
        "dependency_semantics": projection.dependency_semantics,
        "topology": _capability_artifact(profile, topology_available=True),
        "semantic_notice": projection.semantic_notice,
        "source_version": projection.source_version,
        "tree": asdict(projection.root),
    }


def search_payload(
    profile_id: str,
    query: str,
    *,
    source_root: str | Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search the full normalized navigation graph without projecting it all.

    Results are resource records only. They do not imply dependency semantics;
    the client must request a bounded projection for a selected resource ID.
    """
    profile = resolve_dataset_profile(profile_id)
    base = Path(source_root) if source_root is not None else _mock_root()
    topology_path = _path(profile, base)
    if topology_path is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE",
            "dataset_profile": profile.profile_id,
            "results": [],
        }
    if not topology_path.exists():
        return {
            "status": "UNAVAILABLE",
            "reason": "TOPOLOGY_SOURCE_FILE_MISSING",
            "dataset_profile": profile.profile_id,
            "results": [],
        }
    normalized = query.strip().casefold()
    if not normalized:
        return {
            "status": "AVAILABLE",
            "dataset_profile": profile.profile_id,
            "results": [],
        }
    graph = _cached_graph(profile, topology_path)
    matches = [
        {
            "resource_id": node.resource_id,
            "resource_type": node.resource_type,
            "display_name": node.display_name,
        }
        for node in graph.nodes
        if normalized in node.resource_id.casefold()
        or normalized in node.display_name.casefold()
        or normalized in node.resource_type.casefold()
    ]
    matches.sort(
        key=lambda item: (
            item["display_name"].casefold() != normalized,
            item["display_name"].casefold(),
            item["resource_id"],
        )
    )
    return {
        "status": "AVAILABLE",
        "dataset_profile": profile.profile_id,
        "results": matches[:max(1, min(limit, 100))],
    }


def _build_projection(profile: DatasetProfile, path: Path, root_id: str | None, max_depth: int, max_children: int) -> TopologyTreeProjection:
    graph = _cached_graph(profile, path)
    if profile.profile_id == "IT_SERVICES":
        chosen = root_id or next((node.resource_id for node in graph.nodes if node.resource_type == "SERVICE"), None)
        if chosen is None:
            raise ValueError("topoIT graph contains no SERVICE node for default projection root")
        return project_relation_tree(graph.nodes, graph.edges, root_id=chosen, max_depth=max_depth, max_children=max_children)
    chosen = root_id or next((node.resource_id for node in graph.nodes), None)
    if chosen is None:
        raise ValueError("topoIP graph contains no usable adjacency node")
    return project_adjacency_tree(graph.nodes, graph.edges, root_id=chosen, max_depth=max_depth, max_children=max_children)  # type: ignore[arg-type]

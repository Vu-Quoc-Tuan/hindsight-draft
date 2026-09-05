"""Read-model payloads for topology navigation clients.

This module stays outside snapshot contract construction.  Its relations are
for source navigation and cannot be consumed by Explain dependency/P2 code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..data_profiles import DatasetProfile, resolve_dataset_profile
from ..loaders.topology_ip_csv import TopoIPLoader
from ..loaders.topology_it_csv import ITTopologyLoader, TopologyRelationNode
from .topology_projection import NavigationRelationEdge, TopologyTreeProjection, project_adjacency_tree, project_relation_tree


@dataclass(frozen=True)
class _CachedTopologyGraph:
    nodes: tuple[TopologyRelationNode, ...]
    edges: tuple[Any, ...]
    source_version: str
    aliases: Mapping[str, Any] | None
    ambiguous_aliases: frozenset[str]


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
        "navigation_mapping": profile.navigation_mapping,
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
        loader = ITTopologyLoader(path)
        graph = loader.load_graph()
        aliases, ambiguous_aliases = loader.load_aliases()
        cached = _CachedTopologyGraph(
            graph.nodes,
            graph.edges,
            graph.source_version,
            MappingProxyType(aliases),
            frozenset(ambiguous_aliases),
        )
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
        cached = _CachedTopologyGraph(nodes, tuple(adjacency), source_version, None, frozenset())
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


def resolve_navigation_payload(
    profile_id: str,
    identifier: str,
    *,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve an exact source identifier only for opening a navigation tree.

    This is intentionally separate from ``ResourceMapper`` and snapshot
    construction.  In particular, unambiguous topoIT aliases can open an IT
    record but cannot promote SOURCE_RELATION rows into P2 dependency evidence.
    """
    profile = resolve_dataset_profile(profile_id)
    base = Path(source_root) if source_root is not None else _mock_root()
    topology_path = _path(profile, base)
    raw_identifier = identifier.strip()
    if topology_path is None:
        return _navigation_unavailable(profile, raw_identifier, "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE")
    if not topology_path.exists():
        return _navigation_unavailable(profile, raw_identifier, "TOPOLOGY_SOURCE_FILE_MISSING")
    if not raw_identifier:
        return _navigation_unavailable(profile, raw_identifier, "NAVIGATION_IDENTIFIER_REQUIRED")

    graph = _cached_graph(profile, topology_path)
    resource_ids = {node.resource_id for node in graph.nodes}
    if raw_identifier in resource_ids:
        return _navigation_available(
            profile,
            raw_identifier,
            raw_identifier,
            mapping_status="EXACT_RESOURCE_ID",
            source_field="canonical_resource_id",
        )

    if profile.profile_id == "IP_NETWORK":
        # device_code is the only exact raw identity that the IP topology
        # advertises.  An interface suffix is not part of the device identity.
        device_code = raw_identifier.split("/", 1)[0].strip()
        if device_code in resource_ids:
            return _navigation_available(
                profile,
                raw_identifier,
                device_code,
                mapping_status="EXACT_IDENTITY",
                source_field="topoIP.device_code",
            )
        return _navigation_unavailable(profile, raw_identifier, "SOURCE_IDENTIFIER_NOT_FOUND")

    aliases = graph.aliases or {}
    ambiguous = graph.ambiguous_aliases
    alias_key = raw_identifier.split("/", 1)[0].strip()
    if alias_key in ambiguous:
        return _navigation_unavailable(profile, raw_identifier, "AMBIGUOUS_SOURCE_FIELD_MAPPING", mapping_status="AMBIGUOUS")
    alias = aliases.get(alias_key)
    if alias is None:
        return _navigation_unavailable(profile, raw_identifier, "SOURCE_IDENTIFIER_NOT_FOUND")
    if alias.resource_id not in resource_ids:
        # The relations and alias table must originate from the same frozen
        # topology source.  Do not open a dangling alias after malformed input.
        return _navigation_unavailable(profile, raw_identifier, "NAVIGATION_RESOURCE_NOT_PRESENT")
    return _navigation_available(
        profile,
        raw_identifier,
        alias.resource_id,
        mapping_status="UNIQUE_SOURCE_FIELD_MATCH",
        source_field=alias.verified_by,
    )


def _navigation_available(
    profile: DatasetProfile,
    identifier: str,
    resource_id: str,
    *,
    mapping_status: str,
    source_field: str,
) -> dict[str, Any]:
    return {
        "status": "AVAILABLE",
        "dataset_profile": profile.profile_id,
        "identifier": identifier,
        "resource_id": resource_id,
        "mapping_status": mapping_status,
        "source_field": source_field,
        "navigation_eligible": True,
        # IT aliases intentionally never become P2 mappings.  IP exact
        # identity is eligible for the already-existing bounded adjacency path,
        # but this endpoint itself does not enable a dependency analysis.
        "p2_mapping_eligible": profile.profile_id == "IP_NETWORK",
        "dependency_semantics": (
            "UNVERIFIED" if profile.profile_id == "IT_SERVICES" else "UNAVAILABLE"
        ),
    }


def _navigation_unavailable(
    profile: DatasetProfile,
    identifier: str,
    reason: str,
    *,
    mapping_status: str = "UNMAPPED",
) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "dataset_profile": profile.profile_id,
        "identifier": identifier,
        "resource_id": None,
        "mapping_status": mapping_status,
        "source_field": None,
        "navigation_eligible": False,
        "p2_mapping_eligible": False,
        "dependency_semantics": (
            "UNVERIFIED" if profile.profile_id == "IT_SERVICES" else "UNAVAILABLE"
        ),
        "reason": reason,
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

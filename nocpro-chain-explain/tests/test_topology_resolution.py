"""Shared mapping and structural-path contracts across P0, P2, and Overview."""

from libs.contracts.topology_mapping import resolve_resource_ids
from libs.contracts.topology_paths import (
    select_path_forest,
    shortest_path,
    shortest_paths_to_targets,
)
import nocpro_api.cohesion_advisor as cohesion_advisor
from nocpro_api.cohesion_advisor import _build_topology_connectivity


def _mapping(alarm_id: str, resource_id: str, status: str = "EXACT") -> dict:
    return {"alarm_id": alarm_id, "resource_id": resource_id, "mapping_status": status}


def test_conflicting_claim_is_not_counted_by_overview_regardless_of_order():
    rows = [
        _mapping("a1", "R1"),
        _mapping("a1", "R2"),
        _mapping("a2", "R3"),
        _mapping("a3", "R4", "AMBIGUOUS"),
    ]
    edges = [{"source_resource_id": "R1", "target_resource_id": "R3", "relation_type": "IP_ADJACENCY"}]
    for ordered in (rows, list(reversed(rows))):
        assert resolve_resource_ids(ordered) == {"a2": "R3"}
        assert resolve_resource_ids(ordered, {"a1", "a2"}, require_all=True) is None
        result = _build_topology_connectivity(
            raw_mappings=ordered,
            raw_edges=edges,
            member_ids={"a1", "a2", "a3"},
            alarm_devices={"a1": "D1", "a2": "D2", "a3": "D3"},
        )
        assert result["mapped_alarm_ids"] == {"a2"}
        assert result["mapped_device_ids"] == ["D2"]
        assert result["connected_pair_count"] == 0
        assert result["display_paths"] == []
        assert result["display_paths_truncated"] is False


def test_identical_duplicate_claims_are_harmless():
    rows = [_mapping("a1", "R1"), _mapping("a1", "R1")]
    assert resolve_resource_ids(rows, {"a1"}, require_all=True) == {"a1": "R1"}


def test_shared_bfs_is_bounded_and_deterministic():
    adjacency = {
        "A": {"C", "B"}, "B": {"A", "D"}, "C": {"A", "D"}, "D": {"B", "C", "E"}, "E": {"D"},
    }
    assert shortest_path(adjacency, "A", "D", max_hops=2) == ["A", "B", "D"]
    assert shortest_path(adjacency, "A", "E", max_hops=2) is None
    assert shortest_path(adjacency, "A", "E", max_hops=3) == ["A", "B", "D", "E"]
    assert shortest_paths_to_targets(adjacency, "A", {"D", "E", "missing"}, max_hops=3) == {
        "D": ["A", "B", "D"], "E": ["A", "B", "D", "E"],
    }


def test_display_path_forest_is_deterministic_and_not_an_all_pairs_count():
    paths = [
        {"source": "A", "target": "C", "path": ["A", "C"], "hop_count": 1, "relation_type": "IP_ADJACENCY"},
        {"source": "A", "target": "B", "path": ["A", "X", "B"], "hop_count": 2, "relation_type": "R2"},
        {"source": "B", "target": "C", "path": ["B", "C"], "hop_count": 1, "relation_type": "R1"},
        {"source": "C", "target": "D", "path": ["C", "D"], "hop_count": 1, "relation_type": "R1"},
        {"source": "A", "target": "D", "path": ["A", "D"], "hop_count": 1, "relation_type": "R3"},
        {"source": "A", "target": "invalid", "path": ["A"], "hop_count": 1, "relation_type": "R0"},
    ]

    expected = select_path_forest(paths)
    assert expected == select_path_forest(list(reversed(paths)))
    assert [(item["source"], item["target"]) for item in expected] == [
        ("A", "C"), ("A", "D"), ("B", "C"),
    ]
    assert len(expected) == 3
    assert len(paths) == 6
    assert len(expected) < len(paths)


def test_overview_path_tie_is_independent_of_edge_order():
    mappings = [_mapping("a1", "A"), _mapping("a2", "C")]
    edges = [
        {"source_resource_id": "A", "target_resource_id": "C", "relation_type": "Z_RELATION"},
        {"source_resource_id": "A", "target_resource_id": "C", "relation_type": "A_RELATION"},
    ]
    for ordered in (edges, list(reversed(edges))):
        result = _build_topology_connectivity(
            raw_mappings=mappings, raw_edges=ordered,
            member_ids={"a1", "a2"}, alarm_devices={},
        )
        assert result["paths"][0]["relation_type"] == "A_RELATION"
        assert result["connected_pair_count"] == 1
        assert result["display_paths"] == result["paths"]
        assert result["display_paths_truncated"] is False


def test_overview_display_path_cap_does_not_change_connectivity_counts(monkeypatch):
    monkeypatch.setattr(cohesion_advisor, "MAX_OVERVIEW_DISPLAY_PATHS", 2)
    resources = ["A", "B", "C", "D"]
    result = _build_topology_connectivity(
        raw_mappings=[
            _mapping(f"a{index}", resource)
            for index, resource in enumerate(resources)
        ],
        raw_edges=[
            {
                "source_resource_id": source,
                "target_resource_id": target,
                "relation_type": "IP_ADJACENCY",
            }
            for index, source in enumerate(resources)
            for target in resources[index + 1:]
        ],
        member_ids={f"a{index}" for index in range(len(resources))},
        alarm_devices={},
    )

    assert len(result["paths"]) == 6
    assert result["connected_pair_count"] == 6
    assert result["pair_total"] == 6
    assert len(result["display_paths"]) == 2
    assert result["display_paths_truncated"] is True

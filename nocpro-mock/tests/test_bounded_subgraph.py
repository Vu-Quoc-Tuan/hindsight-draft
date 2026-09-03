"""Unit tests for bounded subgraph extraction."""

from __future__ import annotations

from nocpro_mock.loaders.topology_ip_csv import TopoIPRelation
from nocpro_mock.normalize.bounded_subgraph import extract_bounded_ip_subgraph


def _rel(rel_id: str, d1: str, d2: str) -> TopoIPRelation:
    return TopoIPRelation(
        relation_id=rel_id,
        device_code=d1,
        device_code_relation=d2,
        raw={},
    )


def test_empty_seeds_returns_empty_tuple() -> None:
    relations = [
        _rel("1", "R1", "R2"),
        _rel("2", "R2", "R3"),
    ]
    assert extract_bounded_ip_subgraph(relations, []) == ()
    assert extract_bounded_ip_subgraph(relations, [None, ""]) == ()


def test_1hop_extraction_extracts_seed_and_neighbors() -> None:
    relations = [
        _rel("1", "CORE_1", "AGG_1"),
        _rel("2", "AGG_1", "ACCESS_1"),
        _rel("3", "CORE_2", "AGG_2"),
        _rel("4", "AGG_2", "ACCESS_2"),
    ]

    # Seed is AGG_1 -> 1-hop should include relation 1 and 2, but NOT relation 3 or 4
    extracted = extract_bounded_ip_subgraph(relations, ["AGG_1"], max_hops=1)
    extracted_ids = {r.relation_id for r in extracted}
    assert extracted_ids == {"1", "2"}


def test_max_relations_ceiling() -> None:
    relations = [
        _rel("1", "CORE_1", "AGG_1"),
        _rel("2", "CORE_1", "AGG_2"),
        _rel("3", "CORE_1", "AGG_3"),
    ]
    extracted = extract_bounded_ip_subgraph(relations, ["CORE_1"], max_relations=2)
    assert len(extracted) == 2

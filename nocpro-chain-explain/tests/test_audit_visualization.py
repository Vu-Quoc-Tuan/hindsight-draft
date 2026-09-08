from __future__ import annotations

from random import Random

from audit import (
    AuditEdge,
    AuditGraph,
    AuditVerdict,
    Candidate,
    CandidateSource,
    ConductanceResult,
    ScoredCandidate,
    StructuralAuditResult,
    StructuralRole,
    StructuralRoleResult,
)
from tier2.audit_visualization import (
    AUDIT_VISUALIZATION_MAX_EDGES,
    AUDIT_VISUALIZATION_MAX_NODES,
    AUDIT_VISUALIZATION_VERSION,
    build_audit_visualization,
)


def _graph(members: list[str], weighted_edges: list[tuple[str, str, float]]) -> AuditGraph:
    adjacency: dict[str, dict[str, float]] = {member: {} for member in members}
    edges = []
    for left, right, weight in weighted_edges:
        edges.append(AuditEdge(left, right, weight, ("temporal", "entity")))
        adjacency[left][right] = weight
        adjacency[right][left] = weight
    return AuditGraph(tuple(members), tuple(edges), adjacency)


def _audit(chain_id: str, side_a: set[str] | None) -> StructuralAuditResult:
    if side_a is None:
        return StructuralAuditResult(
            chain_id=chain_id,
            verdict=AuditVerdict.NO_LOW_CONDUCTANCE_CUT,
            best_cut=None,
            scored_candidates=(),
            epsilon=0.2,
            reason="no eligible low-conductance cut",
        )
    cut = ScoredCandidate(
        candidate=Candidate(
            source=CandidateSource.DESCRIPTOR,
            members=frozenset(side_a),
            label="fixture-cut",
        ),
        conductance=ConductanceResult(
            label="fixture-cut",
            size_s=len(side_a),
            size_complement=len(side_a),
            phi=0.1,
            feasible=True,
            reason=None,
        ),
    )
    return StructuralAuditResult(
        chain_id=chain_id,
        verdict=AuditVerdict.CANDIDATE_SPLIT,
        best_cut=cut,
        scored_candidates=(cut,),
        epsilon=0.2,
        reason="fixture",
    )


def _roles(members: list[str]) -> dict[str, StructuralRoleResult]:
    return {
        member: StructuralRoleResult(
            alarm_id=member,
            role=StructuralRole.NON_CONNECTOR,
            is_articulation_point=False,
            blocks_supported=1,
            reason="fixture",
        )
        for member in members
    }


def test_small_projection_retains_exact_nodes_edges_and_empty_graph_is_available() -> None:
    members = ["A", "B", "C"]
    graph = _graph(members, [("B", "A", 0.8), ("B", "C", 0.4)])
    result = build_audit_visualization(graph, _audit("C1", {"A"}), _roles(members))

    assert result.status == "AVAILABLE"
    assert result.projection_version == AUDIT_VISUALIZATION_VERSION
    assert [node.alarm_id for node in result.nodes] == ["A", "B", "C"]
    assert [(edge.source_alarm_id, edge.target_alarm_id) for edge in result.edges] == [
        ("A", "B"),
        ("B", "C"),
    ]
    assert result.edges[0].crosses_best_cut is True
    assert result.total_node_count == result.shown_node_count == 3
    assert result.total_edge_count == result.shown_edge_count == 2
    assert result.truncated is False

    empty = build_audit_visualization(
        _graph(members, []), _audit("C1", None), _roles(members)
    )
    assert empty.status == "AVAILABLE"
    assert len(empty.nodes) == 3
    assert empty.edges == ()
    assert empty.total_edge_count == 0


def test_projection_is_capped_balanced_and_deterministic_under_input_reordering() -> None:
    members = [f"A{i:03d}" for i in range(50)] + [f"B{i:03d}" for i in range(50)]
    weighted_edges = [
        (left, right, 1.0 - (index / 20_000))
        for index, (left, right) in enumerate(
            (pair for offset, left in enumerate(members) for pair in ((left, right) for right in members[offset + 1 :]))
        )
    ]
    audit = _audit("C1", set(members[:50]))
    first = build_audit_visualization(
        _graph(members, weighted_edges), audit, _roles(members)
    )

    assert len(first.nodes) == AUDIT_VISUALIZATION_MAX_NODES == 80
    assert len(first.edges) == AUDIT_VISUALIZATION_MAX_EDGES == 160
    assert sum(node.cut_side == "A" for node in first.nodes) == 40
    assert sum(node.cut_side == "B" for node in first.nodes) == 40
    selected = {node.alarm_id for node in first.nodes}
    assert all(
        edge.source_alarm_id in selected and edge.target_alarm_id in selected
        for edge in first.edges
    )
    assert all(edge.source_alarm_id < edge.target_alarm_id for edge in first.edges)
    assert first.hidden_node_count == 20
    assert first.hidden_edge_count == len(weighted_edges) - 160
    assert first.truncated is True

    shuffled_members = list(members)
    shuffled_edges = list(weighted_edges)
    Random(7).shuffle(shuffled_members)
    Random(11).shuffle(shuffled_edges)
    second = build_audit_visualization(
        _graph(shuffled_members, shuffled_edges), audit, _roles(members)
    )
    assert second == first

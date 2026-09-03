from __future__ import annotations

from nocpro_mock.loaders.topology_it_csv import TopologyRelationEdge, TopologyRelationNode
from nocpro_mock.ui.topology_projection import project_relation_tree


def _node(resource_id: str, resource_type: str) -> TopologyRelationNode:
    return TopologyRelationNode(resource_id, resource_type, resource_id, ("fixture.csv",))  # type: ignore[arg-type]


def _edge(source: str, target: str, relation: str = "SERVICE_HAS_MODULE") -> TopologyRelationEdge:
    return TopologyRelationEdge(source, target, relation, "SOURCE_RELATION", "UNVERIFIED", "fixture.csv", "fixture-v1")  # type: ignore[arg-type]


def test_projection_stops_cycle_with_non_expandable_reference() -> None:
    projection = project_relation_tree(
        (_node("it:service:s1", "SERVICE"), _node("it:module:m1", "MODULE"), _node("it:database:d1", "DATABASE")),
        (_edge("it:service:s1", "it:module:m1"), _edge("it:module:m1", "it:database:d1", "MODULE_LINKS_DATABASE"), _edge("it:database:d1", "it:service:s1", "DATABASE_LINKS_SERVICE")),
        root_id="it:service:s1",
    )

    cycle = projection.root.children[0].children[0].children[0]
    assert cycle.reference_kind == "CYCLE"
    assert cycle.expandable is False
    assert cycle.resource_id == "it:service:s1"


def test_projection_uses_one_primary_occurrence_and_reference_for_second_parent() -> None:
    projection = project_relation_tree(
        (_node("it:service:s1", "SERVICE"), _node("it:module:m1", "MODULE"), _node("it:module:m2", "MODULE"), _node("it:database:d1", "DATABASE")),
        (_edge("it:service:s1", "it:module:m1"), _edge("it:service:s1", "it:module:m2"), _edge("it:module:m1", "it:database:d1", "MODULE_LINKS_DATABASE"), _edge("it:module:m2", "it:database:d1", "MODULE_LINKS_DATABASE")),
        root_id="it:service:s1",
    )

    first, second = projection.root.children
    assert first.children[0].reference_kind is None
    assert second.children[0].reference_kind == "MULTI_PARENT"
    assert second.children[0].linked_parent_count == 1


def test_projection_reports_hidden_children_under_bound() -> None:
    root = _node("it:service:s1", "SERVICE")
    modules = tuple(_node(f"it:module:m{i}", "MODULE") for i in range(3))
    projection = project_relation_tree(
        (root, *modules),
        tuple(_edge(root.resource_id, module.resource_id) for module in modules),
        root_id=root.resource_id,
        max_children=2,
    )

    assert len(projection.root.children) == 2
    assert projection.root.hidden_child_count == 1

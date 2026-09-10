"""Unit tests for topology tree projection engine."""

from __future__ import annotations

import pytest

from nocpro_api.topology.engine import (
    NavigationRelationEdge,
    TopologyNodeItem,
    project_adjacency_tree,
    project_relation_tree,
)


def test_project_relation_tree_hierarchy() -> None:
    nodes = [
        TopologyNodeItem("svc1", "SERVICE", "Payment Service"),
        TopologyNodeItem("mod1", "MODULE", "Payment Gateway"),
        TopologyNodeItem("inst1", "INSTANCE", "PG Instance 01"),
    ]
    edges = [
        NavigationRelationEdge("svc1", "mod1", "SERVICE_HAS_MODULE", "service_module.csv"),
        NavigationRelationEdge("mod1", "inst1", "MODULE_HAS_INSTANCE", "module_server.csv"),
    ]

    proj = project_relation_tree(nodes, edges, root_id="svc1", max_depth=3)
    assert proj.direction_kind == "SOURCE_RELATION"
    assert proj.dependency_semantics == "UNVERIFIED"
    assert "navigation" in proj.semantic_notice.lower()
    assert proj.root.resource_id == "svc1"
    assert len(proj.root.children) == 1

    mod_node = proj.root.children[0]
    assert mod_node.resource_id == "mod1"
    assert len(mod_node.children) == 1

    inst_node = mod_node.children[0]
    assert inst_node.resource_id == "inst1"
    assert len(inst_node.children) == 0


def test_project_relation_tree_stops_cycle() -> None:
    nodes = [
        TopologyNodeItem("n1", "MODULE", "Node 1"),
        TopologyNodeItem("n2", "MODULE", "Node 2"),
    ]
    edges = [
        NavigationRelationEdge("n1", "n2", "MODULE_LINKS_MODULE"),
        NavigationRelationEdge("n2", "n1", "MODULE_LINKS_MODULE"),
    ]

    proj = project_relation_tree(nodes, edges, root_id="n1", max_depth=4)
    child = proj.root.children[0]
    assert child.resource_id == "n2"
    assert len(child.children) == 1
    cycle_node = child.children[0]
    assert cycle_node.resource_id == "n1"
    assert cycle_node.reference_kind == "CYCLE"
    assert not cycle_node.expandable


def test_project_relation_tree_multi_parent() -> None:
    nodes = [
        TopologyNodeItem("svc1", "SERVICE", "Service 1"),
        TopologyNodeItem("mod1", "MODULE", "Module 1"),
        TopologyNodeItem("mod2", "MODULE", "Module 2"),
        TopologyNodeItem("shared_db", "DATABASE", "Shared DB"),
    ]
    edges = [
        NavigationRelationEdge("svc1", "mod1", "SERVICE_HAS_MODULE"),
        NavigationRelationEdge("svc1", "mod2", "SERVICE_HAS_MODULE"),
        NavigationRelationEdge("mod1", "shared_db", "MODULE_LINKS_DATABASE"),
        NavigationRelationEdge("mod2", "shared_db", "MODULE_LINKS_DATABASE"),
    ]

    proj = project_relation_tree(nodes, edges, root_id="svc1", max_depth=3)
    mod1_node = proj.root.children[0]
    mod2_node = proj.root.children[1]

    # One child renders the full node, second renders MULTI_PARENT reference
    db1 = mod1_node.children[0]
    db2 = mod2_node.children[0]
    assert {db1.reference_kind, db2.reference_kind} == {None, "MULTI_PARENT"}


def test_project_adjacency_tree_undirected() -> None:
    nodes = [
        TopologyNodeItem("dev1", "DEVICE", "Switch A"),
        TopologyNodeItem("dev2", "DEVICE", "Switch B"),
    ]
    edges = [
        NavigationRelationEdge("dev1", "dev2", "ADJACENT_TO", "topoIP.csv"),
    ]

    proj = project_adjacency_tree(nodes, edges, root_id="dev1", max_depth=2)
    assert proj.direction_kind == "NONE"
    assert proj.dependency_semantics == "UNAVAILABLE"
    assert proj.root.resource_id == "dev1"
    assert len(proj.root.children) == 1
    assert proj.root.children[0].resource_id == "dev2"

    # Also projects starting from dev2 backwards across the undirected edge
    proj2 = project_adjacency_tree(nodes, edges, root_id="dev2", max_depth=2)
    assert proj2.root.resource_id == "dev2"
    assert len(proj2.root.children) == 1
    assert proj2.root.children[0].resource_id == "dev1"

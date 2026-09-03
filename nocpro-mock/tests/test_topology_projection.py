from __future__ import annotations

import csv
import json
from contextlib import redirect_stdout
from io import StringIO
from urllib.request import urlopen

from nocpro_mock.loaders.topology_it_csv import TopologyRelationEdge, TopologyRelationNode
from nocpro_mock.ui.topology_projection import project_relation_tree
from nocpro_mock.ui.topology_api import projection_payload
from nocpro_mock.ui.server import start_topology_server_in_thread
from nocpro_mock.cli import main


def _node(resource_id: str, resource_type: str) -> TopologyRelationNode:
    return TopologyRelationNode(resource_id, resource_type, resource_id, ("fixture.csv",))  # type: ignore[arg-type]


def _edge(source: str, target: str, relation: str = "SERVICE_HAS_MODULE") -> TopologyRelationEdge:
    return TopologyRelationEdge(source, target, relation, "SOURCE_RELATION", "UNVERIFIED", "fixture.csv", "fixture-v1")  # type: ignore[arg-type]


def _write_csv(path, headers, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _write_minimal_topoit(root) -> None:
    _write_csv(root / "service_module_server.csv", ["service_id", "module_id", "instance_id"], [{"service_id": "s1", "module_id": "m1", "instance_id": "i1"}])
    _write_csv(root / "module_database.csv", ["module_id", "database_id"], [{"module_id": "m1", "database_id": "d1"}])
    _write_csv(root / "database.csv", ["database_id", "service_id", "instance_id"], [{"database_id": "d1", "service_id": "s1", "instance_id": "i1"}])
    _write_csv(root / "storage.csv", ["storage_name", "instance_id"], [{"storage_name": "st1", "instance_id": "i1"}])


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


def test_alarm_only_profile_is_explicitly_unavailable() -> None:
    payload = projection_payload("ALARM_ONLY")
    assert payload["status"] == "UNAVAILABLE"
    assert payload["reason"] == "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE"


def test_it_profile_payload_keeps_source_relation_boundary(tmp_path) -> None:
    topology_root = tmp_path / "datasets" / "raw" / "topo" / "topoIT"
    _write_minimal_topoit(topology_root)
    payload = projection_payload("IT_SERVICES", source_root=tmp_path)
    assert payload["status"] == "AVAILABLE"
    assert payload["direction_kind"] == "SOURCE_RELATION"
    assert payload["dependency_semantics"] == "UNVERIFIED"


def test_cli_emits_alarm_only_unavailable_payload() -> None:
    output = StringIO()
    with redirect_stdout(output):
        assert main(["topology-tree", "--profile", "ALARM_ONLY"]) == 0
    payload = json.loads(output.getvalue())
    assert payload["status"] == "UNAVAILABLE"


def test_adjacency_projection_deduplicates_repeated_endpoint_pairs(monkeypatch, tmp_path) -> None:
    from nocpro_mock.data_profiles import DatasetProfile
    from nocpro_mock.ui import topology_api

    profile = DatasetProfile("IP_NETWORK", "fixture", "alarm.csv", "topo.csv", "UNDIRECTED_ADJACENCY", "NONE", "UNVERIFIED")
    monkeypatch.setattr(topology_api, "resolve_dataset_profile", lambda _: profile)
    topo = tmp_path / "topo.csv"
    topo.write_text(
        "id,device_code,device_code_relation,network_class_name,network_class_name_relation,interface_port,interface_port_relation,update_time_vipa\n"
        "1,A,B,,,p1,p2,\n2,A,B,,,p3,p4,\n",
        encoding="utf-8",
    )
    payload = topology_api.projection_payload("IP_NETWORK", source_root=tmp_path, max_depth=1)
    assert [child["resource_id"] for child in payload["tree"]["children"]] == ["B"]
    assert payload["source_version"].startswith("sha256:")


def test_projection_reuses_cached_graph_until_source_signature_changes(monkeypatch, tmp_path) -> None:
    from nocpro_mock.ui import topology_api
    from nocpro_mock.data_profiles import DatasetProfile

    profile = DatasetProfile("IP_NETWORK", "fixture", "alarm.csv", "topo.csv", "UNDIRECTED_ADJACENCY", "NONE", "UNVERIFIED")
    monkeypatch.setattr(topology_api, "resolve_dataset_profile", lambda _: profile)
    topology_api._GRAPH_CACHE.clear()
    topo = tmp_path / "topo.csv"
    topo.write_text("id,device_code,device_code_relation,network_class_name,network_class_name_relation,interface_port,interface_port_relation,update_time_vipa\n1,A,B,,,,,\n", encoding="utf-8")
    calls = 0
    original = topology_api.TopoIPLoader.load
    def counted_load(loader):
        nonlocal calls
        calls += 1
        return original(loader)
    monkeypatch.setattr(topology_api.TopoIPLoader, "load", counted_load)
    topology_api.projection_payload("IP_NETWORK", source_root=tmp_path)
    topology_api.projection_payload("IP_NETWORK", source_root=tmp_path)
    assert calls == 1


def test_read_only_topology_http_endpoint_requires_profile_id() -> None:
    server, base = start_topology_server_in_thread()
    try:
        with urlopen(f"{base}/api/topology/projection?profile_id=ALARM_ONLY") as response:  # noqa: S310 - local test server
            payload = json.loads(response.read())
        assert payload["status"] == "UNAVAILABLE"
        assert payload["reason"] == "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE"
    finally:
        server.shutdown()
        server.server_close()

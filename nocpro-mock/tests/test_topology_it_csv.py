from __future__ import annotations

import csv
from pathlib import Path

from nocpro_mock.data_profiles import resolve_dataset_profile
from nocpro_mock.loaders.topology_it_csv import ITTopologyLoader


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _write_topology(root: Path) -> Path:
    _write_csv(
        root / "service_module_server.csv",
        ["service_id", "service_name", "module_id", "module_name", "instance_id", "instance_ip"],
        [{"service_id": "s1", "service_name": "Billing", "module_id": "m1", "module_name": "API", "instance_id": "i1", "instance_ip": "10.0.0.1"}],
    )
    _write_csv(
        root / "module_database.csv",
        ["module_id", "database_id"],
        [{"module_id": "m1", "database_id": "d1"}],
    )
    _write_csv(
        root / "database.csv",
        ["database_id", "database_name", "service_id", "service_name", "instance_id", "instance_ip"],
        [{"database_id": "d1", "database_name": "orders", "service_id": "s1", "service_name": "Billing", "instance_id": "i2", "instance_ip": "10.0.0.2"}],
    )
    _write_csv(
        root / "storage.csv",
        ["storage_name", "instance_id", "instance_ip"],
        [{"storage_name": "store-a", "instance_id": "i2", "instance_ip": "10.0.0.2"}],
    )
    return root


def test_loader_normalizes_namespace_nodes_and_typed_source_relations(tmp_path: Path) -> None:
    graph = ITTopologyLoader(_write_topology(tmp_path / "topoIT")).load_graph()

    assert {node.resource_id for node in graph.nodes} >= {
        "it:service:s1", "it:module:m1", "it:instance:i1", "it:database:d1", "it:storage:store-a"
    }
    assert {(edge.relation_type, edge.direction_kind) for edge in graph.edges} == {
        ("SERVICE_HAS_MODULE", "SOURCE_RELATION"),
        ("MODULE_HAS_INSTANCE", "SOURCE_RELATION"),
        ("MODULE_LINKS_DATABASE", "SOURCE_RELATION"),
        ("DATABASE_LINKS_SERVICE", "SOURCE_RELATION"),
        ("DATABASE_LINKS_INSTANCE", "SOURCE_RELATION"),
        ("INSTANCE_LINKS_STORAGE", "SOURCE_RELATION"),
    }
    assert {edge.dependency_semantics for edge in graph.edges} == {"UNVERIFIED"}


def test_loader_rejects_incomplete_required_source_schema(tmp_path: Path) -> None:
    root = tmp_path / "topoIT"
    _write_csv(root / "service_module_server.csv", ["service_id"], [{"service_id": "s1"}])

    loader = ITTopologyLoader(root)
    try:
        loader.load_graph()
    except ValueError as exc:
        assert "service_module_server.csv" in str(exc)
        assert "module_id" in str(exc)
    else:
        raise AssertionError("incomplete schema must fail closed")


def test_real_data_profiles_keep_alarm_and_topology_sources_paired() -> None:
    alarm_only = resolve_dataset_profile("ALARM_ONLY")
    ip = resolve_dataset_profile("IP_NETWORK")
    it = resolve_dataset_profile("IT_SERVICES")

    assert alarm_only.topology_kind == "UNAVAILABLE"
    assert ip.alarm_csv.endswith("datasets/raw/alarm/alarmIP.csv")
    assert ip.topology_path.endswith("datasets/raw/topo/topoIP.csv")
    assert ip.topology_kind == "UNDIRECTED_ADJACENCY"
    assert it.alarm_csv.endswith("datasets/raw/alarm/alarmIT.csv")
    assert it.topology_path.endswith("datasets/raw/topo/topoIT")
    assert it.topology_kind == "DIRECTED_SOURCE_RELATIONS"

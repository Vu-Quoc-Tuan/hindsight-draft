"""Unit tests for Kafka topology wire publisher and batch chunking."""

from __future__ import annotations

from pathlib import Path

from nocpro_mock.producer.kafka_topology import (
    KafkaTopologyConfig,
    build_ip_topology_payload,
    build_it_topology_payload,
    build_topology_wire_batch,
)


def test_ip_topology_payload_and_strict_metadata(tmp_path: Path):
    topo_csv = tmp_path / "topoIP.csv"
    topo_csv.write_text("device_code,device_code_relation,source_class\nDEV_A,DEV_B,SITE_ROUTER\nDEV_B,DEV_C,SITE_ROUTER\n")

    payload = build_ip_topology_payload(topo_csv)
    assert payload["profile_id"] == "IP_NETWORK"
    assert payload["relation_model"] == "PHYSICAL_ADJACENCY"
    assert payload["direction_kind"] == "NONE"
    assert payload["dependency_semantics"] == "UNAVAILABLE"
    assert payload["navigation_eligible"] is True
    assert payload["p2_eligible"] is False  # Strict methodology invariant!

    assert len(payload["nodes"]) == 3
    assert len(payload["edges"]) == 2
    assert payload["edges"][0]["relation_type"] == "ADJACENT_TO"


def test_it_topology_payload_and_strict_metadata(tmp_path: Path):
    it_dir = tmp_path / "topoIT"
    it_dir.mkdir()
    (it_dir / "service_module_server.csv").write_text("service_id,service_name,module_id,module_name,instance_id,server_id,ip\nsvc1,Service 1,mod1,Module 1,inst1,srv1,10.0.0.1\n")
    (it_dir / "module_database.csv").write_text("module_id,database_id\nmod1,db1\n")
    (it_dir / "database.csv").write_text("database_id,service_id,instance_id\ndb1,svc1,inst1\n")
    (it_dir / "storage.csv").write_text("instance_id,storage_name\ninst1,stor1\n")

    payload = build_it_topology_payload(it_dir)
    assert payload["profile_id"] == "IT_SERVICES"
    assert payload["relation_model"] == "SOURCE_RELATION"
    assert payload["direction_kind"] == "SOURCE_RELATION"
    assert payload["dependency_semantics"] == "UNVERIFIED"
    assert payload["navigation_eligible"] is True
    assert payload["p2_eligible"] is False  # Strict methodology invariant!

    assert len(payload["nodes"]) > 0
    assert len(payload["edges"]) > 0
    assert len(payload["alias_resolution"]) > 0


def test_topology_wire_batch_chunking():
    payload = {
        "profile_id": "TEST_PROFILE",
        "topology_version": "test-v1",
        "source_version": "sha256:dummy",
        "relation_model": "SOURCE_RELATION",
        "direction_kind": "SOURCE_RELATION",
        "dependency_semantics": "UNVERIFIED",
        "navigation_eligible": True,
        "p2_eligible": False,
        "nodes": [{"resource_id": f"node_{i}", "resource_type": "SERVICE", "display_name": f"Node {i}"} for i in range(5000)],
        "edges": [{"source_id": f"node_{i}", "target_id": f"node_{i+1}", "relation_type": "CONNECTS"} for i in range(4999)],
        "alias_resolution": [{"alias_key": f"alias_{i}", "status": "UNIQUE", "unique_resource_id": f"node_{i}", "verified_by": "test"} for i in range(100)],
    }

    # Small chunk target to trigger multiple chunks
    cfg = KafkaTopologyConfig(chunk_target_bytes=5000)
    batch = build_topology_wire_batch(payload, config=cfg)

    assert len(batch.chunks) > 1
    assert batch.complete["event_type"] == "TOPOLOGY_COMPLETE"
    assert batch.complete["chunk_count"] == len(batch.chunks)
    assert batch.complete["node_count"] == 5000
    assert batch.complete["edge_count"] == 4999
    assert batch.complete["alias_count"] == 100
    assert batch.complete["p2_eligible"] is False

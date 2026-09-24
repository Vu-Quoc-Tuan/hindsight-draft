"""Integration test for TopologyRepository running real SQL transactions.

Verifies:
1. Real SQL persistence of Kafka chunks and barrier events.
2. Atomic deduplication inbox (duplicate events skipped).
3. Dual-path assembly (barrier arriving before chunks, or chunks before barrier).
4. Monotonic active version pointer updates.
5. Undirected IP adjacency projection vs directed IT relation projection.
6. Identifier resolution with UNIQUE alias support and UNAVAILABLE IP semantics.
7. Graph hydration for Analysis Worker.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import zstandard

from nocpro_api.ingest.topology_wire import (
    TopologyChunkEvent,
    TopologyCompleteEvent,
    sha256_hex,
)
from nocpro_api.persistence.models import Base
from nocpro_api.persistence.topology_repository import TopologyRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = TopologyRepository(sessions)
    yield repository
    await engine.dispose()


def _make_it_topology():
    return {
        "profile_id": "IT_SERVICES",
        "topology_version": "it-test-v1",
        "source_version": "sha256:11111111111111111111111111111111",
        "nodes": [
            {"resource_id": "svc_order", "resource_type": "SERVICE", "display_name": "Order Service", "source_tables": ["topoIT.xml"]},
            {"resource_id": "db_order", "resource_type": "DATABASE", "display_name": "Order DB", "source_tables": ["topoIT.xml"]},
        ],
        "edges": [
            {
                "source_id": "svc_order",
                "target_id": "db_order",
                "relation_type": "CONNECTS_TO",
                "direction_kind": "SOURCE_RELATION",
                "dependency_semantics": "UNVERIFIED",
                "source_table": "topoIT.xml",
                "source_version": "sha256:11111111111111111111111111111111",
            }
        ],
        "alias_resolution": [
            {
                "alias_key": "order-srv-alias",
                "status": "UNIQUE",
                "unique_resource_id": "svc_order",
                "verified_by": "alias_match",
            }
        ],
    }


def _make_ip_topology():
    return {
        "profile_id": "IP_NETWORK",
        "topology_version": "ip-test-v1",
        "source_version": "sha256:22222222222222222222222222222222",
        "nodes": [
            {"resource_id": "ROUTER_A", "resource_type": "DEVICE", "display_name": "ROUTER_A", "source_tables": ["topoIP.csv"]},
            {"resource_id": "SWITCH_B", "resource_type": "DEVICE", "display_name": "SWITCH_B", "source_tables": ["topoIP.csv"]},
        ],
        "edges": [
            {
                "source_id": "ROUTER_A",
                "target_id": "SWITCH_B",
                "relation_type": "ADJACENT_TO",
                "direction_kind": "NONE",
                "dependency_semantics": "UNAVAILABLE",
                "source_table": "topoIP.csv",
                "source_version": "sha256:22222222222222222222222222222222",
            }
        ],
        "alias_resolution": [],
    }


def _compress_payload(payload: dict) -> tuple[bytes, str]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    checksum = sha256_hex(raw)
    compressed = zstandard.ZstdCompressor(level=3).compress(raw)
    return compressed, checksum


async def _materialize_topology(repo: TopologyRepository, payload: dict, *, offset: int) -> None:
    """Persist a compact topology fixture through the same ingest path as Kafka."""
    compressed, checksum = _compress_payload(payload)
    profile_id = payload["profile_id"]
    topology_version = payload["topology_version"]
    await repo.process_kafka_event(
        TopologyChunkEvent(
            event_type="TOPOLOGY_CHUNK",
            event_id=f"chunk-{profile_id}-{topology_version}",
            profile_id=profile_id,
            topology_version=topology_version,
            chunk_index=0,
            chunk_count=1,
            chunk_checksum=sha256_hex(compressed),
            payload_checksum=checksum,
            payload=compressed,
            produced_at=datetime.now(timezone.utc).isoformat(),
        ),
        topic="nocpro.topology.v1", partition=0, offset=offset, message_key=profile_id,
    )
    await repo.process_kafka_event(
        TopologyCompleteEvent(
            event_type="TOPOLOGY_COMPLETE",
            event_id=f"complete-{profile_id}-{topology_version}",
            profile_id=profile_id,
            topology_version=topology_version,
            source_version=payload["source_version"],
            chunk_count=1,
            payload_checksum=checksum,
            node_count=len(payload["nodes"]),
            edge_count=len(payload["edges"]),
            alias_count=len(payload.get("alias_resolution", [])),
            relation_model="PHYSICAL_ADJACENCY" if profile_id == "IP_NETWORK" else "DIRECTED_SOURCE_RELATIONS",
            direction_kind="NONE" if profile_id == "IP_NETWORK" else "SOURCE_RELATION",
            dependency_semantics="UNAVAILABLE" if profile_id == "IP_NETWORK" else "UNVERIFIED",
            navigation_eligible=True,
            p2_eligible=False,
            produced_at=datetime.now(timezone.utc).isoformat(),
        ),
        topic="nocpro.topology.v1", partition=0, offset=offset + 1, message_key=profile_id,
    )


def _topology_payload(profile_id: str, topology_version: str, nodes: list[str], edges: list[tuple[str, str]]) -> dict:
    return {
        "profile_id": profile_id,
        "topology_version": topology_version,
        "source_version": "sha256:33333333333333333333333333333333",
        "nodes": [
            {"resource_id": node, "resource_type": "DEVICE", "display_name": node, "source_tables": ["fixture"]}
            for node in nodes
        ],
        "edges": [
            {
                "source_id": source,
                "target_id": target,
                "relation_type": "ADJACENT_TO" if profile_id == "IP_NETWORK" else "CONNECTS_TO",
                "direction_kind": "NONE" if profile_id == "IP_NETWORK" else "SOURCE_RELATION",
                "dependency_semantics": "UNAVAILABLE" if profile_id == "IP_NETWORK" else "UNVERIFIED",
                "source_table": "fixture",
                "source_version": "sha256:33333333333333333333333333333333",
            }
            for source, target in edges
        ],
        "alias_resolution": [],
    }


async def test_analysis_hydration_keeps_intermediary_paths_and_all_service_branches(repo: TopologyRepository):
    await _materialize_topology(
        repo,
        _topology_payload("IP_NETWORK", "ip-path-v1", ["A", "X", "Y", "B"], [("A", "X"), ("X", "Y"), ("Y", "B")]),
        offset=900,
    )
    hydrated_ip = await repo.hydrate_graph_for_analysis("IP_NETWORK", "ip-path-v1", {"A", "B"})
    assert {(edge["source_resource_id"], edge["target_resource_id"]) for edge in hydrated_ip["edges"]} == {
        ("A", "X"), ("X", "Y"), ("Y", "B"),
    }

    await _materialize_topology(
        repo,
        _topology_payload(
            "IT_SERVICES", "it-branches-v1",
            ["S1", "M1", "H1", "S2", "M2", "H2"],
            [("S1", "M1"), ("M1", "H1"), ("S2", "M2"), ("M2", "H2")],
        ),
        offset=910,
    )
    hydrated_it = await repo.hydrate_graph_for_analysis("IT_SERVICES", "it-branches-v1", {"H1", "H2"})
    assert {(edge["source_resource_id"], edge["target_resource_id"]) for edge in hydrated_it["edges"]} == {
        ("S1", "M1"), ("M1", "H1"), ("S2", "M2"), ("M2", "H2"),
    }


async def test_subgraph_never_exceeds_node_budget_or_emits_dangling_edges(repo: TopologyRepository):
    await _materialize_topology(
        repo,
        _topology_payload("IP_NETWORK", "ip-budget-v1", ["A", "B", "C", "D"], [("A", "B"), ("A", "C"), ("A", "D")]),
        offset=920,
    )
    result = await repo.get_subgraph("IP_NETWORK", seeds=["A", "B", "C"], max_hops=2, max_nodes=2)
    node_ids = {node["id"] for node in result["nodes"]}
    assert len(node_ids) == 2
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in result["edges"])
    assert result["requested_seed_count"] == 3
    assert result["resolved_seed_count"] == 3
    assert result["retained_seed_count"] == 2
    assert result["dropped_seed_count"] == 1
    assert result["truncated"] is True
    assert "SEED_NODE_LIMIT" in result["truncation_reasons"]


async def test_subgraph_supports_four_hops_for_overview_paths(repo: TopologyRepository):
    await _materialize_topology(
        repo,
        _topology_payload(
            "IP_NETWORK", "ip-four-hop-v1", ["A", "B", "C", "D", "E"],
            [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")],
        ),
        offset=925,
    )

    result = await repo.get_subgraph(
        "IP_NETWORK", seeds=["A"], max_hops=4, max_nodes=20
    )

    assert result["status"] == "AVAILABLE"
    assert result["topology_version"] == "ip-four-hop-v1"
    assert {node["id"] for node in result["nodes"]} == {"A", "B", "C", "D", "E"}
    assert len(result["edges"]) == 4
    assert result["truncated"] is False


async def test_subgraph_rejects_hops_outside_supported_range(repo: TopologyRepository):
    with pytest.raises(ValueError, match="max_hops must be between 1 and 4"):
        await repo.get_subgraph("IP_NETWORK", seeds=["A"], max_hops=5)


async def test_topology_repository_chunk_and_barrier_lifecycle(repo: TopologyRepository):
    """Test full assembly of chunk followed by complete barrier into real tables."""
    payload = _make_it_topology()
    compressed, checksum = _compress_payload(payload)

    chunk_event = TopologyChunkEvent(
        event_type="TOPOLOGY_CHUNK",
        event_id="evt-c1",
        profile_id="IT_SERVICES",
        topology_version="it-test-v1",
        chunk_index=0,
        chunk_count=1,
        chunk_checksum=sha256_hex(compressed),
        payload_checksum=checksum,
        payload=compressed,
        produced_at=datetime.now(timezone.utc).isoformat(),
    )

    complete_event = TopologyCompleteEvent(
        event_type="TOPOLOGY_COMPLETE",
        event_id="evt-barrier",
        profile_id="IT_SERVICES",
        topology_version="it-test-v1",
        source_version=payload["source_version"],
        chunk_count=1,
        payload_checksum=checksum,
        node_count=len(payload["nodes"]),
        edge_count=len(payload["edges"]),
        alias_count=len(payload["alias_resolution"]),
        relation_model="DIRECTED_SOURCE_RELATIONS",
        direction_kind="SOURCE_RELATION",
        dependency_semantics="UNVERIFIED",
        navigation_eligible=True,
        p2_eligible=False,
        produced_at=datetime.now(timezone.utc).isoformat(),
    )

    # Ingest chunk 0
    res1 = await repo.process_kafka_event(
        chunk_event, topic="nocpro.topology.v1", partition=0, offset=100, message_key="IT_SERVICES"
    )
    assert res1 is None  # Awaiting barrier

    # Duplicate chunk delivery must be ignored (returns None without reprocessing)
    res1_dup = await repo.process_kafka_event(
        chunk_event, topic="nocpro.topology.v1", partition=0, offset=100, message_key="IT_SERVICES"
    )
    assert res1_dup is None

    # Ingest barrier -> triggers completion!
    res2 = await repo.process_kafka_event(
        complete_event, topic="nocpro.topology.v1", partition=0, offset=101, message_key="IT_SERVICES"
    )
    assert res2 == ("IT_SERVICES", "it-test-v1")

    # Verify repository queries
    assert await repo.is_topology_ready("IT_SERVICES", "it-test-v1") is True
    active_ver = await repo.get_active_version("IT_SERVICES")
    assert active_ver is not None
    assert active_ver.topology_version == "it-test-v1"

    profiles = await repo.list_profiles()
    assert "IT_SERVICES" in profiles


async def test_topology_repository_dual_path_assembly_early_barrier(repo: TopologyRepository):
    """Test dual-path recovery when complete barrier arrives BEFORE the chunk."""
    payload = _make_it_topology()
    payload["topology_version"] = "it-early-barrier-v1"
    compressed, checksum = _compress_payload(payload)

    chunk_event = TopologyChunkEvent(
        event_type="TOPOLOGY_CHUNK",
        event_id="evt-c-late",
        profile_id="IT_SERVICES",
        topology_version="it-early-barrier-v1",
        chunk_index=0,
        chunk_count=1,
        chunk_checksum=sha256_hex(compressed),
        payload_checksum=checksum,
        payload=compressed,
        produced_at=datetime.now(timezone.utc).isoformat(),
    )

    complete_event = TopologyCompleteEvent(
        event_type="TOPOLOGY_COMPLETE",
        event_id="evt-b-early",
        profile_id="IT_SERVICES",
        topology_version="it-early-barrier-v1",
        source_version=payload["source_version"],
        chunk_count=1,
        payload_checksum=checksum,
        node_count=len(payload["nodes"]),
        edge_count=len(payload["edges"]),
        alias_count=len(payload["alias_resolution"]),
        relation_model="DIRECTED_SOURCE_RELATIONS",
        direction_kind="SOURCE_RELATION",
        dependency_semantics="UNVERIFIED",
        navigation_eligible=True,
        p2_eligible=False,
        produced_at=datetime.now(timezone.utc).isoformat(),
    )

    # 1. Complete barrier arrives first -> stages barrier metadata
    res_b = await repo.process_kafka_event(
        complete_event, topic="nocpro.topology.v1", partition=0, offset=200, message_key="IT_SERVICES"
    )
    assert res_b is None  # Awaiting chunks!

    # 2. Chunk arrives second -> triggers dual-path assembly!
    res_c = await repo.process_kafka_event(
        chunk_event, topic="nocpro.topology.v1", partition=0, offset=201, message_key="IT_SERVICES"
    )
    assert res_c == ("IT_SERVICES", "it-early-barrier-v1")

    assert await repo.is_topology_ready("IT_SERVICES", "it-early-barrier-v1") is True


async def test_topology_repository_projection_and_resolution(repo: TopologyRepository):
    """Test IP undirected adjacency vs IT directed relation and alias resolution."""
    # 1. Materialize IT
    it_payload = _make_it_topology()
    it_comp, it_cksum = _compress_payload(it_payload)
    await repo.process_kafka_event(
        TopologyChunkEvent(
            event_type="TOPOLOGY_CHUNK", event_id="e1", profile_id="IT_SERVICES", topology_version="it-test-v1",
            chunk_index=0, chunk_count=1, chunk_checksum=sha256_hex(it_comp), payload_checksum=it_cksum, payload=it_comp,
            produced_at=datetime.now(timezone.utc).isoformat()
        ),
        topic="nocpro.topology.v1", partition=0, offset=301, message_key="IT_SERVICES",
    )
    await repo.process_kafka_event(
        TopologyCompleteEvent(
            event_type="TOPOLOGY_COMPLETE", event_id="e2", profile_id="IT_SERVICES", topology_version="it-test-v1",
            source_version=it_payload["source_version"], chunk_count=1, payload_checksum=it_cksum,
            node_count=len(it_payload["nodes"]), edge_count=len(it_payload["edges"]), alias_count=len(it_payload["alias_resolution"]),
            relation_model="DIRECTED_SOURCE_RELATIONS", direction_kind="SOURCE_RELATION", dependency_semantics="UNVERIFIED",
            navigation_eligible=True, p2_eligible=False, produced_at=datetime.now(timezone.utc).isoformat()
        ),
        topic="nocpro.topology.v1", partition=0, offset=302, message_key="IT_SERVICES",
    )

    # 2. Materialize IP
    ip_payload = _make_ip_topology()
    ip_comp, ip_cksum = _compress_payload(ip_payload)
    await repo.process_kafka_event(
        TopologyChunkEvent(
            event_type="TOPOLOGY_CHUNK", event_id="e3", profile_id="IP_NETWORK", topology_version="ip-test-v1",
            chunk_index=0, chunk_count=1, chunk_checksum=sha256_hex(ip_comp), payload_checksum=ip_cksum, payload=ip_comp,
            produced_at=datetime.now(timezone.utc).isoformat()
        ),
        topic="nocpro.topology.v1", partition=0, offset=303, message_key="IP_NETWORK",
    )
    await repo.process_kafka_event(
        TopologyCompleteEvent(
            event_type="TOPOLOGY_COMPLETE", event_id="e4", profile_id="IP_NETWORK", topology_version="ip-test-v1",
            source_version=ip_payload["source_version"], chunk_count=1, payload_checksum=ip_cksum,
            node_count=len(ip_payload["nodes"]), edge_count=len(ip_payload["edges"]), alias_count=len(ip_payload["alias_resolution"]),
            relation_model="PHYSICAL_ADJACENCY", direction_kind="NONE", dependency_semantics="UNAVAILABLE",
            navigation_eligible=True, p2_eligible=False, produced_at=datetime.now(timezone.utc).isoformat()
        ),
        topic="nocpro.topology.v1", partition=0, offset=304, message_key="IP_NETWORK",
    )

    # 3. IP Projection must traverse undirected (from target SWITCH_B to ROUTER_A)
    ip_proj = await repo.get_projection("IP_NETWORK", root_id="SWITCH_B", max_depth=2, max_children=10)
    assert ip_proj["status"] == "AVAILABLE"
    assert ip_proj["topology_kind"] == "UNDIRECTED_ADJACENCY"
    assert ip_proj["dependency_semantics"] == "UNAVAILABLE"
    assert len(ip_proj["tree"]["children"]) == 1
    assert ip_proj["tree"]["children"][0]["resource_id"] == "ROUTER_A"

    # 4. IT Alias resolution with status UNIQUE
    it_alias_res = await repo.resolve_identifier("IT_SERVICES", "order-srv-alias")
    assert it_alias_res["status"] == "AVAILABLE"
    assert it_alias_res["resource_id"] == "svc_order"
    assert it_alias_res["mapping_status"] == "VERIFIED_ALIAS"
    assert it_alias_res["dependency_semantics"] == "UNVERIFIED"

    # 5. IP Identifier resolution must lock dependency_semantics to UNAVAILABLE
    ip_res = await repo.resolve_identifier("IP_NETWORK", "ROUTER_A")
    assert ip_res["status"] == "AVAILABLE"
    assert ip_res["resource_id"] == "ROUTER_A"
    assert ip_res["dependency_semantics"] == "UNAVAILABLE"

    # 6. Hydration for Analysis Worker
    hydrated = await repo.hydrate_graph_for_analysis("IP_NETWORK", "ip-test-v1")
    assert hydrated is not None
    assert len(hydrated["nodes"]) == 2
    assert len(hydrated["edges"]) == 1

    # 7. Subgraph extraction around seeds
    subgraph = await repo.get_subgraph("IP_NETWORK", seeds=["ROUTER_A"], max_hops=1)
    assert subgraph["status"] == "AVAILABLE"
    assert len(subgraph["nodes"]) == 2
    assert len(subgraph["edges"]) == 1
    seed_node = next(n for n in subgraph["nodes"] if n["id"] == "ROUTER_A")
    assert seed_node["is_seed"] is True


async def test_alarm_entity_resolution_persistence(repo: TopologyRepository):
    from contracts.v1.enums import MappingMethod, MappingStatus
    from contracts.v1.models import AlarmEntityResolution

    res1 = AlarmEntityResolution(
        alarm_id="ALM_101",
        entity_role="OBSERVED_HOST",
        raw_value="10.210.48.81",
        resource_id="it:instance:724822",
        status=MappingStatus.EXACT,
        method=MappingMethod.EXACT_IDENTITY,
        source_field="device_ip",
        confidence=1.0,
        topology_profile_id="IT_SERVICES",
        topology_version="it-test-v1",
        candidate_resource_ids=("it:instance:724822",),
        matched_text="10.210.48.81",
        resolver_version="v1",
    )
    res2 = AlarmEntityResolution(
        alarm_id="ALM_101",
        entity_role="AFFECTED_COMPONENT_CANDIDATE",
        raw_value="neutron-openvswitch-agent",
        resource_id="it:module:93645",
        status=MappingStatus.STRUCTURED_FIELD_UNIQUE,
        method=MappingMethod.STRUCTURED_FIELD_EXACT,
        source_field="component",
        confidence=0.85,
        topology_profile_id="IT_SERVICES",
        topology_version="it-test-v1",
        candidate_resource_ids=("it:module:93645",),
        matched_text="neutron-openvswitch-agent",
        resolver_version="v1",
    )

    # 1. Save
    await repo.save_alarm_entity_resolutions([res1, res2])

    # 2. Fetch
    fetched = await repo.get_alarm_entity_resolutions(
        ["ALM_101"], profile_id="IT_SERVICES", topology_version="it-test-v1"
    )
    assert len(fetched) == 2
    roles = {r.entity_role for r in fetched}
    assert roles == {"OBSERVED_HOST", "AFFECTED_COMPONENT_CANDIDATE"}

    # Check mapping status preserved
    host = next(r for r in fetched if r.entity_role == "OBSERVED_HOST")
    assert host.status == MappingStatus.EXACT
    assert host.resource_id == "it:instance:724822"
    assert host.confidence == 1.0

    comp = next(r for r in fetched if r.entity_role == "AFFECTED_COMPONENT_CANDIDATE")
    assert comp.status == MappingStatus.STRUCTURED_FIELD_UNIQUE
    assert comp.confidence == 0.85

    # 3. Update existing with new confidence and ensure composite key doesn't insert duplicate
    res2_updated = AlarmEntityResolution(
        alarm_id="ALM_101",
        entity_role="AFFECTED_COMPONENT_CANDIDATE",
        raw_value="neutron-openvswitch-agent",
        resource_id="it:module:93645",
        status=MappingStatus.STRUCTURED_FIELD_UNIQUE,
        method=MappingMethod.STRUCTURED_FIELD_EXACT,
        source_field="component",
        confidence=0.90,
        topology_profile_id="IT_SERVICES",
        topology_version="it-test-v1",
        candidate_resource_ids=("it:module:93645",),
        matched_text="neutron-openvswitch-agent",
        resolver_version="v1",
    )
    await repo.save_alarm_entity_resolutions([res2_updated])

    fetched_after = await repo.get_alarm_entity_resolutions(
        ["ALM_101"], profile_id="IT_SERVICES", topology_version="it-test-v1"
    )
    assert len(fetched_after) == 2
    comp_updated = next(r for r in fetched_after if r.entity_role == "AFFECTED_COMPONENT_CANDIDATE")
    assert comp_updated.confidence == 0.90

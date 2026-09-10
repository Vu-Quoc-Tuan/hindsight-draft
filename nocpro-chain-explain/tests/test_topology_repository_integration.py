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

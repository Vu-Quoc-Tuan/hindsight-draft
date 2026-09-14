"""Unit tests for Topology Representation Learning and Graph Proximity Embedding (§4A, ADR-0022)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from channels import (
    ChannelFamily,
    EvidenceState,
    ResourceResolver,
    TopologyEmbeddingModel,
    TopologyGraph,
    evaluate_pair_channels,
    evaluate_topo_embedding_channel,
)
from channels.topology_embedding import (
    CHANNEL_ID,
    DEFAULT_SUPPORT_THRESHOLD,
    DERIVATION_TAG,
)
from libs.contracts import IngestedAlarm, IngestedPackage, IngestedSnapshot
from libs.provenance import ProvenanceClass
from similar_chains import (
    ChainFingerprint,
    FingerprintModel,
    TermVector,
    fit_fingerprint_model,
    hybrid_topology_similarity,
)


def make_alarm(alarm_id: str, **fields) -> IngestedAlarm:
    raw = {k: str(v) for k, v in fields.items() if v is not None}
    return IngestedAlarm(
        alarm_id=alarm_id,
        snapshot_id="s1",
        raw=raw,
        alarm_name=fields.get("alarm_name"),
        device_code=fields.get("device_code"),
        node_reference=fields.get("node_reference"),
        canonical_start_time=fields.get("canonical_start_time"),
    )


# --------------------------------------------------------------------------
# Model Fitting & Mathematical Properties
# --------------------------------------------------------------------------


def test_fit_from_ring_adjacency():
    """A 4-node ring topology A - B - C - D - A has high latent proximity across neighbors."""
    adj = {
        "A": {"B", "D"},
        "B": {"A", "C"},
        "C": {"B", "D"},
        "D": {"C", "A"},
    }
    model = TopologyEmbeddingModel.fit_from_adjacency(adj, dimension=8)
    assert model.dimension > 0
    assert len(model.node_to_index) == 4

    # Check embeddings are L2 normalized (unit length)
    for node in ["A", "B", "C", "D"]:
        emb = model.get_node_embedding(node)
        assert emb is not None
        assert np.isclose(np.linalg.norm(emb), 1.0, atol=1e-5)

    # Symmetry
    cos_ab = model.cosine_similarity("A", "B")
    cos_ba = model.cosine_similarity("B", "A")
    assert cos_ab is not None and cos_ba is not None
    assert np.isclose(cos_ab, cos_ba, atol=1e-5)

    # Self-similarity should be 1.0
    cos_aa = model.cosine_similarity("A", "A")
    assert cos_aa is not None
    assert np.isclose(cos_aa, 1.0, atol=1e-5)

    # Normalized affinity is in [0, 1]
    aff_ab = model.normalized_affinity("A", "B")
    assert aff_ab is not None
    assert 0.0 <= aff_ab <= 1.0


def test_fit_preserves_disconnected_community_separation():
    """Two disconnected triangles should have lower inter-community affinity than intra-community."""
    adj = {
        # Community 1
        "c1_a": {"c1_b", "c1_c"},
        "c1_b": {"c1_a", "c1_c"},
        "c1_c": {"c1_a", "c1_b"},
        # Community 2
        "c2_x": {"c2_y", "c2_z"},
        "c2_y": {"c2_x", "c2_z"},
        "c2_z": {"c2_x", "c2_y"},
    }
    model = TopologyEmbeddingModel.fit_from_adjacency(adj, dimension=4)
    intra = model.normalized_affinity("c1_a", "c1_b")
    inter = model.normalized_affinity("c1_a", "c2_x")

    assert intra is not None
    assert inter is not None
    assert intra > inter


def test_fit_from_topology_graph():
    """TopologyGraph object can directly fit a TopologyEmbeddingModel."""
    graph = TopologyGraph(relation_types=frozenset({"PHYSICAL_ADJACENCY"}))
    graph.adjacency = {
        "router_1": {"switch_1"},
        "switch_1": {"router_1", "host_1"},
        "host_1": {"switch_1"},
    }
    graph.source_ref = "test_topo_v1"
    model = TopologyEmbeddingModel.fit_from_topology_graph(graph, dimension=4)
    assert model.source_ref == "test_topo_v1"
    assert "router_1" in model.node_to_index
    assert "host_1" in model.node_to_index


def test_empty_and_singleton_graphs():
    """Empty or disconnected single-node topologies do not crash."""
    empty_model = TopologyEmbeddingModel.fit_from_adjacency({})
    assert empty_model.dimension == 16
    assert len(empty_model.node_to_index) == 0

    single_model = TopologyEmbeddingModel.fit_from_adjacency({"A": set()})
    assert len(single_model.node_to_index) == 1
    emb = single_model.get_node_embedding("A")
    assert emb is not None


# --------------------------------------------------------------------------
# Serialization & Persistence
# --------------------------------------------------------------------------


def test_save_and_load_npz():
    """Model can be saved to a compressed npz file and reloaded identically."""
    adj = {"dev1": {"dev2"}, "dev2": {"dev1", "dev3"}, "dev3": {"dev2"}}
    original = TopologyEmbeddingModel.fit_from_adjacency(adj, dimension=4, source_ref="topo_export_v1")

    with tempfile.TemporaryDirectory() as td:
        save_path = Path(td) / "topo_embed.npz"
        original.save_npz(save_path)
        assert save_path.is_file()

        loaded = TopologyEmbeddingModel.load_npz(save_path)
        assert loaded.dimension == original.dimension
        assert loaded.node_to_index == original.node_to_index
        assert loaded.source_ref == original.source_ref
        assert np.allclose(loaded.embeddings, original.embeddings, atol=1e-6)


# --------------------------------------------------------------------------
# Channel Evaluation Contract (Fail-Closed & Availability)
# --------------------------------------------------------------------------


def test_channel_evaluation_available_when_mapped():
    """Properly mapped alarms on known devices yield an available Dep_embed channel."""
    alarm_a = make_alarm("a1")
    alarm_b = make_alarm("a2")
    resolver = ResourceResolver(resolved={"a1": "dev1", "a2": "dev2"})
    model = TopologyEmbeddingModel.fit_from_adjacency(
        {"dev1": {"dev2"}, "dev2": {"dev1"}},
        dimension=4,
    )

    cv = evaluate_topo_embedding_channel(
        alarm_a,
        alarm_b,
        model=model,
        resolver=resolver,
        threshold=0.5,
    )

    assert cv.channel_id == CHANNEL_ID
    assert cv.channel_family == ChannelFamily.DEP_EMBEDDING
    assert cv.availability is True
    assert 0.0 <= cv.positive_score <= 1.0
    assert cv.state in (EvidenceState.SUPPORT, EvidenceState.NEUTRAL)
    assert cv.evidence_metadata is not None
    assert cv.evidence_metadata["resource_a"] == "dev1"
    assert cv.evidence_metadata["resource_b"] == "dev2"


def test_channel_evaluation_fails_closed_when_unmapped():
    """Missing or unmapped resource mapping strictly forces channel to UNAVAILABLE (⊥)."""
    alarm_a = make_alarm("a1")
    alarm_b = make_alarm("a2")
    # Only a1 is resolved, a2 is missing
    resolver = ResourceResolver(resolved={"a1": "dev1"})
    model = TopologyEmbeddingModel.fit_from_adjacency({"dev1": {"dev2"}})

    cv = evaluate_topo_embedding_channel(
        alarm_a,
        alarm_b,
        model=model,
        resolver=resolver,
    )

    assert cv.availability is False
    assert cv.state == EvidenceState.UNAVAILABLE
    assert "lack exact resource mapping" in str(cv.detail)


def test_channel_evaluation_fails_closed_when_model_is_none():
    """None model gracefully yields UNAVAILABLE without error."""
    alarm_a = make_alarm("a1")
    alarm_b = make_alarm("a2")
    resolver = ResourceResolver(resolved={"a1": "dev1", "a2": "dev2"})

    cv = evaluate_topo_embedding_channel(
        alarm_a,
        alarm_b,
        model=None,
        resolver=resolver,
    )

    assert cv.availability is False
    assert cv.state == EvidenceState.UNAVAILABLE


# --------------------------------------------------------------------------
# Integration with evaluate_pair_channels
# --------------------------------------------------------------------------


def test_evaluate_pair_channels_includes_topo_embedding_when_requested():
    """evaluate_pair_channels appends Dep_embed when include_topo_embedding=True."""
    alarm_a = make_alarm("a1", canonical_start_time="2026-09-01T10:00:00Z")
    alarm_b = make_alarm("a2", canonical_start_time="2026-09-01T10:00:02Z")

    package = IngestedPackage(
        snapshot=IngestedSnapshot(
            snapshot_id="s1",
            snapshot_version="1",
            snapshot_time="2026-09-01T10:00:00Z",
            status="COMPLETE",
            source="foreign-producer",
            source_kind="SYNTHETIC_TEST",
            produced_at="2026-09-01T10:00:01Z",
            topology_version="topo_v1",
        ),
        alarms={"a1": alarm_a, "a2": alarm_b},
        memberships={"c1": ["a1", "a2"]},
        topology={
            "mappings": [
                {"alarm_id": "a1", "resource_id": "R1", "mapping_status": "EXACT"},
                {"alarm_id": "a2", "resource_id": "R2", "mapping_status": "EXACT"},
            ],
            "edges": [
                {
                    "source_resource_id": "R1",
                    "target_resource_id": "R2",
                    "relation_type": "PHYSICAL_ADJACENCY",
                }
            ],
        },
    )

    model = TopologyEmbeddingModel.fit_from_adjacency({"R1": {"R2"}, "R2": {"R1"}}, dimension=4)

    # Without include_topo_embedding
    default_vals = evaluate_pair_channels(package, "c1", "a1", "a2")
    assert not any(v.channel_id == CHANNEL_ID for v in default_vals)

    # With include_topo_embedding
    vals = evaluate_pair_channels(
        package,
        "c1",
        "a1",
        "a2",
        topo_embedding_model=model,
        include_topo_embedding=True,
    )
    embed_val = next((v for v in vals if v.channel_id == CHANNEL_ID), None)
    assert embed_val is not None
    assert embed_val.availability is True
    assert embed_val.channel_family == ChannelFamily.DEP_EMBEDDING


# --------------------------------------------------------------------------
# Integration with similar_chains (Hybrid Structural Similarity)
# --------------------------------------------------------------------------


def test_hybrid_topology_similarity_blends_semantic_and_graph_embeddings():
    """hybrid_topology_similarity combines text/taxonomy fingerprint with topology graph representation."""
    fp1 = ChainFingerprint(
        chain_id="c1",
        lineage_component_id="lin1",
        family_terms=TermVector.from_terms(["BGP_DOWN"]),
        device_type_terms=TermVector.from_terms(["ROUTER"]),
        descriptor_terms=(),
        size_bin="size_bin_1",
        duration_bin="duration_bin_1",
        member_count=2,
    )
    fp2 = ChainFingerprint(
        chain_id="c2",
        lineage_component_id="lin2",
        family_terms=TermVector.from_terms(["BGP_DOWN"]),
        device_type_terms=TermVector.from_terms(["ROUTER"]),
        descriptor_terms=(),
        size_bin="size_bin_1",
        duration_bin="duration_bin_1",
        member_count=2,
    )

    model = fit_fingerprint_model([fp1, fp2], model_version="sim-v1")
    topo_model = TopologyEmbeddingModel.fit_from_adjacency(
        {"r1": {"r2"}, "r2": {"r1"}, "r3": {"r4"}, "r4": {"r3"}},
        dimension=4,
    )

    # Devices r1 and r2 are tightly linked in community 1; r3 and r4 in community 2
    hybrid_linked, sem, topo_linked = hybrid_topology_similarity(
        fp1,
        fp2,
        model=model,
        topo_model=topo_model,
        left_resources=["r1"],
        right_resources=["r2"],
        topo_weight=0.5,
    )

    hybrid_distant, _, topo_distant = hybrid_topology_similarity(
        fp1,
        fp2,
        model=model,
        topo_model=topo_model,
        left_resources=["r1"],
        right_resources=["r3"],
        topo_weight=0.5,
    )

    assert topo_linked > topo_distant
    assert hybrid_linked > hybrid_distant

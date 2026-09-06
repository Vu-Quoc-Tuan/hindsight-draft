from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json

import pytest

from audit import (
    AuditVerdict,
    Candidate,
    CandidateSource,
    ConductanceResult,
    ScoredCandidate,
    StructuralAuditResult,
)
from tier2.audit_artifact import (
    AUDIT_ARTIFACT_VERSION,
    ReviewAuditArtifact,
    audit_artifact_from_dict,
    audit_artifact_to_dict,
    build_review_audit_artifact,
)
from tier2.audit_visualization import (
    AUDIT_VISUALIZATION_MAX_EDGES,
    AUDIT_VISUALIZATION_MAX_NODES,
    AUDIT_VISUALIZATION_SELECTION_STRATEGY,
    AUDIT_VISUALIZATION_VERSION,
    AuditVisualization,
    AuditVisualizationEdge,
    AuditVisualizationNode,
)


def _audit() -> StructuralAuditResult:
    cut = ScoredCandidate(
        candidate=Candidate(
            source=CandidateSource.DESCRIPTOR,
            members=frozenset({"a1", "a2"}),
            label="device_code=D1",
        ),
        conductance=ConductanceResult(
            label="device_code=D1",
            size_s=2,
            size_complement=2,
            phi=0.125,
            feasible=True,
            reason=None,
        ),
    )
    return StructuralAuditResult(
        chain_id="C1",
        verdict=AuditVerdict.CANDIDATE_SPLIT,
        best_cut=cut,
        scored_candidates=(cut,),
        epsilon=0.2,
        reason="balanced low-conductance cut found",
    )


def _artifact() -> ReviewAuditArtifact:
    return build_review_audit_artifact(
        snapshot_id="S1",
        snapshot_version="v2",
        chain_id="C1",
        members=("a4", "a2", "a1", "a3"),
        structural_audit=_audit(),
        visualization=_visualization(),
        analysis_version="tier2-audit-v1",
        analysis_config_version="thresholds-v1",
        artifact_id="audit-run-1",
        created_at="2026-09-02T10:00:00+00:00",
    )


def _visualization() -> AuditVisualization:
    return AuditVisualization(
        status="AVAILABLE",
        reason=None,
        projection_version=AUDIT_VISUALIZATION_VERSION,
        selection_strategy=AUDIT_VISUALIZATION_SELECTION_STRATEGY,
        max_nodes=AUDIT_VISUALIZATION_MAX_NODES,
        max_edges=AUDIT_VISUALIZATION_MAX_EDGES,
        total_node_count=4,
        shown_node_count=2,
        hidden_node_count=2,
        total_edge_count=1,
        shown_edge_count=1,
        hidden_edge_count=0,
        truncated=True,
        nodes=(
            AuditVisualizationNode("a1", 0.8, "A", "NON_CONNECTOR"),
            AuditVisualizationNode("a3", 0.8, "B", "CONNECTOR"),
        ),
        edges=(
            AuditVisualizationEdge("a1", "a3", 0.8, ("entity", "temporal"), True),
        ),
    )


def test_exact_audit_artifact_v2_round_trips_with_bounded_visualization():
    artifact = _artifact()
    payload = audit_artifact_to_dict(artifact)
    restored = audit_artifact_from_dict(payload)

    assert restored == artifact
    assert restored.artifact_version == AUDIT_ARTIFACT_VERSION
    assert restored.structural_audit == _audit()
    assert "graph" not in payload
    assert "pair_evidence" not in payload
    assert restored.visualization == _visualization()
    assert payload["visualization"]["shown_node_count"] == 2
    assert payload["scored_cuts"][0]["members"] == ["a1", "a2"]


def test_artifact_fingerprint_is_deterministic_and_detects_tampering():
    first = _artifact()
    second = _artifact()
    assert first.artifact_fingerprint == second.artifact_fingerprint

    payload = audit_artifact_to_dict(first)
    payload["visualization"]["edges"][0]["weight"] = 0.5
    with pytest.raises(ValueError, match="fingerprint"):
        audit_artifact_from_dict(payload)


def test_legacy_v1_artifact_hydrates_without_mutation_or_visualization():
    payload = audit_artifact_to_dict(_artifact())
    payload["artifact_version"] = "review-audit-v1"
    payload.pop("visualization")
    payload.pop("artifact_fingerprint")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["artifact_fingerprint"] = sha256(encoded.encode("utf-8")).hexdigest()

    restored = audit_artifact_from_dict(payload)

    assert restored.artifact_version == "review-audit-v1"
    assert restored.visualization is None
    assert audit_artifact_to_dict(restored) == payload


def test_v2_artifact_rejects_invalid_bounded_visualization_structure():
    payload = audit_artifact_to_dict(_artifact())
    payload["visualization"]["edges"][0]["target_alarm_id"] = "missing-node"
    with pytest.raises(ValueError, match="edge is not canonical"):
        audit_artifact_from_dict(payload, verify_fingerprint=False)

    payload = audit_artifact_to_dict(_artifact())
    payload["visualization"]["max_nodes"] = 81
    with pytest.raises(ValueError, match="policy mismatch"):
        audit_artifact_from_dict(payload, verify_fingerprint=False)


def test_deserialization_rejects_non_exact_artifact():
    artifact = _artifact()
    payload = audit_artifact_to_dict(artifact)
    payload["mode"] = "SPARSIFIED"
    with pytest.raises(ValueError, match="exact"):
        audit_artifact_from_dict(payload, verify_fingerprint=False)


def test_compatibility_is_strict_for_snapshot_chain_membership_and_config():
    artifact = _artifact()

    assert artifact.is_compatible(
        snapshot_id="S1",
        snapshot_version="v2",
        chain_id="C1",
        members=("a1", "a2", "a3", "a4"),
        analysis_version="tier2-audit-v1",
        analysis_config_version="thresholds-v1",
    )
    assert not artifact.is_compatible(
        snapshot_id="S1",
        snapshot_version="v1",
        chain_id="C1",
        members=("a1", "a2", "a3", "a4"),
        analysis_version="tier2-audit-v1",
        analysis_config_version="thresholds-v1",
    )
    assert not replace(
        artifact, analysis_config_version="thresholds-v0"
    ).is_compatible(
        snapshot_id="S1",
        snapshot_version="v2",
        chain_id="C1",
        members=("a1", "a2", "a3", "a4"),
        analysis_version="tier2-audit-v1",
        analysis_config_version="thresholds-v1",
    )

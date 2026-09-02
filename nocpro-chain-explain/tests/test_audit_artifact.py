from __future__ import annotations

from dataclasses import replace

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
        analysis_version="tier2-audit-v1",
        analysis_config_version="thresholds-v1",
        artifact_id="audit-run-1",
        created_at="2026-09-02T10:00:00+00:00",
    )


def test_exact_audit_artifact_round_trips_without_dense_graph():
    artifact = _artifact()
    payload = audit_artifact_to_dict(artifact)
    restored = audit_artifact_from_dict(payload)

    assert restored == artifact
    assert restored.artifact_version == AUDIT_ARTIFACT_VERSION
    assert restored.structural_audit == _audit()
    assert "graph" not in payload
    assert "pair_evidence" not in payload
    assert payload["scored_cuts"][0]["members"] == ["a1", "a2"]


def test_artifact_fingerprint_is_deterministic_and_detects_tampering():
    first = _artifact()
    second = _artifact()
    assert first.artifact_fingerprint == second.artifact_fingerprint

    payload = audit_artifact_to_dict(first)
    payload["scored_cuts"][0]["conductance"]["phi"] = 0.5
    with pytest.raises(ValueError, match="fingerprint"):
        audit_artifact_from_dict(payload)


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

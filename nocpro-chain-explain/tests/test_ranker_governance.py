"""Unit tests for XGBRanker governance, cryptographic signing, and production verification."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from review_learning import (
    FEATURE_SCHEMA_VERSION,
    LABEL_POLICY_VERSION,
    RankerArtifactManifest,
    generate_synthetic_review_corpus,
    load_production_ranker_artifact,
    materialize_training_corpus,
    save_ranker_artifact,
    sign_ranker_artifact,
    train_xgbranker,
    verify_ranker_artifact_signature,
)
from nocpro_api.review_learning_service import ReviewLearningService
from review_learning.contracts import CandidateExposure, canonical_fingerprint


@pytest.fixture
def trained_ranker():
    sessions, exposures, feedbacks = generate_synthetic_review_corpus(
        group_count=20,
        base_date="2026-09-01T10:00:00Z",
    )
    corpus = materialize_training_corpus(
        sessions=sessions,
        exposures=exposures,
        feedbacks=feedbacks,
        cutoff="2026-09-10T00:00:00Z",
    )
    model, metrics = train_xgbranker(
        train_ds=corpus.train,
        val_ds=corpus.val,
        params={"n_estimators": 5, "max_depth": 3, "random_state": 42},
    )
    return model, metrics, corpus.cutoff, corpus.corpus_fingerprint


def _make_manifest(metrics, cutoff, fp, **overrides) -> RankerArtifactManifest:
    prof_data = {
        "profile_version": "v1",
        "created_at": "2026-09-10T00:00:00Z",
        "total_groups": 10,
        "feature_count": 43,
        "lineage_overlap_detected": False,
        "temporal_inversion_detected": False,
        "corpus_fingerprint": fp,
    }
    base = {
        "model_version": "gov_test_v1",
        "model_family": "XGBRanker",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "label_policy_version": LABEL_POLICY_VERSION,
        "training_cutoff": cutoff,
        "corpus_fingerprint": fp,
        "hyperparameters": {"n_estimators": 5, "max_depth": 3},
        "metrics": metrics,
        "slice_metrics": {},
        "artifact_sha256": "",
        "source_kind_mix": {"REAL_LIVE": 10},
        "truth_tier_distribution": {"PO_ASSERTED": 10},
        "protected_mode_used": True,
        "strict_temporal_holdout_used": True,
        "lineage_overlap_detected": False,
        "temporal_inversion_detected": False,
        "approval_status": "DRAFT",
        "data_profile_fingerprint": canonical_fingerprint(prof_data),
    }
    base.update(overrides)
    return RankerArtifactManifest(**base)


def _write_data_profile(target_dir: Path, fp: str = "") -> str:
    prof_path = target_dir / "data_profile.json"
    prof_data = {
        "profile_version": "v1",
        "created_at": "2026-09-10T00:00:00Z",
        "total_groups": 10,
        "feature_count": 43,
        "lineage_overlap_detected": False,
        "temporal_inversion_detected": False,
        "corpus_fingerprint": fp,
    }
    prof_path.write_text(json.dumps(prof_data), encoding="utf-8")
    return canonical_fingerprint(prof_data)


def test_sign_artifact_requires_non_empty_principal(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    save_ranker_artifact(model, manifest, tmp_path)

    with pytest.raises(ValueError, match="non-empty principal_id is required"):
        sign_ranker_artifact(tmp_path, principal_id="", signing_key="secret123")

    with pytest.raises(ValueError, match="non-empty principal_id is required"):
        sign_ranker_artifact(tmp_path, principal_id="   ", signing_key="secret123")


def test_sign_and_verify_requires_signing_key(trained_ranker, tmp_path, monkeypatch):
    monkeypatch.delenv("NOCPRO_GOVERNANCE_SIGNING_KEY", raising=False)
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    save_ranker_artifact(model, manifest, tmp_path)

    with pytest.raises(ValueError, match="HMAC governance signing key is required"):
        sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key=None)


def test_verify_fails_if_detached_signature_missing(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    # Remove detached file
    (tmp_path / "approval_signature.json").unlink()

    with pytest.raises(ValueError, match="Detached approval signature file missing"):
        verify_ranker_artifact_signature(tmp_path, signing_key="secret123")


def test_verify_fails_if_signature_tampered(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    # Tamper with detached signature
    sig_path = tmp_path / "approval_signature.json"
    with open(sig_path, "r", encoding="utf-8") as f:
        sig_data = json.load(f)
    sig_data["signature"] = "deadbeef" * 8
    with open(sig_path, "w", encoding="utf-8") as f:
        json.dump(sig_data, f)

    with pytest.raises(ValueError, match="Detached approval signature does not match"):
        verify_ranker_artifact_signature(tmp_path, signing_key="secret123")


def test_verify_fails_if_manifest_digest_tampered(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    # Modify manifest after signing
    manifest_file = tmp_path / "manifest.json"
    with open(manifest_file, "r", encoding="utf-8") as f:
        man_data = json.load(f)
    man_data["model_family"] = "TAMPERED_RANKER"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(man_data, f)

    with pytest.raises(ValueError, match="Detached signature canonical digest does not match"):
        verify_ranker_artifact_signature(tmp_path, signing_key="secret123")


def test_verify_fails_on_wrong_key(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="correct_key")

    with pytest.raises(ValueError, match="Cryptographic signature verification failed"):
        verify_ranker_artifact_signature(tmp_path, signing_key="wrong_key")


def test_load_production_rejects_unapproved_truth_tiers(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    # Include TEST_FIXTURE or unapproved tier
    manifest = _make_manifest(
        metrics,
        cutoff,
        fp,
        truth_tier_distribution={"TEST_FIXTURE": 5, "PO_ASSERTED": 5},
    )
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    with pytest.raises(ValueError, match="unapproved truth tiers"):
        load_production_ranker_artifact(tmp_path, signing_key="secret123")


def test_load_production_rejects_empty_or_nonpositive_truth_tiers(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp, truth_tier_distribution={})
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    with pytest.raises(ValueError, match="truth_tier_distribution"):
        load_production_ranker_artifact(tmp_path, signing_key="secret123")


def test_load_production_succeeds_for_compliant_artifact(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(
        metrics,
        cutoff,
        fp,
        source_kind_mix={"REAL_LIVE": 5, "REAL_EXPORT_REPLAY": 5},
        truth_tier_distribution={"PO_ASSERTED": 8, "EXPERT_CONSENSUS": 2},
    )
    _write_data_profile(tmp_path, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    loaded_model, loaded_man = load_production_ranker_artifact(tmp_path, signing_key="secret123")
    assert loaded_man.approval_status == "APPROVED"
    assert loaded_man.approved_by == "lead_eng"


def test_rerank_candidate_exposures_nested_features(trained_ranker, tmp_path):
    """Verify ReviewLearningService parses nested feature_payload['features'] and scores."""
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(
        metrics,
        cutoff,
        fp,
        source_kind_mix={"REAL_LIVE": 10},
        truth_tier_distribution={"PO_ASSERTED": 10},
    )
    _write_data_profile(tmp_path, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    service = ReviewLearningService(
        ranker_artifact_dir=str(tmp_path),
        enforce_production_governance=True,
        signing_key="secret123",
    )

    cand1 = CandidateExposure(
        review_id="rev-test-1",
        candidate_id="cand-good",
        candidate_fingerprint="fp1",
        operation="REMOVE_MEMBER",
        original_rank=1,
        displayed_rank=1,
            deterministic_eligibility="HARD_GATES_PASSED",
        hard_gate_status="PASSED",
        pareto_state="DOMINATED",
        feature_payload={
            "features": {
                "op__remove": 1.0,
                "op__split": 0.0,
                "op__move": 0.0,
                "op__merge": 0.0,
                "benefit": 0.95,
                "raw_score": 10.0,
            }
        },
    )
    cand2 = CandidateExposure(
        review_id="rev-test-1",
        candidate_id="cand-poor",
        candidate_fingerprint="fp2",
        operation="MOVE_MEMBER",
        original_rank=0,
        displayed_rank=0,
            deterministic_eligibility="HARD_GATES_PASSED",
        hard_gate_status="PASSED",
        pareto_state="DOMINATED",
        feature_payload={
            "features": {
                "op__remove": 0.0,
                "op__split": 0.0,
                "op__move": 1.0,
                "op__merge": 0.0,
                "benefit": 0.05,
                "raw_score": 1.0,
            }
        },
    )

    reranked = service.rerank_candidate_exposures([cand2, cand1])
    assert len(reranked) == 2
    assert reranked[0].candidate_id == "cand-good"
    assert reranked[0].displayed_rank == 1
    assert reranked[1].candidate_id == "cand-poor"
    assert reranked[1].displayed_rank == 2
    assert reranked[0].deterministic_context["ranking_status"] == "RERANKED"
    assert reranked[0].feature_payload["model_score"] > reranked[1].feature_payload["model_score"]
    assert reranked[0].deterministic_context["margin"] > 0.0
    assert reranked[0].deterministic_context["ranking_audit"]["ranker_version"] == "gov_test_v1"


def test_abstention_threshold_preserves_original_order(trained_ranker, tmp_path):
    """Verify that an abstention threshold preserves original order when model margin is small."""
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(
        metrics,
        cutoff,
        fp,
        source_kind_mix={"REAL_LIVE": 10},
        truth_tier_distribution={"PO_ASSERTED": 10},
        abstention_threshold=1000.0,  # Unattainable high margin
    )
    _write_data_profile(tmp_path, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    service = ReviewLearningService(
        ranker_artifact_dir=str(tmp_path),
        enforce_production_governance=True,
        signing_key="secret123",
    )
    assert service.abstention_threshold == 1000.0


def test_abstention_threshold_preserves_original_order_and_persists_audit(trained_ranker, tmp_path):
    """Verify that an abstention threshold preserves original order when model margin is small, and records audit evidence."""
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(
        metrics,
        cutoff,
        fp,
        abstention_threshold=0.5,
        source_kind_mix={"REAL_LIVE": 10},
        truth_tier_distribution={"PO_ASSERTED": 10},
    )
    _write_data_profile(tmp_path, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    service = ReviewLearningService(
        ranker_artifact_dir=str(tmp_path),
        enforce_production_governance=True,
        signing_key="secret123",
    )

    cand1 = CandidateExposure(
        review_id="rev-test-1",
        candidate_id="cand-1",
        candidate_fingerprint="fp1",
        operation="REMOVE_MEMBER",
        original_rank=0,
        displayed_rank=1,
            deterministic_eligibility="HARD_GATES_PASSED",
        hard_gate_status="PASSED",
        pareto_state="DOMINATED",
        feature_payload={"features": {"benefit": 0.9}},
    )
    cand2 = CandidateExposure(
        review_id="rev-test-1",
        candidate_id="cand-2",
        candidate_fingerprint="fp2",
        operation="MOVE_MEMBER",
        original_rank=1,
        displayed_rank=2,
            deterministic_eligibility="HARD_GATES_PASSED",
        hard_gate_status="PASSED",
        pareto_state="DOMINATED",
        feature_payload={"features": {"benefit": 0.8}},
    )

    # With abstention, candidate list preserves original order but persists ABSTAINED audit
    reranked = service.rerank_candidate_exposures([cand1, cand2])
    assert [c.candidate_id for c in reranked] == ["cand-1", "cand-2"]
    assert reranked[0].deterministic_context["ranking_status"] == "ABSTAINED"
    assert reranked[0].deterministic_context["abstention_reason"] == "MARGIN_BELOW_THRESHOLD"
    assert reranked[0].feature_payload["model_score"] is not None


def test_production_governance_rejects_debug_invariants(trained_ranker, tmp_path):
    """Verify load_production_ranker_artifact rejects artifacts trained with debug flags."""
    model, metrics, cutoff, fp = trained_ranker

    # 1. Reject unprotected_mode
    m1 = _make_manifest(metrics, cutoff, fp, protected_mode_used=False)
    p1 = tmp_path / "art1"
    save_ranker_artifact(model, m1, p1)
    sign_ranker_artifact(p1, principal_id="lead_eng", signing_key="secret123")
    with pytest.raises(ValueError, match="protected_mode_used=False"):
        load_production_ranker_artifact(p1, signing_key="secret123")

    # 2. Reject strict_temporal_holdout_used=False
    m2 = _make_manifest(metrics, cutoff, fp, strict_temporal_holdout_used=False)
    p2 = tmp_path / "art2"
    save_ranker_artifact(model, m2, p2)
    sign_ranker_artifact(p2, principal_id="lead_eng", signing_key="secret123")
    with pytest.raises(ValueError, match="strict_temporal_holdout_used=False"):
        load_production_ranker_artifact(p2, signing_key="secret123")

    # 3. Reject lineage_overlap_detected=True
    m3 = _make_manifest(metrics, cutoff, fp, lineage_overlap_detected=True)
    p3 = tmp_path / "art3"
    save_ranker_artifact(model, m3, p3)
    sign_ranker_artifact(p3, principal_id="lead_eng", signing_key="secret123")
    with pytest.raises(ValueError, match="lineage overlap was detected"):
        load_production_ranker_artifact(p3, signing_key="secret123")

    # 4. Reject temporal_inversion_detected=True
    m4 = _make_manifest(metrics, cutoff, fp, temporal_inversion_detected=True)
    p4 = tmp_path / "art4"
    save_ranker_artifact(model, m4, p4)
    sign_ranker_artifact(p4, principal_id="lead_eng", signing_key="secret123")
    with pytest.raises(ValueError, match="temporal inversion was detected"):
        load_production_ranker_artifact(p4, signing_key="secret123")


def test_production_env_blocks_disabling_governance(monkeypatch):
    """Verify APP_ENV=production fails-closed if enforce_production_governance=False."""
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="Production environment detected"):
        ReviewLearningService(enforce_production_governance=False)


def test_workspace_manifest_threshold_inheritance(trained_ranker, tmp_path, monkeypatch):
    """Verify an explicitly active test ranker inherits its manifest threshold."""
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(
        metrics,
        cutoff,
        fp,
        abstention_threshold=0.35,
        source_kind_mix={"REAL_LIVE": 10},
        truth_tier_distribution={"PO_ASSERTED": 10},
    )
    _write_data_profile(tmp_path, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")

    active_config = tmp_path / "review-learning-active.yaml"
    active_config.write_text(
        "config_version: test-active-v1\n"
        "mode: RANKER_ACTIVE\n"
        "ranker:\n"
        "  mode: ACTIVE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOCPRO_REVIEW_LEARNING_CONFIG_PATH", str(active_config))
    monkeypatch.setenv("NOCPRO_REVIEW_RANKER_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("NOCPRO_GOVERNANCE_SIGNING_KEY", "secret123")
    # The test uses a synthetic DRAFT artifact and exercises Workspace wiring,
    # not production artifact approval.
    monkeypatch.setenv("NOCPRO_REVIEW_RANKER_ENFORCE_GOVERNANCE", "0")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("NOCPRO_REVIEW_RANKER_ABSTENTION_THRESHOLD", raising=False)

    from nocpro_api.workspace import Workspace
    ws = Workspace()
    try:
        assert ws.review_learning.abstention_threshold == 0.35
    finally:
        ws.close()


def test_production_rejects_unsigned_runtime_threshold_override(monkeypatch):
    """A deployment must not alter the threshold that artifact governance signed."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("NOCPRO_REVIEW_RANKER_ENFORCE_GOVERNANCE", "1")
    monkeypatch.setenv("NOCPRO_REVIEW_RANKER_ABSTENTION_THRESHOLD", "0.25")

    from nocpro_api.workspace import Workspace

    with pytest.raises(RuntimeError, match="signed artifact abstention threshold"):
        Workspace()


def test_production_rejects_missing_data_profile(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    _write_data_profile(tmp_path, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")
    (tmp_path / "data_profile.json").unlink()
    with pytest.raises(FileNotFoundError, match="(missing mandatory data profile|REQUIRED_BUNDLE_FILE_MISSING: data_profile.json)"):
        load_production_ranker_artifact(tmp_path, signing_key="secret123")


def test_production_rejects_data_profile_checksum_mismatch(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    _write_data_profile(tmp_path, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")
    (tmp_path / "data_profile.json").write_text('{"tampered": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="(SHA-256 checksum mismatch|data_profile.json sha256 mismatch|data_profile.json fingerprint does not match)"):
        load_production_ranker_artifact(tmp_path, signing_key="secret123")


def test_production_rejects_data_profile_missing_from_bundle_checksums(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    manifest = _make_manifest(metrics, cutoff, fp)
    _write_data_profile(tmp_path, fp)
    save_ranker_artifact(model, manifest, tmp_path)
    # Remove data_profile.json from manifest bundle_checksums manually
    man_path = tmp_path / "manifest.json"
    with open(man_path, "r", encoding="utf-8") as f:
        man_data = json.load(f)
    man_data["bundle_checksums"].pop("data_profile.json", None)
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man_data, f)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")
    with pytest.raises(ValueError, match="data_profile.json is missing from manifest bundle_checksums"):
        load_production_ranker_artifact(tmp_path, signing_key="secret123")


def test_production_rejects_data_profile_lineage_overlap(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    dp_data = {
        "profile_version": "v1",
        "created_at": "2026-09-10T00:00:00Z",
        "total_groups": 10,
        "feature_count": 43,
        "lineage_overlap_detected": True,
        "temporal_inversion_detected": False,
        "corpus_fingerprint": fp,
    }
    manifest = _make_manifest(metrics, cutoff, fp, data_profile_fingerprint=canonical_fingerprint(dp_data))
    (tmp_path / "data_profile.json").write_text(json.dumps(dp_data), encoding="utf-8")
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")
    with pytest.raises(ValueError, match="data_profile.json reports lineage_overlap_detected=True"):
        load_production_ranker_artifact(tmp_path, signing_key="secret123")


def test_production_rejects_data_profile_temporal_inversion(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    dp_data = {
        "profile_version": "v1",
        "created_at": "2026-09-10T00:00:00Z",
        "total_groups": 10,
        "feature_count": 43,
        "lineage_overlap_detected": False,
        "temporal_inversion_detected": True,
        "corpus_fingerprint": fp,
    }
    manifest = _make_manifest(metrics, cutoff, fp, data_profile_fingerprint=canonical_fingerprint(dp_data))
    (tmp_path / "data_profile.json").write_text(json.dumps(dp_data), encoding="utf-8")
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")
    with pytest.raises(ValueError, match="data_profile.json reports temporal_inversion_detected=True"):
        load_production_ranker_artifact(tmp_path, signing_key="secret123")


def test_production_rejects_data_profile_corpus_mismatch(trained_ranker, tmp_path):
    model, metrics, cutoff, fp = trained_ranker
    dp_data = {
        "profile_version": "v1",
        "created_at": "2026-09-10T00:00:00Z",
        "total_groups": 10,
        "feature_count": 43,
        "lineage_overlap_detected": False,
        "temporal_inversion_detected": False,
        "corpus_fingerprint": "mismatched_corpus_fingerprint_xyz",
    }
    manifest = _make_manifest(metrics, cutoff, fp, data_profile_fingerprint=canonical_fingerprint(dp_data))
    (tmp_path / "data_profile.json").write_text(json.dumps(dp_data), encoding="utf-8")
    save_ranker_artifact(model, manifest, tmp_path)
    sign_ranker_artifact(tmp_path, principal_id="lead_eng", signing_key="secret123")
    with pytest.raises(ValueError, match="corpus_fingerprint does not match"):
        load_production_ranker_artifact(tmp_path, signing_key="secret123")

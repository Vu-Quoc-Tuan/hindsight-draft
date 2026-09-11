from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import HTTPException
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nocpro_api.persistence.models import Base
from nocpro_api.persistence.repository import SnapshotRepository
from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.review_principal import (
    ReviewerPrincipal,
    ReviewReasonPolicyUnavailable,
    get_reviewer_principal,
    load_reason_policy,
)
from review_learning import (
    CandidateExposure,
    ReviewDecision,
    TruthTier,
    compute_candidate_fingerprint,
    compute_candidate_set_fingerprint,
    canonical_fingerprint,
)
from review_learning.contracts import ImmutableReviewConflict, ReviewDomainForbidden


@dataclass
class DummyJobView:
    job_id: str
    chain_id: str
    result: Any
    identity: dict
    review_domain: str = "IP_NETWORK"


@pytest.fixture
async def sqlite_repo(tmp_path: Path):
    db_file = tmp_path / "audit_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    repo = SnapshotRepository(sm)
    yield repo
    await engine.dispose()


def test_ranking_audit_cryptographically_bound_into_fingerprint():
    """Verify modifying ranking_status, model_score, margin, threshold, displayed_rank changes candidate_fingerprint."""
    base_audit = {
        "ranking_status": "RERANKED",
        "model_score": 0.85,
        "margin": 0.25,
        "abstention_threshold": 0.1,
        "abstention_reason": None,
        "ranker_version": "v1",
        "artifact_fingerprint": "art_fp_123",
    }
    fp_base = compute_candidate_fingerprint(
        candidate_id="c1",
        operation="REMOVE",
        feature_fingerprint="feat_fp_1",
        displayed_rank=1,
        ranking_audit=base_audit,
        original_rank=0,
    )

    # 1. Tamper with ranking_status
    audit_tampered_status = dict(base_audit, ranking_status="ABSTAINED")
    fp_status = compute_candidate_fingerprint(
        candidate_id="c1",
        operation="REMOVE",
        feature_fingerprint="feat_fp_1",
        displayed_rank=1,
        ranking_audit=audit_tampered_status,
        original_rank=0,
    )
    assert fp_base != fp_status

    # 2. Tamper with model_score
    audit_tampered_score = dict(base_audit, model_score=0.99)
    fp_score = compute_candidate_fingerprint(
        candidate_id="c1",
        operation="REMOVE",
        feature_fingerprint="feat_fp_1",
        displayed_rank=1,
        ranking_audit=audit_tampered_score,
        original_rank=0,
    )
    assert fp_base != fp_score

    # 3. Tamper with margin
    audit_tampered_margin = dict(base_audit, margin=0.5)
    fp_margin = compute_candidate_fingerprint(
        candidate_id="c1",
        operation="REMOVE",
        feature_fingerprint="feat_fp_1",
        displayed_rank=1,
        ranking_audit=audit_tampered_margin,
        original_rank=0,
    )
    assert fp_base != fp_margin

    # 4. Tamper with displayed_rank
    fp_rank = compute_candidate_fingerprint(
        candidate_id="c1",
        operation="REMOVE",
        feature_fingerprint="feat_fp_1",
        displayed_rank=2,
        ranking_audit=base_audit,
        original_rank=0,
    )
    assert fp_base != fp_rank

    # 5. Tamper with abstention_threshold
    audit_tampered_thresh = dict(base_audit, abstention_threshold=0.3)
    fp_thresh = compute_candidate_fingerprint(
        candidate_id="c1",
        operation="REMOVE",
        feature_fingerprint="feat_fp_1",
        displayed_rank=1,
        ranking_audit=audit_tampered_thresh,
        original_rank=0,
    )
    assert fp_base != fp_thresh


@pytest.mark.anyio
async def test_replay_with_tampered_ranking_audit_raises_immutable_conflict(sqlite_repo):
    """Verify repository replay enforces immutability when candidate ranking audit is tampered."""
    service = ReviewLearningService(repository=sqlite_repo)

    cand1 = {
        "candidate_id": "c1",
        "operation": "REMOVE",
        "hard_gate_passed": True,
        "recommended": True,
        "raw_score": 0.85,
        "partition_delta": {"removed_alarms": ["a2"]},
    }
    cand2 = {
        "candidate_id": "c2",
        "operation": "SPLIT",
        "hard_gate_passed": True,
        "recommended": False,
        "raw_score": 0.40,
        "partition_delta": {"partitions": [["a1"], ["a2"]]},
    }
    job_view = DummyJobView(
        job_id="job_audit_test_1",
        chain_id="chain_1",
        result={"chain_id": "chain_1", "recommendations": [cand1], "evaluated_candidates": [cand1, cand2]},
        identity={"snapshot_id": "s1", "snapshot_version": "v1"},
    )

    # 1. Freeze initial bundle
    session, exposures = service.prepare_review_bundle(
        job_id="job_audit_test_1",
        job_view=job_view,
        package=None,
    )
    await sqlite_repo.persist_review_bundle(session, exposures)

    # 2. Idempotent replay succeeds
    await sqlite_repo.persist_review_bundle(session, exposures)

    # 3. Tampered replay with altered ranking audit on candidate exposure raises ImmutableReviewConflict
    tampered_audit = dict(exposures[0].deterministic_context.get("ranking_audit", {}))
    tampered_audit["model_score"] = 0.9999
    tampered_fp = compute_candidate_fingerprint(
        candidate_id=exposures[0].candidate_id,
        operation=exposures[0].operation,
        feature_fingerprint=exposures[0].feature_fingerprint,
        displayed_rank=exposures[0].displayed_rank,
        ranking_audit=tampered_audit,
        original_rank=exposures[0].original_rank,
        delta=exposures[0].deterministic_context.get("partition_delta"),
    )

    import dataclasses
    tampered_exp = dataclasses.replace(
        exposures[0],
        candidate_fingerprint=tampered_fp,
    )
    tampered_exposures = [tampered_exp, exposures[1]]

    with pytest.raises(ImmutableReviewConflict, match="Conflict: persisted review exposures"):
        await sqlite_repo.persist_review_bundle(session, tampered_exposures)


@pytest.mark.anyio
async def test_open_access_feedback_is_always_po_asserted(sqlite_repo):
    """Verify:
    During the pre-auth phase every local actor can submit and every review is
    explicitly labeled PO_ASSERTED. Role-based policy will be introduced later.
    """
    service = ReviewLearningService(repository=sqlite_repo)

    cand1 = {
        "candidate_id": "c1",
        "operation": "REMOVE",
        "hard_gate_passed": True,
        "recommended": True,
        "partition_delta": {"removed_alarms": ["a2"]},
    }
    job_view = DummyJobView(
        job_id="job_role_auth_1",
        chain_id="chain_1",
        result={"chain_id": "chain_1", "recommendations": [cand1], "evaluated_candidates": [cand1]},
        identity={"snapshot_id": "s1", "snapshot_version": "v1"},
        review_domain="IP_NETWORK",
    )
    await service.freeze_review_bundle(job_id="job_role_auth_1", job_view=job_view, package=None)

    # A formerly read-only role is permitted in the open-access phase.
    ro_principal = ReviewerPrincipal(
        subject="auditor_bob",
        role="READONLY_OPERATOR",
        domain_scope=("IP_NETWORK",),
        auth_type="TRUSTED_PROXY",
    )
    assert ro_principal.is_read_only is True
    fb_ro = await service.record_feedback(
        job_id="job_role_auth_1",
        submission={"candidate_id": "c1", "decision": ReviewDecision.APPROVE, "confidence": 1.0, "reason": "Test note"},
        principal=ro_principal,
    )
    assert fb_ro.truth_tier == TruthTier.PO_ASSERTED

    # Operator role is also accepted and remains PO_ASSERTED.
    op_principal = ReviewerPrincipal(
        subject="op_dave",
        role="OPERATOR",
        domain_scope=("IP_NETWORK",),
        auth_type="TRUSTED_PROXY",
    )
    fb_op = await service.record_feedback(
        job_id="job_role_auth_1",
        submission={"candidate_id": "c1", "decision": ReviewDecision.APPROVE, "confidence": 0.9, "reason": "Operator verification"},
        principal=op_principal,
    )
    assert fb_op.truth_tier == TruthTier.PO_ASSERTED

    # Product owner is represented identically at the current truth boundary.
    po_principal = ReviewerPrincipal(
        subject="po_alice",
        role="PRODUCT_OWNER",
        domain_scope=("IP_NETWORK",),
        auth_type="TRUSTED_PROXY",
    )
    assert po_principal.can_assert_po_truth is True
    fb_po = await service.record_feedback(
        job_id="job_role_auth_1",
        submission={"candidate_id": "c1", "decision": ReviewDecision.APPROVE, "confidence": 1.0, "reason": "PO override"},
        principal=po_principal,
    )
    assert fb_po.truth_tier == TruthTier.PO_ASSERTED

    # Supersession remains append-only and has the same current tier.
    po2_principal = ReviewerPrincipal(
        subject="po_bob",
        role="PRINCIPAL_OPERATOR",
        domain_scope=("IP_NETWORK",),
        auth_type="TRUSTED_PROXY",
    )
    fb_po2 = await service.supersede_feedback(
        job_id="job_role_auth_1",
        supersedes_feedback_id=fb_po.feedback_id,
        submission={"candidate_id": "c1", "decision": "REJECT", "confidence": 1.0, "reason": "PO override 2"},
        principal=po2_principal,
    )
    assert fb_po2.truth_tier == TruthTier.PO_ASSERTED


def test_local_dev_principal_is_open_access_po_with_wildcard_scope(monkeypatch):
    from starlette.datastructures import Headers
    from unittest.mock import MagicMock

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("REVIEW_IDENTITY_MODE", raising=False)
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = Headers({})

    principal = get_reviewer_principal(mock_request)

    assert principal.role == "PRODUCT_OWNER"
    assert principal.domain_scope == ("*",)


def test_missing_or_invalid_reason_policy_fails_closed(tmp_path):
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ReviewReasonPolicyUnavailable, match="not found"):
        load_reason_policy(missing)

    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("policy_version: review-reasons-v1\nreasons_by_decision: []\n", encoding="utf-8")
    with pytest.raises(ReviewReasonPolicyUnavailable, match="reasons_by_decision"):
        load_reason_policy(malformed)


@pytest.mark.anyio
async def test_trusted_proxy_production_headers_fail_closed(monkeypatch):
    """Verify TRUSTED_PROXY mode in production fails closed:
    - Missing X-User-Roles raises 401 Unauthorized
    - Missing X-Domain-Scope raises 403 Forbidden
    """
    from starlette.datastructures import Headers
    from unittest.mock import MagicMock

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REVIEW_IDENTITY_MODE", "TRUSTED_PROXY")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")

    # 1. Missing X-User-Roles raises 401
    mock_req_no_roles = MagicMock()
    mock_req_no_roles.client.host = "127.0.0.1"
    mock_req_no_roles.headers = Headers({
        "X-Forwarded-User": "alice_prod",
        "X-Domain-Scope": "IP_NETWORK",
    })
    with pytest.raises(HTTPException) as exc1:
        get_reviewer_principal(mock_req_no_roles)
    assert exc1.value.status_code == 401
    assert "Missing required X-User-Roles header" in exc1.value.detail

    # 2. Missing X-Domain-Scope raises 403
    mock_req_no_scope = MagicMock()
    mock_req_no_scope.client.host = "127.0.0.1"
    mock_req_no_scope.headers = Headers({
        "X-Forwarded-User": "alice_prod",
        "X-User-Roles": "PRODUCT_OWNER",
    })
    with pytest.raises(HTTPException) as exc2:
        get_reviewer_principal(mock_req_no_scope)
    assert exc2.value.status_code == 403
    assert "Missing required X-Domain-Scope header" in exc2.value.detail

    # 3. Present headers succeeds
    mock_req_ok = MagicMock()
    mock_req_ok.client.host = "127.0.0.1"
    mock_req_ok.headers = Headers({
        "X-Forwarded-User": "alice_prod",
        "X-User-Roles": "PRODUCT_OWNER",
        "X-Domain-Scope": "IP_NETWORK,IT_SERVICES",
    })
    p = get_reviewer_principal(mock_req_ok)
    assert p.subject == "alice_prod"
    assert p.role == "PRODUCT_OWNER"
    assert p.domain_scope == ("IP_NETWORK", "IT_SERVICES")


@pytest.mark.anyio
async def test_get_feedback_authorization_and_404(sqlite_repo):
    """Verify:
    1. Querying feedback for an unknown job_id raises KeyError -> 404.
    2. Querying feedback for an unauthorized domain raises ReviewDomainForbidden -> 403.
    3. Never silently returns 200 [] when unauthorized.
    """
    from nocpro_api.workspace import Workspace

    ws = Workspace()
    ws.repository = sqlite_repo
    ws.review_learning = ReviewLearningService(sqlite_repo)

    # 1. Unknown job_id raises KeyError (maps to 404 in FastAPI routes)
    p_ip = ReviewerPrincipal(
        subject="op_ip",
        role="OPERATOR",
        domain_scope=("IP_NETWORK",),
        auth_type="LOCAL_DEV",
    )
    with pytest.raises(KeyError, match="unknown review job_id 'job_nonexistent'"):
        await ws.list_operator_feedback(job_id="job_nonexistent", principal=p_ip)

    # 2. Freeze a real review job with domain 'OPTICAL'
    cand1 = {
        "candidate_id": "c1",
        "operation": "REMOVE",
        "hard_gate_passed": True,
        "recommended": True,
        "partition_delta": {"removed_alarms": ["a2"]},
    }
    job_view = DummyJobView(
        job_id="job_optical_1",
        chain_id="chain_opt_1",
        result={"chain_id": "chain_opt_1", "recommendations": [cand1], "evaluated_candidates": [cand1]},
        identity={"snapshot_id": "s1", "snapshot_version": "v1"},
        review_domain="OPTICAL",
    )
    ws.review_jobs.get = lambda jid: job_view
    await ws.review_learning.freeze_review_bundle(
        job_id="job_optical_1",
        job_view=job_view,
        package=None,
    )

    # Record feedback with authorized optical principal
    p_opt = ReviewerPrincipal(
        subject="op_opt",
        role="PRODUCT_OWNER",
        domain_scope=("OPTICAL",),
        auth_type="LOCAL_DEV",
    )
    await ws.record_operator_feedback(
        job_id="job_optical_1",
        payload={"candidate_id": "c1", "decision": "APPROVED", "reason": "Optical verified"},
        principal=p_opt,
    )

    # 3. Principal authorized for IP_NETWORK (but NOT OPTICAL) queries feedback:
    # Must raise ReviewDomainForbidden (maps to 403) and NOT return empty list!
    with pytest.raises(ReviewDomainForbidden, match="not authorized for review domain 'OPTICAL'"):
        await ws.list_operator_feedback(job_id="job_optical_1", principal=p_ip)

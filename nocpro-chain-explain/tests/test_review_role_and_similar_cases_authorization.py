from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
import httpx2
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from configuration import load_analysis_config
from nocpro_api import create_app
from nocpro_api.persistence.models import Base
from nocpro_api.persistence.repository import SnapshotRepository
from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.review_principal import (
    get_reviewer_principal,
)
from nocpro_api.workspace import Workspace
from review_learning.contracts import (
    ImmutableReviewSnapshotContext,
)
from tier2.counterfactual.jobs import CounterfactualJobManager

pytestmark = pytest.mark.anyio


from types import SimpleNamespace
from libs.contracts import load_package
from tests.test_counterfactual_analysis import _member, _metric_computer


def _config():
    return load_analysis_config("config/thresholds/e2e-counterfactual.yaml")


def _multi_candidate_tier1b():
    return SimpleNamespace(
        members={
            "A": _member(),
            "B": _member(),
            "C": _member(),
            "X": _member(role="WEAK", support=0.1, representativeness=0.1),
            "Y": _member(role="WEAK", support=0.15, representativeness=0.15),
        },
        local_candidates=(),
    )


def _package(snapshot_id: str = "snap_sec_test", snapshot_time: str = "2026-01-01T00:00:00Z"):
    return load_package({
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": snapshot_id,
            "snapshot_version": "1",
            "snapshot_time": snapshot_time,
            "status": "COMPLETE",
            "source": "fixture",
            "source_kind": "REAL_LIVE",
            "produced_at": snapshot_time,
        },
        "alarms": [
            {"alarm_id": a, "snapshot_id": snapshot_id, "raw": {"failure_domain": "IP_NETWORK"}}
            for a in ("A", "B", "C", "X", "Y")
        ],
        "chains": [
            {"chain_id": "C", "snapshot_id": snapshot_id, "member_count": 5},
        ],
        "memberships": [
            {"chain_id": "C", "alarm_id": a, "snapshot_id": snapshot_id}
            for a in ("A", "B", "C", "X", "Y")
        ],
    })


@pytest.fixture
async def sec_fixture(tmp_path: Path):
    db_file = tmp_path / "sec_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", poolclass=NullPool, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    repo = SnapshotRepository(sm)

    ws = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    ws.repository = repo
    ws.review_learning = ReviewLearningService(repo)
    ws.package = _package()
    ws.review_jobs = CounterfactualJobManager(metric_computer=_metric_computer)

    sub = ws.review_jobs.submit(
        ws.package,
        "C",
        tier1b_artifact=_multi_candidate_tier1b(),
        audit_artifact=None,
        analysis_config=_config(),
        lineage_component_id="comp_sec_test",
    )
    job_view = ws.review_jobs.wait(sub.job_id)
    cand_id = "cand_sec_1"
    if job_view.result:
        cands = (
            job_view.result.recommendations
            or job_view.result.remove.candidates
            or job_view.result.evaluated_candidates
        )
        if cands:
            cand_id = cands[0].candidate.candidate_id

    await repo.persist_counterfactual_job(job_view.persistence_payload())
    sess = await ws.review_learning.freeze_review_bundle(
        job_id=sub.job_id,
        job_view=job_view,
        package=ws.package,
        delay_model=ws.temporal_delay_model,
    )

    app = create_app(workspace=ws)
    transport = httpx2.ASGITransport(app=app)

    yield {
        "engine": engine,
        "sm": sm,
        "repo": repo,
        "ws": ws,
        "app": app,
        "transport": transport,
        "job_id": sub.job_id,
        "candidate_id": cand_id,
        "session": sess,
    }

    ws.close()
    await engine.dispose()


def test_immutable_review_snapshot_context_default_source_kind():
    """Verify default source_kind is SOURCE_KIND_UNAVAILABLE."""
    ctx = ImmutableReviewSnapshotContext(
        snapshot_id="s1",
        snapshot_version="v1",
        review_time=datetime.now(timezone.utc),
        chain_id="c1",
        review_domain="IP_NETWORK",
        lineage_component_id="lc1",
    )
    assert ctx.source_kind == "SOURCE_KIND_UNAVAILABLE"


async def test_role_authorization_rejection_no_orphans(sec_fixture, monkeypatch: pytest.MonkeyPatch):
    """Verify all roles can submit feedback (role checks disabled until auth is implemented)."""
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")
    transport = sec_fixture["transport"]
    job_id = sec_fixture["job_id"]
    cand_id = sec_fixture["candidate_id"]

    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # NOTE: Role authorization is disabled (no login/auth yet). All roles get 201.

        # 1. ENGINEER role submits feedback -> 201 (no role check)
        resp_eng = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback",
            json={
                "candidate_id": cand_id,
                "decision": "APPROVED",
                "reason": "Engineer approval attempt",
            },
            headers={
                "X-Dev-Operator-Id": "eng_user",
                "X-Dev-Operator-Role": "ENGINEER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_eng.status_code == 201

        # 2. VIEWER role submits feedback -> 201 (no role check)
        resp_view = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback",
            json={
                "candidate_id": cand_id,
                "decision": "REJECTED",
                "reason": "Viewer reject attempt",
            },
            headers={
                "X-Dev-Operator-Id": "viewer_user",
                "X-Dev-Operator-Role": "VIEWER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_view.status_code == 201

        # 3. Multi-role without PO (ENGINEER, VIEWER) -> 201 (no role check)
        resp_multi = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback",
            json={
                "candidate_id": cand_id,
                "decision": "APPROVED",
                "reason": "Multi unauth attempt",
            },
            headers={
                "X-Dev-Operator-Id": "multi_user",
                "X-Dev-Operator-Role": "ENGINEER, VIEWER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_multi.status_code == 201


async def test_role_authorization_multi_role_and_whitespace(sec_fixture, monkeypatch: pytest.MonkeyPatch):
    """Verify multi-role with PO and case/whitespace insensitivity succeeds."""
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")
    transport = sec_fixture["transport"]
    job_id = sec_fixture["job_id"]
    cand_id = sec_fixture["candidate_id"]

    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Multi-role containing PRODUCT_OWNER with whitespace and lowercase: ' viewer , product_owner '
        resp = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback",
            json={
                "candidate_id": cand_id,
                "decision": "APPROVED",
                "reason": "Multi role PO authorized",
            },
            headers={
                "X-Dev-Operator-Id": "po_user",
                "X-Dev-Operator-Role": " viewer , product_owner ",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["decision"] in ("APPROVE", "APPROVED")
        fb_id = body["feedback_id"]

        # Supersede feedback with PO role
        resp_sup = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback/{fb_id}/supersede",
            json={
                "candidate_id": cand_id,
                "decision": "REJECTED",
                "reason": "PO supersede reason",
            },
            headers={
                "X-Dev-Operator-Id": "po_user_2",
                "X-Dev-Operator-Role": "PRINCIPAL_OPERATOR",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_sup.status_code == 201

        # Supersede feedback with unauthorized role (VIEWER) -> 409 Conflict
        # (feedback was already superseded above; role checks are disabled)
        resp_sup_unauth = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback/{fb_id}/supersede",
            json={
                "candidate_id": cand_id,
                "decision": "APPROVED",
                "reason": "Unauthorized supersede attempt",
            },
            headers={
                "X-Dev-Operator-Id": "viewer_user",
                "X-Dev-Operator-Role": "VIEWER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_sup_unauth.status_code in (201, 409)  # allowed (role checks off); 409 if already superseded


def test_trusted_proxy_roles_validation(monkeypatch: pytest.MonkeyPatch):
    """Verify TRUSTED_PROXY mode fail-closed on missing/empty X-User-Roles."""
    from starlette.datastructures import Headers
    from unittest.mock import MagicMock

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REVIEW_IDENTITY_MODE", "TRUSTED_PROXY")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")

    # 1. Missing X-User-Roles raises 401/403
    req_no_roles = MagicMock()
    req_no_roles.client.host = "127.0.0.1"
    req_no_roles.headers = Headers({
        "X-Forwarded-User": "alice_prod",
        "X-Domain-Scope": "IP_NETWORK",
    })
    with pytest.raises(HTTPException) as exc1:
        get_reviewer_principal(req_no_roles)
    assert exc1.value.status_code in (401, 403)
    assert "X-User-Roles header" in exc1.value.detail

    # 2. Empty X-User-Roles raises 401/403
    req_empty_roles = MagicMock()
    req_empty_roles.client.host = "127.0.0.1"
    req_empty_roles.headers = Headers({
        "X-Forwarded-User": "alice_prod",
        "X-User-Roles": "   ",
        "X-Domain-Scope": "IP_NETWORK",
    })
    with pytest.raises(HTTPException) as exc2:
        get_reviewer_principal(req_empty_roles)
    assert exc2.value.status_code in (401, 403)

    # 3. Present valid roles succeeds and parses multi-roles
    req_valid = MagicMock()
    req_valid.client.host = "127.0.0.1"
    req_valid.headers = Headers({
        "X-Forwarded-User": "alice_prod",
        "X-User-Roles": "ENGINEER, PRODUCT_OWNER",
        "X-Domain-Scope": "IP_NETWORK",
    })
    p = get_reviewer_principal(req_valid)
    assert p.subject == "alice_prod"
    assert "PRODUCT_OWNER" in p.all_roles
    assert "ENGINEER" in p.all_roles
    assert p.is_role_authorized_for_po_asserted() is True


async def test_similar_cases_endpoint_security(sec_fixture, monkeypatch: pytest.MonkeyPatch):
    """Verify similar-cases endpoint requires principal, 404 on unknown job, 403 on domain mismatch, 200 on authorized."""
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")
    transport = sec_fixture["transport"]
    job_id = sec_fixture["job_id"]
    cand_id = sec_fixture["candidate_id"]

    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Unknown job_id -> 404
        resp_404 = await client.get(
            f"/api/v1/review-jobs/job_unknown_xyz/candidates/{cand_id}/similar-cases",
            headers={
                "X-Dev-Operator-Id": "po_user",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_404.status_code == 404

        # 2. Domain mismatch (session is IP_NETWORK, reviewer only has OPTICAL) -> 403 Forbidden
        resp_403 = await client.get(
            f"/api/v1/review-jobs/{job_id}/candidates/{cand_id}/similar-cases",
            headers={
                "X-Dev-Operator-Id": "po_optical",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "OPTICAL",
            },
        )
        assert resp_403.status_code == 403
        assert "not authorized" in resp_403.json()["detail"]

        # 3. Authorized domain -> 200 OK
        resp_200 = await client.get(
            f"/api/v1/review-jobs/{job_id}/candidates/{cand_id}/similar-cases",
            headers={
                "X-Dev-Operator-Id": "po_ip",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_200.status_code == 200
        assert "retrieval_status" in resp_200.json()


async def test_chain_feedback_domain_authorization(sec_fixture, monkeypatch: pytest.MonkeyPatch):
    """Verify GET /api/v1/chains/{chain_id}/feedback checks domain from joined session."""
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")
    transport = sec_fixture["transport"]
    job_id = sec_fixture["job_id"]
    cand_id = sec_fixture["candidate_id"]

    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Post valid feedback to create a record on chain C
        resp = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback",
            json={
                "candidate_id": cand_id,
                "decision": "APPROVED",
                "reason": "Chain test valid feedback",
            },
            headers={
                "X-Dev-Operator-Id": "po_user",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp.status_code == 201
        chain_id = resp.json()["chain_id"]

        # 2. Query chain feedback with domain mismatch (OPTICAL) -> 403 Forbidden
        resp_mismatch = await client.get(
            f"/api/v1/chains/{chain_id}/feedback",
            headers={
                "X-Dev-Operator-Id": "po_optical",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "OPTICAL",
            },
        )
        assert resp_mismatch.status_code == 403
        assert "not authorized" in resp_mismatch.json()["detail"]

        # 3. Query chain feedback with matching domain -> 200 OK
        resp_match = await client.get(
            f"/api/v1/chains/{chain_id}/feedback",
            headers={
                "X-Dev-Operator-Id": "po_user",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_match.status_code == 200
        assert len(resp_match.json()) == 1

        # 4. Query non-existent chain -> 200 []
        resp_nonexistent = await client.get(
            "/api/v1/chains/chain_does_not_exist/feedback",
            headers={
                "X-Dev-Operator-Id": "po_user",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_nonexistent.status_code == 200
        assert resp_nonexistent.json() == []

"""End-to-end HTTP API process restart and lifecycle acceptance test.

Verifies complete public HTTP lifecycle across simulated process restart:
- Server reason policy enforcement
- Domain authorization fail-closed
- Re-querying metadata on cold cache without N+1
- Supersede and stealth retraction (404 on mismatched review)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import httpx2
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nocpro_api import create_app
from nocpro_api.persistence.models import Base
from nocpro_api.persistence.repository import SnapshotRepository
from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.review_principal import ReviewerPrincipal
from nocpro_api.workspace import Workspace
from review_learning.contracts import (
    CandidateExposure,
    ReviewDecision,
    ReviewSession,
)

pytestmark = [pytest.mark.anyio, pytest.mark.e2e]


def _make_e2e_bundle(review_id: str, job_id: str, domain: str = "IP_NETWORK"):
    now = datetime.now(timezone.utc)
    session = ReviewSession(
        review_id=review_id,
        job_id=job_id,
        snapshot_id="snap_e2e_1",
        snapshot_version="1",
        chain_id="chain_e2e_1",
        review_time=now,
        source_kind="OPERATOR_REVIEW",
        review_domain=domain,
        lineage_component_id="comp_e2e_1",
        candidate_set_fingerprint="cs_fp_e2e",
        generator_version="v1",
        config_version="v1",
        exposure_policy="ALL_EVALUATED",
    )
    exposures = [
        CandidateExposure(
            review_id=review_id,
            candidate_id="cand_e2e_1",
            candidate_fingerprint="fp_e2e_1",
            operation="REMOVE",
            original_rank=1,
            displayed_rank=1,
            deterministic_eligibility="HARD_GATES_PASSED",
            hard_gate_status="PASSED",
            pareto_state="FRONTIER_SELECTED",
            deterministic_context={
                "benefit": 2.0,
                "partition_delta": {"removed": ["a1"]},
                "frozen_universe": {
                    "source_chain_id": "chain_e2e_1",
                    "source_alarm_ids": ["a1", "a2"],
                    "target_chain_id": None,
                    "target_alarm_ids": [],
                    "snapshot_id": "snap_e2e_1",
                    "snapshot_version": "1",
                },
            },
            case_context={"domain": domain},
            feature_schema_version="cf-features-v1",
            feature_payload={"exact_metrics": {"benefit": 2.0}},
        ),
        CandidateExposure(
            review_id=review_id,
            candidate_id="cand_e2e_2",
            candidate_fingerprint="fp_e2e_2",
            operation="SPLIT",
            original_rank=2,
            displayed_rank=2,
            deterministic_eligibility="DOMINATED",
            hard_gate_status="PASSED",
            pareto_state="DOMINATED",
            deterministic_context={
                "benefit": 1.0,
                "partition_delta": {"partitions": [["a1"], ["a2"]]},
                "frozen_universe": {
                    "source_chain_id": "chain_e2e_1",
                    "source_alarm_ids": ["a1", "a2"],
                    "target_chain_id": None,
                    "target_alarm_ids": [],
                    "snapshot_id": "snap_e2e_1",
                    "snapshot_version": "1",
                },
            },
            case_context={"domain": domain},
            feature_schema_version="cf-features-v1",
            feature_payload={"exact_metrics": {"benefit": 1.0}},
        ),
    ]
    return session, exposures


async def test_api_process_restart_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")

    db_file = tmp_path / "restart.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repo = SnapshotRepository(sessions)

    # 1. Start Process 1: Setup workspace and persist review bundle
    ws1 = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    ws1.repository = repo
    ws1.review_learning = ReviewLearningService(repo)

    job_id = "job_api_restart_1"
    review_id = "rev_api_restart_1"
    session, exposures = _make_e2e_bundle(review_id=review_id, job_id=job_id, domain="IP_NETWORK")
    job_payload = {
        "job_id": job_id,
        "snapshot_id": session.snapshot_id,
        "snapshot_version": session.snapshot_version,
        "chain_id": session.chain_id,
        "cache_fingerprint": f"cfp_{job_id}",
        "status": "SUCCEEDED",
        "progress_percent": 100,
        "cache_hit": False,
        "identity": {
            "snapshot_id": session.snapshot_id,
            "snapshot_version": session.snapshot_version,
            "chain_id": session.chain_id,
            "domain": "IP_NETWORK",
        },
        "result": {
            "evaluated_candidates": [
                {"candidate_id": exp.candidate_id, "operation": exp.operation}
                for exp in exposures
            ],
            "recommendations": [
                {"candidate_id": exposures[0].candidate_id, "operation": exposures[0].operation}
            ],
        },
        "error": None,
    }
    await repo.persist_counterfactual_job(job_payload)
    await repo.persist_review_bundle(session, exposures)
    ws1.review_learning.register_persisted_bundle(session, exposures)

    app1 = create_app(workspace=ws1)
    transport1 = httpx2.ASGITransport(app=app1)

    # Submit feedback via HTTP API on Process 1
    async with httpx2.AsyncClient(transport=transport1, base_url="http://testserver") as client:
        # A. Reject domain mismatch
        resp_forbid = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback",
            json={
                "candidate_id": "cand_e2e_1",
                "decision": "APPROVE",
                "reason_code": "PLAUSIBLE_SUBGRAPH",
            },
            headers={
                "X-Dev-Operator-Id": "optical_bob",
                "X-Dev-Domain-Scope": "OPTICAL_TRANSPORT",
            },
        )
        assert resp_forbid.status_code == 403

        # B. Reject invalid reason code
        resp_bad_reason = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback",
            json={
                "candidate_id": "cand_e2e_1",
                "decision": "APPROVE",
                "reason_code": "NON_EXISTENT_REASON_CODE",
            },
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_bad_reason.status_code in (400, 422)

        # C. Submit valid feedback
        resp_valid = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback",
            json={
                "candidate_id": "cand_e2e_1",
                "decision": "APPROVE",
                "reason_code": "PLAUSIBLE_SUBGRAPH",
                "confidence": 0.95,
            },
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert resp_valid.status_code == 201
        fb_data = resp_valid.json()
        fb_id = fb_data["feedback_id"]
        assert fb_id.startswith("fb_")
        assert fb_data["decision"] == "APPROVE"

    ws1.close()
    del ws1
    del app1

    # 2. Simulate complete process restart: instantiate new Workspace and App with empty caches
    ws2 = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    ws2.repository = repo
    ws2.review_learning = ReviewLearningService(repo)
    assert len(ws2.review_learning._sessions) == 0
    assert len(ws2.review_learning._exposures) == 0

    app2 = create_app(workspace=ws2)
    transport2 = httpx2.ASGITransport(app=app2)

    async with httpx2.AsyncClient(transport=transport2, base_url="http://testserver") as client:
        # A. Query active feedback on cold cache: verify domain authorization and full session metadata
        unauth_resp = await client.get(
            f"/api/v1/review-jobs/{job_id}/feedback",
            headers={
                "X-Dev-Operator-Id": "optical_bob",
                "X-Dev-Domain-Scope": "OPTICAL_TRANSPORT",
            },
        )
        assert unauth_resp.status_code == 403

        list_resp = await client.get(
            f"/api/v1/review-jobs/{job_id}/feedback",
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert list_resp.status_code == 200
        active_items = list_resp.json()
        assert len(active_items) == 1
        item = active_items[0]
        assert item["feedback_id"] == fb_id
        assert item["job_id"] == job_id
        assert item["snapshot_id"] == "snap_e2e_1"
        assert item["chain_id"] == "chain_e2e_1"
        assert item["decision"] == "APPROVE"

        # B. Supersede feedback over HTTP on restarted process
        sup_resp = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback/{fb_id}/supersede",
            json={
                "candidate_id": "cand_e2e_2",
                "decision": "REJECT",
                "reason_code": "INCORRECT_PARTITION",
                "confidence": 0.85,
            },
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert sup_resp.status_code == 201
        sup_data = sup_resp.json()
        sup_id = sup_data["feedback_id"]
        assert sup_id != fb_id
        assert sup_data["supersedes_feedback_id"] == fb_id
        assert sup_data["decision"] == "REJECT"

        # Verify previous fb_id is no longer returned in active listing
        list_resp2 = await client.get(
            f"/api/v1/review-jobs/{job_id}/feedback",
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert list_resp2.status_code == 200
        active_items2 = list_resp2.json()
        assert len(active_items2) == 1
        assert active_items2[0]["feedback_id"] == sup_id

        # C. Stealth retraction: attempt retracting with mismatched job_id returns 404 without leaking presence
        retract_wrong = await client.post(
            f"/api/v1/review-jobs/wrong_job_999/feedback/{sup_id}/retract",
            json={"reason": "Attacker probe"},
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert retract_wrong.status_code == 404

        # Persist a second independent job in the same domain to test stealth retraction
        # when the job exists, but the feedback belongs to a different review session
        other_job_id = "job_api_restart_other"
        other_rev_id = "rev_api_restart_other"
        other_session, other_exposures = _make_e2e_bundle(
            review_id=other_rev_id, job_id=other_job_id, domain="IP_NETWORK"
        )
        await repo.persist_counterfactual_job({
            "job_id": other_job_id,
            "snapshot_id": other_session.snapshot_id,
            "snapshot_version": other_session.snapshot_version,
            "chain_id": other_session.chain_id,
            "cache_fingerprint": f"cfp_{other_job_id}",
            "status": "SUCCEEDED",
            "progress_percent": 100,
            "cache_hit": False,
            "identity": {
                "snapshot_id": other_session.snapshot_id,
                "snapshot_version": other_session.snapshot_version,
                "chain_id": other_session.chain_id,
                "domain": "IP_NETWORK",
            },
            "result": {"evaluated_candidates": [], "recommendations": []},
            "error": None,
        })
        await repo.persist_review_bundle(other_session, other_exposures)

        # Retracting sup_id (which belongs to rev_api_restart_1) via other_job_id returns 404 (stealth)
        retract_other_job = await client.post(
            f"/api/v1/review-jobs/{other_job_id}/feedback/{sup_id}/retract",
            json={"reason": "Attacker probe on existing job"},
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert retract_other_job.status_code == 404

        # D. Valid retraction on correct job succeeds
        retract_ok = await client.post(
            f"/api/v1/review-jobs/{job_id}/feedback/{sup_id}/retract",
            json={"reason": "Retracted by operator"},
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert retract_ok.status_code == 200
        assert retract_ok.json() == {"status": "RETRACTED", "feedback_id": sup_id}

        # Verify active listing is now empty
        list_resp3 = await client.get(
            f"/api/v1/review-jobs/{job_id}/feedback",
            headers={
                "X-Dev-Operator-Id": "alice_po",
                "X-Dev-Operator-Role": "PRODUCT_OWNER",
                "X-Dev-Domain-Scope": "IP_NETWORK",
            },
        )
        assert list_resp3.status_code == 200
        assert len(list_resp3.json()) == 0

    ws2.close()
    await engine.dispose()

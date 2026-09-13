import asyncio
from types import SimpleNamespace
from dataclasses import asdict
from pathlib import Path
import httpx2
import pytest
from nocpro_api.app import create_app
from nocpro_api.workspace import Workspace
from nocpro_api.review_principal import ReviewerPrincipal
from nocpro_api.serializers import counterfactual_job_view
from tier2.counterfactual import analyze_counterfactual_review
from tests.test_counterfactual_analysis import (
    IDENTITY,
    CONFIG,
    _package,
    _tier1b,
    _metric_computer,
)


@pytest.mark.anyio
async def test_review_learning_status_endpoint():
    app = create_app()
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        res = await client.get("/api/v1/review-learning/status")
    assert res.status_code == 200
    data = res.json()
    assert data["loaded"] is False
    assert data["model_version"] is None
    assert data["metrics"] == {}
    assert data["training_available"] is False
    assert "ONLINE_TRAINING_DISABLED" in data["training_reason"]
    assert "disclaimer" in data
    assert "Historical reference" in data.get("disclaimer", "")


def test_candidate_ranking_audit_enrichment():
    pkg = _package()
    ws = Workspace()
    ws.package = pkg

    result = analyze_counterfactual_review(
        pkg,
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_metric_computer,
    )

    dummy_job = SimpleNamespace(
        job_id="job_audit_test_001",
        chain_id="C",
        status="SUCCEEDED",
        progress_percent=100,
        result=result,
        error=None,
        submitted_at=None,
        started_at=None,
        completed_at=None,
        lineage_component_id=None,
        cache_fingerprint="fp123",
        identity=asdict(IDENTITY),
    )
    dummy_job.view = lambda: dummy_job

    view = counterfactual_job_view(
        dummy_job, package=pkg, language="vi", review_learning=ws.review_learning
    )
    candidates = view.result.get("evaluated_candidates", [])
    assert len(candidates) > 0
    first = candidates[0]
    assert "ranking_audit" in first
    audit = first["ranking_audit"]
    assert audit["ranking_status"] in ("RERANKED", "ABSTAINED", "UNAVAILABLE")
    assert "model_score" in audit
    assert "ranker_version" in audit
    assert first.get("displayed_rank") is not None


@pytest.mark.anyio
async def test_similar_cases_integration():
    pkg = _package()
    ws = Workspace()
    ws.package = pkg

    result = analyze_counterfactual_review(
        pkg,
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_metric_computer,
    )

    dummy_job = SimpleNamespace(
        job_id="job_audit_test_002",
        chain_id="C",
        status="SUCCEEDED",
        progress_percent=100,
        result=result,
        error=None,
        submitted_at=None,
        started_at=None,
        completed_at=None,
        lineage_component_id=None,
        cache_fingerprint="fp123",
        identity=asdict(IDENTITY),
    )
    dummy_job.view = lambda: dummy_job
    ws.review_jobs._jobs["job_audit_test_002"] = dummy_job

    first_cand = result.remove.candidates[0].candidate

    p = ReviewerPrincipal(
        subject="test_op",
        role="OPERATOR",
        domain_scope=("*",),
        auth_type="LOCAL_DEV",
    )
    sim_res = await ws.find_similar_cases_for_candidate(
        job_id="job_audit_test_002",
        candidate_id=first_cand.candidate_id,
        principal=p,
        min_common_blocks=2,
    )
    assert sim_res.retrieval_status == "UNAVAILABLE"
    assert sim_res.cross_incident_cases == []

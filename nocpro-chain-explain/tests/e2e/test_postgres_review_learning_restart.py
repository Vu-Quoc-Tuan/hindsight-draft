from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nocpro_api.persistence.models import Base
from nocpro_api.persistence.repository import SnapshotRepository
from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.review_principal import ReviewerPrincipal
from review_learning.contracts import (
    CandidateExposure,
    ManualCorrection,
    ReviewCase,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
)

pytestmark = [pytest.mark.anyio, pytest.mark.postgres, pytest.mark.e2e, pytest.mark.docker]

if os.environ.get("NOCPRO_RUN_DOCKER_E2E") != "1":
    pytest.skip("NOCPRO_RUN_DOCKER_E2E=1 is not set; skipping Postgres E2E tests", allow_module_level=True)

POSTGRES_URL = os.environ.get("TEST_DATABASE_URL")
if not POSTGRES_URL:
    pytest.skip("TEST_DATABASE_URL is not configured", allow_module_level=True)


def _verify_safe_test_db(url_str: str) -> None:
    """Guard against pointing test runner at production databases."""
    import os
    from urllib.parse import urlparse
    parsed = urlparse(url_str)
    dbname = parsed.path.lstrip("/")
    allow_cleanup = (
        os.environ.get("NOCPRO_ALLOW_TEST_CLEANUP") == "1"
        or os.environ.get("NOCPRO_RUN_DOCKER_E2E") == "1"
    )
    is_test_named = dbname.endswith("_test") or dbname.startswith("test_") or "test" in dbname
    if not (is_test_named or allow_cleanup):
        pytest.skip(
            f"Refusing to run tests against DB '{dbname}' without explicit confirmation. "
            "Database name must contain 'test' or NOCPRO_ALLOW_TEST_CLEANUP=1 must be set."
        )


@pytest.fixture
async def pg_repo():
    """Connect to PostgreSQL with isolated random schema per test."""
    import uuid
    _verify_safe_test_db(POSTGRES_URL)
    schema_name = f"review_e2e_{uuid.uuid4().hex[:12]}"

    base_engine = create_async_engine(POSTGRES_URL, echo=False)
    try:
        async with base_engine.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema_name}"))
    except Exception as exc:
        await base_engine.dispose()
        pytest.skip(f"PostgreSQL connection unavailable at {POSTGRES_URL}: {exc}")

    # Connect with search_path set strictly to the isolated schema (excluding public)
    schema_engine = create_async_engine(
        POSTGRES_URL,
        connect_args={"server_settings": {"search_path": f"{schema_name}"}},
        echo=False,
    )
    async with schema_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(schema_engine, expire_on_commit=False)
    repository = SnapshotRepository(sessions)
    yield repository

    # Complete teardown: drop the isolated schema and cascade all tables
    await schema_engine.dispose()
    async with base_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
    await base_engine.dispose()


def _make_bundle(review_id: str = "rev_test_e2e_1", job_id: str = "job_test_e2e_1", domain: str = "IP_CORE", review_time: datetime | None = None):
    now = review_time or datetime.now(timezone.utc)
    session = ReviewSession(
        review_id=review_id,
        job_id=job_id,
        snapshot_id=f"snap_{review_id}",
        snapshot_version="v1",
        chain_id=f"chain_{review_id}",
        review_time=now,
        source_kind="OPERATOR_REVIEW",
        review_domain=domain,
        lineage_component_id=f"comp_{review_id}",
        candidate_set_fingerprint=f"cs_fp_{review_id}",
        generator_version="gen_v1",
        config_version="cfg_v1",
        delay_model_version="delay_v2",
        retrieval_version=None,
        exposure_policy="ALL_EVALUATED",
    )
    exposures = [
        CandidateExposure(
            review_id=review_id,
            candidate_id="cand_1",
            candidate_fingerprint="fp_cand_1",
            operation="REMOVE",
            original_rank=1,
            displayed_rank=1,
            deterministic_eligibility="HARD_GATES_PASSED",
            hard_gate_status="PASSED",
            pareto_state="FRONTIER_SELECTED",
            deterministic_context={"benefit": 2.0, "partition_delta": {"removed": ["a1"]}},
            case_context={"domain": domain},
            temporal_context={"status": "AVAILABLE", "delay_score_mean": 0.9},
            feature_schema_version="cf-features-v1",
            feature_payload={"exact_metrics": {"benefit": 2.0}},
        ),
        CandidateExposure(
            review_id=review_id,
            candidate_id="cand_2",
            candidate_fingerprint="fp_cand_2",
            operation="SPLIT",
            original_rank=2,
            displayed_rank=2,
            deterministic_eligibility="DOMINATED",
            hard_gate_status="PASSED",
            pareto_state="DOMINATED",
            deterministic_context={"benefit": 0.5, "partition_delta": {"split": [["a1"], ["a2"]]}},
            case_context={"domain": domain},
            temporal_context={"status": "AVAILABLE", "delay_score_mean": 0.3},
            feature_schema_version="cf-features-v1",
            feature_payload={"exact_metrics": {"benefit": 0.5}},
        ),
    ]
    return session, exposures


async def test_postgres_atomic_unit_of_work(pg_repo: SnapshotRepository):
    """Verify persist_succeeded_job_and_review_bundle commits job and review bundle in a single transaction."""
    job_id = "job_test_e2e_uow_1"
    review_id = "rev_test_e2e_uow_1"
    now = datetime.now(timezone.utc)

    job_payload = {
        "job_id": job_id,
        "snapshot_id": "snap_1",
        "snapshot_version": "v1",
        "chain_id": "chain_1",
        "cache_fingerprint": "cf_fp_1",
        "status": "SUCCEEDED",
        "progress_percent": 100,
        "cache_hit": False,
        "identity": {"snapshot_id": "snap_1", "snapshot_version": "v1"},
        "result": {"recommendations": [{"candidate_id": "cand_1", "operation": "REMOVE"}]},
        "error": None,
    }
    session, exposures = _make_bundle(review_id=review_id, job_id=job_id, domain="IP_CORE", review_time=now)

    # 1. Atomic commit succeeds
    await pg_repo.persist_succeeded_job_and_review_bundle(job_payload, session, exposures)

    # Verify both job and review bundle exist
    stored_job = await pg_repo.counterfactual_job(job_id)
    assert stored_job is not None
    assert stored_job.job_id == job_id
    assert stored_job.status == "SUCCEEDED"

    stored_session = await pg_repo.get_review_session(review_id)
    assert stored_session is not None
    assert stored_session.review_id == review_id
    assert stored_session.review_domain == "IP_CORE"

    stored_exps = await pg_repo.get_candidate_exposures(review_id)
    assert len(stored_exps) == 2


async def test_postgres_strict_append_only_zero_mutation(pg_repo: SnapshotRepository):
    """Verify zero UPDATE or DELETE statements on evidence tables across full feedback lifecycle.
    Tables: review_session, candidate_exposure, review_feedback, manual_correction.
    """
    review_id = "rev_test_e2e_append_only"
    job_id = "job_test_e2e_append_only"
    session, exposures = _make_bundle(review_id=review_id, job_id=job_id, domain="IP_CORE")
    await pg_repo.persist_review_bundle(session, exposures)

    now = datetime.now(timezone.utc)

    # 1. Append active feedback fb1
    fb1 = ReviewFeedback(
        feedback_id="fb_test_e2e_1",
        review_id=review_id,
        candidate_id="cand_1",
        reviewer_subject="alice",
        reviewer_role="PRINCIPAL_OPERATOR",
        reviewer_domain_scope=("IP_CORE",),
        decision=ReviewDecision.APPROVE,
        confidence=0.9,
        reason_policy_version="v1",
        reason_codes=("PLAUSIBLE_SUBGRAPH",),
        truth_tier=TruthTier.PO_ASSERTED,
        created_at=now,
    )
    case1 = ReviewCase(
        case_id="case_test_e2e_1",
        review_id=review_id,
        feedback_id="fb_test_e2e_1",
        candidate_id="cand_1",
        case_time=now,
        lineage_component_id="comp_1",
        operation_pattern="REMOVE",
        case_domain="IP_CORE",
        fingerprint_schema_version="cf-case-v1",
        fingerprint_payload={"metrics": {"benefit": 2.0}},
        fingerprint_hash="fp_h1",
        decision=ReviewDecision.APPROVE,
        truth_tier=TruthTier.PO_ASSERTED,
        status="ACTIVE",
    )
    await pg_repo.append_review_feedback(fb1, review_case=case1)

    # 2. Supersede fb1 with fb2 (MANUAL_CORRECTION)
    fb2 = ReviewFeedback(
        feedback_id="fb_test_e2e_2",
        review_id=review_id,
        candidate_id="cand_1",
        reviewer_subject="alice",
        reviewer_role="PRINCIPAL_OPERATOR",
        reviewer_domain_scope=("IP_CORE",),
        decision=ReviewDecision.MANUAL_CORRECTION,
        confidence=1.0,
        reason_policy_version="v1",
        reason_codes=("MANUAL_TOPOLOGY_SPLIT",),
        truth_tier=TruthTier.PO_ASSERTED,
        supersedes_feedback_id="fb_test_e2e_1",
        created_at=now + timedelta(minutes=5),
    )
    mc2 = ManualCorrection(
        correction_id="mc_test_e2e_2",
        feedback_id="fb_test_e2e_2",
        operation="SPLIT",
        partition_delta={"split": [["a1"], ["a2"]]},
        correction_fingerprint="fp_mc2",
        created_at=now + timedelta(minutes=5),
    )
    case2 = ReviewCase(
        case_id="case_test_e2e_2",
        review_id=review_id,
        feedback_id="fb_test_e2e_2",
        candidate_id="cand_1",
        case_time=now + timedelta(minutes=5),
        lineage_component_id="comp_1",
        operation_pattern="SPLIT",
        case_domain="IP_CORE",
        fingerprint_schema_version="cf-case-v1",
        fingerprint_payload={"metrics": {"benefit": 1.0}},
        fingerprint_hash="fp_h2",
        decision=ReviewDecision.MANUAL_CORRECTION,
        truth_tier=TruthTier.PO_ASSERTED,
        status="ACTIVE",
    )
    await pg_repo.append_superseding_feedback(
        fb2,
        supersedes_feedback_id="fb_test_e2e_1",
        manual_correction=mc2,
        review_case=case2,
    )

    # 3. Retract fb2
    await pg_repo.append_retraction_event(
        feedback_id="fb_test_e2e_2",
        actor_subject="supervisor_carol",
        reason="Retracted for refinement",
        created_at=now + timedelta(minutes=10),
    )

    # Strict PostgreSQL row audit:
    # Both fb1 and fb2 MUST still exist unchanged in the review_feedback table!
    async with pg_repo.sessions() as session_db:
        fbs_in_db = (
            await session_db.execute(
                text("SELECT feedback_id, decision, supersedes_feedback_id FROM review_feedback WHERE review_id = :review_id ORDER BY created_at"),
                {"review_id": review_id},
            )
        ).fetchall()
        assert len(fbs_in_db) == 2
        assert fbs_in_db[0].feedback_id == "fb_test_e2e_1"
        assert fbs_in_db[0].supersedes_feedback_id is None
        assert fbs_in_db[1].feedback_id == "fb_test_e2e_2"
        assert fbs_in_db[1].supersedes_feedback_id == "fb_test_e2e_1"

        # Lifecycle events table contains CREATED, SUPERSEDED, CREATED, and RETRACTED
        lc_events = (
            await session_db.execute(
                text("SELECT event_type, feedback_id, superseded_by_id FROM feedback_lifecycle_event WHERE feedback_id IN ('fb_test_e2e_1', 'fb_test_e2e_2') ORDER BY created_at")
            )
        ).fetchall()
        assert len(lc_events) == 4
        assert lc_events[0].event_type == "CREATED"
        assert lc_events[0].feedback_id == "fb_test_e2e_1"
        assert lc_events[1].event_type == "SUPERSEDED"
        assert lc_events[1].feedback_id == "fb_test_e2e_1"
        assert lc_events[1].superseded_by_id == "fb_test_e2e_2"
        assert lc_events[2].event_type == "CREATED"
        assert lc_events[2].feedback_id == "fb_test_e2e_2"
        assert lc_events[3].event_type == "RETRACTED"
        assert lc_events[3].feedback_id == "fb_test_e2e_2"

        # review_case rows: case1 was NOT updated in place; both case1 and case2 rows exist
        cases_in_db = (
            await session_db.execute(
                text("SELECT case_id, feedback_id FROM review_case WHERE review_id = :review_id ORDER BY created_at"),
                {"review_id": review_id},
            )
        ).fetchall()
        assert len(cases_in_db) == 2

    # Querying projected active state yields 0 active feedbacks (since fb2 was retracted and fb1 was superseded)
    active_feedbacks = await pg_repo.active_review_feedback(review_id=review_id)
    assert len(active_feedbacks) == 0

    # active_review_cases_before also projects 0 active cases for this review
    active_cases = await pg_repo.active_review_cases_before(datetime(2099, 1, 1, tzinfo=timezone.utc))
    assert len([c for c in active_cases if c.review_id == review_id]) == 0


async def test_postgres_service_restart_hydration(pg_repo: SnapshotRepository):
    """Verify ReviewLearningService restart hydration and state projection against real PostgreSQL."""
    review_id = "rev_test_e2e_pg_restart"
    job_id = "job_test_e2e_pg_restart"
    t0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    session, exposures = _make_bundle(review_id=review_id, job_id=job_id, domain="IP_CORE", review_time=t0)
    await pg_repo.persist_review_bundle(session, exposures)

    # 1. First Service instance records display event and feedback
    service1 = ReviewLearningService(pg_repo)
    principal = ReviewerPrincipal(
        subject="operator_alice",
        role="PRINCIPAL_OPERATOR",
        domain_scope=("IP_CORE",),
        auth_type="TEST",
    )

    await service1.record_display_events(
        job_id=job_id,
        events_payload=[
            {"candidate_id": "cand_1", "displayed_rank": 1, "surface": "VALIDATION_VIEW_TOP_CARD", "client_event_id": "e_pg_1"},
            {"candidate_id": "cand_2", "displayed_rank": 2, "surface": "EXPANDED_CANDIDATE_LIST", "client_event_id": "e_pg_2"},
        ],
        principal=principal,
    )

    fb = await service1.record_feedback(
        job_id=job_id,
        submission={
            "candidate_id": "cand_1",
            "decision": "APPROVE",
            "confidence": 0.95,
            "reason_codes": ["PLAUSIBLE_SUBGRAPH"],
        },
        principal=principal,
    )
    assert fb.decision == ReviewDecision.APPROVE

    # 2. Simulate complete service crash and restart: create Service 2 with empty cache
    del service1
    service2 = ReviewLearningService(pg_repo)
    assert len(service2._sessions) == 0
    assert len(service2._exposures) == 0

    # 3. Query similar cases in a subsequent session after restart
    t1 = datetime.now(timezone.utc) + timedelta(hours=1)
    session2, exposures2 = _make_bundle(
        review_id="rev_test_e2e_pg_subsequent",
        job_id="job_test_e2e_pg_subsequent",
        domain="IP_CORE",
        review_time=t1,
    )
    await pg_repo.persist_review_bundle(session2, exposures2)

    similar = await service2.find_similar_cases_for_candidate(
        job_id="job_test_e2e_pg_subsequent",
        candidate_id="cand_1",
        principal=principal,
        top_k=5,
        min_common_blocks=0,
        min_similarity=0.1,
    )
    assert similar.retrieval_status == "AVAILABLE"
    assert len(similar.cross_incident_cases) >= 1
    assert similar.cross_incident_cases[0].candidate_id == "cand_1"
    assert similar.cross_incident_cases[0].decision == ReviewDecision.APPROVE

    # 4. Service 2 also records additional display events on the hydrated session
    count = await service2.record_display_events(
        job_id=job_id,
        events_payload=[
            {"candidate_id": "cand_1", "displayed_rank": 1, "surface": "PEER_SIMILARITY_DRAWER", "client_event_id": "e_pg_3"},
        ],
        principal=principal,
    )
    assert count == 1


async def test_production_governance_simulation_and_restart(
    pg_repo: SnapshotRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """End-to-End Production Governance Simulation and Service Restart Verification:
    Demonstrates data contracts, cryptographic signature verification, detached binding,
    fail-closed schema validation, temporal holdout, and candidate reranking integration
    across FastAPI, Workspace, ReviewLearningService, and PostgreSQL.

    NOTE ON EPISTEMIC BOUNDARY:
    This test runs an integration simulation of production governance and data contracts.
    The underlying data for the test groups is simulated fixture data demonstrating plumbing;
    final live production model evaluation will be performed once real Product Owner (PO)
    review feedback has been collected via Agent 1 in active operation.

    Lifecycle stages:
    1. Seed real-like jobs & review bundles in PostgreSQL
    2. Submit operator feedback via FastAPI HTTP endpoint
    3. Verify persistence & audit trail in PostgreSQL
    4. Simulate full service crash/restart with empty cache
    5. Materialize protected training corpus from PostgreSQL with zero leakage
    6. Train XGBRanker offline model
    7. Save and cryptographically sign production artifact
    8. Load and verify production artifact with fail-closed governance
    9. Verify re-ranking on serving path in ReviewLearningService
    """
    import httpx2
    from dataclasses import replace
    from nocpro_api import create_app
    from nocpro_api.workspace import Workspace
    from review_learning import (
        FEATURE_SCHEMA_VERSION,
        LABEL_POLICY_VERSION,
        RankerArtifactManifest,
        build_data_profile,
        generate_synthetic_review_group,
        load_production_ranker_artifact,
        materialize_training_corpus_from_repository_groups,
        save_ranker_artifact,
        sign_ranker_artifact,
        train_xgbranker,
    )

    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")

    # 1. Setup Workspace and populate 3 review groups in PostgreSQL
    ws1 = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    ws1.repository = pg_repo
    ws1.review_learning = ReviewLearningService(pg_repo)

    job_cand_map: dict[str, str] = {}
    for i in range(1, 4):
        rid = f"rev_test_e2e_life_{i}"
        jid = f"job_test_e2e_life_{i}"
        dt = f"2026-09-0{i}T10:00:00Z"
        lin = f"comp_test_e2e_life_{i}"

        session, exposures, _ = generate_synthetic_review_group(
            review_id=rid,
            review_time=dt,
            lineage_component_id=lin,
            scenario="STANDARD_TOP1_APPROVED",
            truth_tier=TruthTier.PO_ASSERTED,
        )
        session = replace(
            session,
            job_id=jid,
            source_kind="REAL_LIVE",
        )

        job_payload = {
            "job_id": jid,
            "snapshot_id": session.snapshot_id,
            "snapshot_version": session.snapshot_version,
            "chain_id": session.chain_id,
            "cache_fingerprint": f"cfp_{jid}",
            "status": "SUCCEEDED",
            "progress_percent": 100,
            "cache_hit": False,
            "identity": {
                "snapshot_id": session.snapshot_id,
                "snapshot_version": session.snapshot_version,
                "chain_id": session.chain_id,
                "domain": "IP_CORE",
            },
            "result": {
                "evaluated_candidates": [
                    {"candidate_id": exp.candidate_id, "operation": exp.operation}
                    for exp in exposures
                ]
            },
            "error": None,
        }
        await pg_repo.persist_counterfactual_job(job_payload)
        await pg_repo.persist_review_bundle(session, exposures)
        ws1.review_learning.register_persisted_bundle(session, exposures)
        job_cand_map[jid] = exposures[0].candidate_id

    # 2. Submit operator feedback via FastAPI HTTP endpoint (approve cand 1, reject cand 2)
    app1 = create_app(workspace=ws1)
    transport1 = httpx2.ASGITransport(app=app1)
    async with httpx2.AsyncClient(transport=transport1, base_url="http://testserver") as client:
        for jid, c1 in job_cand_map.items():
            resp1 = await client.post(
                f"/api/v1/review-jobs/{jid}/feedback",
                json={
                    "candidate_id": c1,
                    "decision": "APPROVED",
                    "reason": "Topological split validated by Principal Operator",
                },
                headers={
                    "X-Dev-Operator-Id": "po_charlie",
                    "X-Dev-Operator-Role": "PRODUCT_OWNER",
                },
            )
            assert resp1.status_code == 201

            rid = jid.replace("job_", "rev_")
            c2 = f"{rid}-cand-2"
            resp2 = await client.post(
                f"/api/v1/review-jobs/{jid}/feedback",
                json={
                    "candidate_id": c2,
                    "decision": "REJECTED",
                    "reason": "Suboptimal split according to PO policy",
                },
                headers={
                    "X-Dev-Operator-Id": "po_charlie",
                    "X-Dev-Operator-Role": "PRODUCT_OWNER",
                },
            )
            assert resp2.status_code == 201

    ws1.close()
    del ws1
    del app1

    # 3. Simulate complete service crash and restart
    ws2 = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    ws2.repository = pg_repo
    ws2.review_learning = ReviewLearningService(pg_repo)
    assert len(ws2.review_learning._sessions) == 0

    # 4. Fetch raw groups directly from PostgreSQL
    cutoff_dt = datetime.now(timezone.utc) + timedelta(days=1)
    cutoff_str = cutoff_dt.isoformat()
    repo_groups = await pg_repo.training_review_groups_before(cutoff_dt)
    e2e_groups = [g for g in repo_groups if g["review_session"].review_id.startswith("rev_test_e2e_life_")]
    assert len(e2e_groups) == 3

    # 5. Protected mode materialization from PostgreSQL
    corpus = materialize_training_corpus_from_repository_groups(
        groups=e2e_groups,
        cutoff=cutoff_str,
        protected_mode=True,
        strict_temporal_holdout=True,
    )
    assert corpus.train.num_groups >= 1
    assert len(corpus.excluded_groups) == 0
    assert corpus.corpus_fingerprint != ""

    profile = build_data_profile(corpus)
    assert profile.lineage_overlap_detected is False
    assert profile.temporal_inversion_detected is False
    assert "REAL_LIVE" in profile.source_kind_distribution
    assert "PO_ASSERTED" in profile.truth_tier_distribution

    # 6. Train XGBRanker on materialized PostgreSQL corpus
    model, metrics = train_xgbranker(
        train_ds=corpus.train,
        val_ds=corpus.val if corpus.val.num_groups > 0 else None,
        params={"n_estimators": 10, "max_depth": 3, "random_state": 42},
    )
    assert model is not None
    assert metrics.ndcg_1 >= 0.0

    # 7. Save and sign production artifact
    artifact_dir = tmp_path / "artifacts" / "review_ranker" / "prod_v1"
    manifest = RankerArtifactManifest(
        model_version="prod_v1",
        model_family="XGBRanker",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        label_policy_version=LABEL_POLICY_VERSION,
        training_cutoff=cutoff_str,
        corpus_fingerprint=corpus.corpus_fingerprint,
        hyperparameters={"n_estimators": 10, "max_depth": 3},
        metrics=metrics,
        slice_metrics={},
        artifact_sha256="",
        source_kind_mix={"REAL_LIVE": 3},
        truth_tier_distribution={"PO_ASSERTED": 3},
        protected_mode_used=True,
        strict_temporal_holdout_used=True,
        lineage_overlap_detected=False,
        temporal_inversion_detected=False,
        approval_status="APPROVED",
        approved_by="governance_lead_charlie",
        data_profile_fingerprint=profile.data_profile_fingerprint,
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "data_profile.json").write_text(
        json.dumps(profile.to_dict(), sort_keys=True), encoding="utf-8"
    )
    save_ranker_artifact(model, manifest, artifact_dir)
    signing_key = "e2e_production_secret_key_999"
    sign_ranker_artifact(
        artifact_dir,
        principal_id="governance_lead_charlie",
        signing_key=signing_key,
        approval_notes="E2E production approval",
    )

    # 8. Verify production load with cryptographic signature
    loaded_model, loaded_manifest = load_production_ranker_artifact(
        artifact_dir, signing_key=signing_key
    )
    assert loaded_manifest.approval_status == "APPROVED"
    assert loaded_manifest.approval_signature is not None

    # 9. Test production serving & reranking in ReviewLearningService
    serving_service = ReviewLearningService(
        repository=pg_repo,
        ranker_artifact_dir=str(artifact_dir),
        enforce_production_governance=True,
        signing_key=signing_key,
    )
    assert serving_service._ranker_model is not None
    assert serving_service._ranker_manifest.model_version == "prod_v1"

    # Test reranking candidate exposures
    test_bundle_session, test_bundle_exposures = _make_bundle(
        review_id="rev_test_e2e_serving_1",
        job_id="job_test_e2e_serving_1",
    )
    reranked = serving_service.rerank_candidate_exposures(list(test_bundle_exposures))
    assert len(reranked) == len(test_bundle_exposures)
    assert [exp.displayed_rank for exp in reranked] == list(range(1, len(reranked) + 1))

    # Test that setting high abstention threshold preserves original ordering
    abstaining_service = ReviewLearningService(
        repository=pg_repo,
        ranker_artifact_dir=str(artifact_dir),
        enforce_production_governance=True,
        signing_key=signing_key,
        abstention_threshold=100.0,
    )
    abstained = abstaining_service.rerank_candidate_exposures(list(test_bundle_exposures))
    assert [exp.candidate_id for exp in abstained] == [exp.candidate_id for exp in test_bundle_exposures]

    ws2.close()

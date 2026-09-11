from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nocpro_api.persistence.models import Base, ReviewCaseModel, ReviewFeedbackModel, ReviewSessionModel
from nocpro_api.persistence.repository import SnapshotRepository
from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.review_principal import ReviewerPrincipal
from review_learning.contracts import (
    CandidateExposure,
    InactiveFeedbackConflict,
    ReviewDecision,
    ReviewSession,
    ReviewSessionNotFound,
    TruthTier,
    UnknownExposureCandidate,
)
from review_learning.temporal_features import sample_bipartite_pairs, sample_chain_pairs

from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.anyio


@pytest.fixture
async def repo(tmp_path):
    db_file = tmp_path / "restart_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        poolclass=NullPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SnapshotRepository(sessions)
    try:
        yield repository
    finally:
        await engine.dispose()


def _make_session_and_exposures(review_id: str = "rev_restart_1", job_id: str = "job_restart_1", domain: str = "IP_CORE", review_time: datetime | None = None):
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


def test_persistence_models_have_no_unsafe_provenance_defaults():
    """Only the server's frozen context may assign domain and truth provenance."""
    for column in (
        ReviewSessionModel.__table__.c.review_domain,
        ReviewFeedbackModel.__table__.c.truth_tier,
        ReviewCaseModel.__table__.c.case_domain,
    ):
        assert column.default is None
        assert column.server_default is None


async def test_restart_hydration_on_demand(repo: SnapshotRepository):
    """Test Scenario 1: Restart Hydration
    Persist bundle to repository -> Service 2 starts with cold in-memory cache ->
    Calling record_feedback on Service 2 transparently hydrates session & exposures from DB.
    """
    t0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    session, exposures = _make_session_and_exposures("rev_restart_1", "job_restart_1", "IP_CORE", review_time=t0)
    await repo.persist_review_bundle(session, exposures)

    # Cold restart: instantiate service2 with empty caches
    service2 = ReviewLearningService(repo)
    assert "rev_restart_1" not in service2._sessions
    assert "job_restart_1" not in service2._job_to_review_id
    assert len(service2._sessions) == 0

    # Submit feedback on cold service2
    principal = ReviewerPrincipal(
        subject="operator_alice",
        role="PRINCIPAL_OPERATOR",
        domain_scope=("IP_CORE",),
        auth_type="TEST",
    )
    submission = {
        "candidate_id": "cand_1",
        "decision": "APPROVE",
        "confidence": 0.95,
        "reason_codes": ["PLAUSIBLE_SUBGRAPH"],
        "notes": "Good separation",
    }

    # Service 2 automatically hydrates session and exposures during record_feedback
    fb = await service2.record_feedback(
        job_id="job_restart_1",
        submission=submission,
        principal=principal,
    )
    assert fb.decision == ReviewDecision.APPROVE
    assert fb.feedback_id is not None
    assert "rev_restart_1" in service2._sessions
    assert len(service2._exposures.get("rev_restart_1", [])) == 2

    # Query repository to ensure persisted
    active_in_db = await repo.active_review_feedback(review_id="rev_restart_1")
    assert len(active_in_db) == 1
    assert active_in_db[0].feedback_id == fb.feedback_id

    # Now test case similarity retrieval on cold service3 with a future session
    t1 = datetime.now(timezone.utc) + timedelta(hours=1)
    session2, exposures2 = _make_session_and_exposures("rev_restart_2", "job_restart_2", "IP_CORE", review_time=t1)
    await repo.persist_review_bundle(session2, exposures2)

    service3 = ReviewLearningService(repo)
    assert len(service3._sessions) == 0

    similar = await service3.find_similar_cases_for_candidate(
        job_id="job_restart_2",
        candidate_id="cand_1",
        principal=principal,
        top_k=5,
        min_common_blocks=0,
        min_similarity=0.1,
    )
    assert similar.retrieval_status == "AVAILABLE"
    assert len(similar.cross_incident_cases) >= 1
    matched = similar.cross_incident_cases[0]
    assert matched.candidate_id == "cand_1"
    assert matched.decision == ReviewDecision.APPROVE


async def test_display_events_fail_closed(repo: SnapshotRepository):
    """Test Scenario 2: Display Events Fail-Closed
    - Unknown session: raises ReviewSessionNotFound
    - Unexposed candidate: raises UnknownExposureCandidate
    - Empty list: returns 0 without error
    """
    service = ReviewLearningService(repo)
    session, exposures = _make_session_and_exposures("rev_disp_fc", "job_disp_fc")
    await repo.persist_review_bundle(session, exposures)
    service.register_persisted_bundle(session, exposures)

    principal = ReviewerPrincipal(subject="alice", role="PRINCIPAL_OPERATOR", domain_scope=("IP_CORE", "*"), auth_type="TEST")

    # 1. Empty list returns 0
    empty_res = await service.record_display_events(job_id="job_disp_fc", events_payload=[], principal=principal)
    assert empty_res == 0

    # 2. Unknown job/session raises ReviewSessionNotFound
    with pytest.raises(ReviewSessionNotFound):
        await service.record_display_events(
            job_id="job_non_existent",
            events_payload=[{"candidate_id": "cand_1", "displayed_rank": 1}],
            principal=principal,
        )

    # 3. Unexposed candidate raises UnknownExposureCandidate
    with pytest.raises(UnknownExposureCandidate):
        await service.record_display_events(
            job_id="job_disp_fc",
            events_payload=[{"candidate_id": "cand_ghost_never_exposed", "displayed_rank": 1}],
            principal=principal,
        )


async def test_multi_worker_authoritative_supersede_conflict(repo: SnapshotRepository):
    """Test Scenario 3: Multi-worker authoritative supersede concurrency
    Two worker services attempting to supersede the same active feedback.
    The second supersede fails with InactiveFeedbackConflict.
    """
    service_worker1 = ReviewLearningService(repo)
    service_worker2 = ReviewLearningService(repo)

    session, exposures = _make_session_and_exposures("rev_mw", "job_mw", "IP_CORE")
    await repo.persist_review_bundle(session, exposures)
    service_worker1.register_persisted_bundle(session, exposures)

    principal1 = ReviewerPrincipal(subject="alice", role="PRINCIPAL_OPERATOR", domain_scope=("IP_CORE",), auth_type="TEST")
    principal2 = ReviewerPrincipal(subject="bob", role="PRINCIPAL_OPERATOR", domain_scope=("IP_CORE",), auth_type="TEST")

    initial_fb = await service_worker1.record_feedback(
        job_id="job_mw",
        submission={"candidate_id": "cand_1", "decision": "APPROVE", "confidence": 0.9},
        principal=principal1,
    )

    # Worker 1 supersedes initial_fb -> succeeds
    await service_worker1.supersede_feedback(
        job_id="job_mw",
        supersedes_feedback_id=initial_fb.feedback_id,
        submission={"candidate_id": "cand_1", "decision": "REJECT", "confidence": 0.8},
        principal=principal1,
    )

    # Worker 2 attempts to supersede the same initial_fb (now superseded in DB) -> must fail!
    with pytest.raises(InactiveFeedbackConflict):
        await service_worker2.supersede_feedback(
            job_id="job_mw",
            supersedes_feedback_id=initial_fb.feedback_id,
            submission={"candidate_id": "cand_1", "decision": "REJECT", "confidence": 0.8},
            principal=principal2,
        )


async def test_database_failure_cache_rollback(repo: SnapshotRepository, monkeypatch):
    """Test Scenario 4: Database failure leaves cache unmutated
    If the repository raises during append_review_feedback, the in-memory cache
    must not retain the uncommitted feedback or case.
    """
    service = ReviewLearningService(repo)
    session, exposures = _make_session_and_exposures("rev_db_fail", "job_db_fail", "IP_CORE")
    await repo.persist_review_bundle(session, exposures)
    service.register_persisted_bundle(session, exposures)

    principal = ReviewerPrincipal(subject="alice", role="PRINCIPAL_OPERATOR", domain_scope=("IP_CORE",), auth_type="TEST")
    submission = {"candidate_id": "cand_1", "decision": "APPROVE", "confidence": 0.9}

    async def _failing_append(*args, **kwargs):
        raise ConnectionResetError("Simulated DB connection failure during commit")

    monkeypatch.setattr(repo, "append_review_feedback", _failing_append)

    with pytest.raises(ConnectionResetError):
        await service.record_feedback(
            job_id="job_db_fail",
            submission=submission,
            principal=principal,
        )

    # In-memory cache must NOT retain any feedback or cases
    assert len(service._active_feedbacks) == 0
    assert len(service._review_cases) == 0


def test_10k_alarms_kde_pair_memory_bounding():
    """Test Scenario 5: 10,000-alarm pairwise sampling bounding
    Verify sample_chain_pairs and sample_bipartite_pairs execute in < 1s
    without memory blowup (sampling directly via index math).
    """
    n_alarms = 10_000
    chain_indices = [f"a_{i}" for i in range(n_alarms)]

    # Single chain sampling: (10,000 * 9,999) / 2 = 49,995,000 total possible pairs
    t0 = time.perf_counter()
    pairs, total = sample_chain_pairs(chain_indices, max_pairs=1000, seed=42)
    elapsed = time.perf_counter() - t0

    assert len(pairs) == 1000
    assert total == 49_995_000
    assert elapsed < 1.0, f"Single-chain 10k sampling took {elapsed:.4f}s, expected < 1s"
    # Ensure all pairs are valid tuples of strings
    assert all(isinstance(p[0], str) and isinstance(p[1], str) for p in pairs)

    # Bipartite sampling between two 5,000-alarm chains: 5,000 * 5,000 = 25,000,000 pairs
    chain_a = [f"u_{i}" for i in range(5000)]
    chain_b = [f"v_{i}" for i in range(5000)]

    t0 = time.perf_counter()
    bip_pairs, bip_total = sample_bipartite_pairs(chain_a, chain_b, max_pairs=1000, seed=42)
    elapsed_bip = time.perf_counter() - t0

    assert len(bip_pairs) == 1000
    assert bip_total == 25_000_000
    assert elapsed_bip < 1.0, f"Bipartite 10k sampling took {elapsed_bip:.4f}s, expected < 1s"
    assert all(p[0].startswith("u_") and p[1].startswith("v_") for p in bip_pairs)

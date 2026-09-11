from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nocpro_api.persistence.models import Base, ReviewSessionModel, ReviewFeedbackModel, FeedbackLifecycleEventModel
from nocpro_api.persistence.repository import SnapshotRepository
from review_learning.contracts import (
    CandidateDisplayEvent,
    CandidateExposure,
    FeedbackLifecycleType,
    ManualCorrection,
    ReviewCase,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
)

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


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


STORE_CLEANUP_STATEMENTS = [
    "DELETE FROM feedback_lifecycle_event WHERE feedback_id IN (SELECT feedback_id FROM review_feedback WHERE review_id LIKE 'rev_test_store_%')",
    "DELETE FROM manual_correction WHERE feedback_id IN (SELECT feedback_id FROM review_feedback WHERE review_id LIKE 'rev_test_store_%')",
    "DELETE FROM review_case WHERE review_id LIKE 'rev_test_store_%'",
    "DELETE FROM review_feedback WHERE review_id LIKE 'rev_test_store_%'",
    "DELETE FROM candidate_display_event WHERE review_id LIKE 'rev_test_store_%'",
    "DELETE FROM candidate_exposure WHERE review_id LIKE 'rev_test_store_%'",
    "DELETE FROM review_session WHERE review_id LIKE 'rev_test_store_%'",
    "DELETE FROM counterfactual_job WHERE job_id LIKE 'job_test_store_%'",
]


@pytest.fixture
async def repo():
    import os
    import uuid
    from sqlalchemy import text
    db_url = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    if "postgresql" in db_url:
        _verify_safe_test_db(db_url)
        schema_name = f"review_store_{uuid.uuid4().hex[:12]}"
        base_engine = create_async_engine(db_url, echo=False)
        try:
            async with base_engine.begin() as conn:
                await conn.execute(text(f"CREATE SCHEMA {schema_name}"))
        except Exception as exc:
            await base_engine.dispose()
            pytest.skip(f"PostgreSQL connection unavailable at {db_url}: {exc}")

        schema_engine = create_async_engine(
            db_url,
            connect_args={"server_settings": {"search_path": f"{schema_name}"}},
            echo=False,
        )
        async with schema_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        sessions = async_sessionmaker(schema_engine, expire_on_commit=False)
        repository = SnapshotRepository(sessions)
        yield repository

        await schema_engine.dispose()
        async with base_engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
        await base_engine.dispose()
    else:
        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        repository = SnapshotRepository(sessions)
        yield repository
        await engine.dispose()


def _make_session_and_exposures(review_id: str = "rev_test_store_1"):
    now = datetime.now(timezone.utc)
    session = ReviewSession(
        review_id=review_id,
        job_id="job_test_store_1",
        snapshot_id="snap_1",
        snapshot_version="v1",
        chain_id="chain_core_1",
        review_time=now,
        source_kind="TEST",
        lineage_component_id="comp_1",
        candidate_set_fingerprint="fp_cand_set",
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
            original_rank=0,
            displayed_rank=0,
            deterministic_eligibility="HARD_GATES_PASSED",
            hard_gate_status="PASSED",
            pareto_state="FRONTIER_SELECTED",
            deterministic_context={"benefit": 1.5},
            case_context={"domain": "IP"},
            temporal_context={"delay_score": 0.8},
            feature_schema_version="cf-features-v1",
            feature_payload={"exact_metrics": {"benefit": 1.5}},
        ),
        CandidateExposure(
            review_id=review_id,
            candidate_id="cand_2",
            candidate_fingerprint="fp_cand_2",
            operation="SPLIT",
            original_rank=1,
            displayed_rank=1,
            deterministic_eligibility="DOMINATED",
            hard_gate_status="PASSED",
            pareto_state="DOMINATED",
            deterministic_context={"benefit": 0.5},
            case_context={"domain": "IP"},
            temporal_context={"delay_score": 0.2},
            feature_schema_version="cf-features-v1",
            feature_payload={"exact_metrics": {"benefit": 0.5}},
        ),
    ]
    return session, exposures


async def test_persist_review_bundle_and_queries(repo: SnapshotRepository):
    session, exposures = _make_session_and_exposures()
    await repo.persist_review_bundle(session, exposures)

    stored_session = await repo.get_review_session("rev_test_store_1")
    assert stored_session is not None
    assert stored_session.review_id == "rev_test_store_1"
    assert stored_session.job_id == "job_test_store_1"
    assert stored_session.exposure_policy == "ALL_EVALUATED"

    by_job = await repo.get_review_session_by_job_id("job_test_store_1")
    assert by_job is not None
    assert by_job.review_id == "rev_test_store_1"

    stored_exposures = await repo.get_candidate_exposures("rev_test_store_1")
    assert len(stored_exposures) == 2
    assert stored_exposures[0].candidate_id == "cand_1"
    assert stored_exposures[0].deterministic_eligibility == "HARD_GATES_PASSED"
    assert stored_exposures[0].feature_schema_version == "cf-features-v1"
    assert stored_exposures[0].feature_payload == {"exact_metrics": {"benefit": 1.5}}
    assert stored_exposures[1].candidate_id == "cand_2"
    assert stored_exposures[1].deterministic_eligibility == "DOMINATED"
    assert stored_exposures[1].feature_schema_version == "cf-features-v1"
    assert stored_exposures[1].feature_payload == {"exact_metrics": {"benefit": 0.5}}


async def test_append_candidate_display_events(repo: SnapshotRepository):
    session, exposures = _make_session_and_exposures()
    await repo.persist_review_bundle(session, exposures)

    now = datetime.now(timezone.utc)
    events = [
        CandidateDisplayEvent(
            display_event_id="disp_1",
            review_id="rev_test_store_1",
            candidate_id="cand_1",
            displayed_rank=0,
            exposure_policy="ALL_EVALUATED",
            surface="VALIDATION_VIEW_TOP_CARD",
            rendered_at=now,
        ),
        CandidateDisplayEvent(
            display_event_id="disp_2",
            review_id="rev_test_store_1",
            candidate_id="cand_2",
            displayed_rank=1,
            exposure_policy="ALL_EVALUATED",
            surface="EXPANDED_CANDIDATE_LIST",
            rendered_at=now,
        ),
    ]
    await repo.append_candidate_display_events(events)

    # Empty list handling
    await repo.append_candidate_display_events([])


async def test_feedback_append_supersede_and_retract_lifecycle(repo: SnapshotRepository):
    session, exposures = _make_session_and_exposures()
    await repo.persist_review_bundle(session, exposures)

    now = datetime.now(timezone.utc)
    fb1 = ReviewFeedback(
        feedback_id="fb_001",
        review_id="rev_test_store_1",
        candidate_id="cand_1",
        reviewer_subject="po_alice",
        reviewer_role="PRODUCT_OWNER",
        domain_scope=("IP_NETWORK",),
        decision=ReviewDecision.APPROVE,
        confidence=0.95,
        reason_policy_version="v1",
        reason_codes=("PLAUSIBLE_SUBGRAPH",),
        reason_text="Candidate separates optical fault cleanly",
        truth_tier=TruthTier.PO_ASSERTED,
    )

    case1 = ReviewCase(
        case_id="case_001",
        review_id="rev_test_store_1",
        feedback_id="fb_001",
        candidate_id="cand_1",
        case_time=now,
        lineage_component_id="comp_1",
        operation_pattern="REMOVE",
        fingerprint_schema_version="v1",
        fingerprint_payload={"block": "ip"},
        fingerprint_hash="fp_hash_001",
        decision=ReviewDecision.APPROVE,
        truth_tier=TruthTier.PO_ASSERTED,
    )

    # 1. Append active feedback fb1
    await repo.append_review_feedback(fb1, review_case=case1)

    active = await repo.active_review_feedback(review_id="rev_test_store_1")
    assert len(active) == 1
    assert active[0].feedback_id == "fb_001"
    assert active[0].decision == ReviewDecision.APPROVE

    active_cases = await repo.active_review_cases_before(datetime(2099, 1, 1, tzinfo=timezone.utc))
    assert len(active_cases) == 1
    assert active_cases[0].case_id == "case_001"
    assert active_cases[0].status == "ACTIVE"

    # 2. Supersede fb1 with fb2 (e.g. corrected to MANUAL_CORRECTION)
    fb2 = ReviewFeedback(
        feedback_id="fb_002",
        review_id="rev_test_store_1",
        candidate_id="cand_1",
        reviewer_subject="po_alice",
        reviewer_role="PRODUCT_OWNER",
        domain_scope=("IP_NETWORK",),
        decision=ReviewDecision.MANUAL_CORRECTION,
        confidence=1.0,
        reason_policy_version="v1",
        reason_codes=("MANUAL_TOPOLOGY_SPLIT",),
        reason_text="Refined with manual partition split",
        truth_tier=TruthTier.PO_ASSERTED,
        supersedes_feedback_id="fb_001",
    )

    mc = ManualCorrection(
        correction_id="mc_001",
        feedback_id="fb_002",
        operation="SPLIT",
        partition_delta={"split": [["a", "b"], ["c"]]},
        correction_fingerprint="fp_mc_1",
    )

    case2 = ReviewCase(
        case_id="case_002",
        review_id="rev_test_store_1",
        feedback_id="fb_002",
        candidate_id="cand_1",
        case_time=now,
        lineage_component_id="comp_1",
        operation_pattern="SPLIT",
        fingerprint_schema_version="v1",
        fingerprint_payload={"block": "ip_refined"},
        fingerprint_hash="fp_hash_002",
        decision=ReviewDecision.MANUAL_CORRECTION,
        truth_tier=TruthTier.PO_ASSERTED,
    )

    await repo.append_superseding_feedback(
        fb2,
        supersedes_feedback_id="fb_001",
        manual_correction=mc,
        review_case=case2,
    )

    # fb1 must no longer be in active_review_feedback, but still preserved immutably in DB
    active = await repo.active_review_feedback(review_id="rev_test_store_1")
    assert len(active) == 1
    assert active[0].feedback_id == "fb_002"
    assert active[0].decision == ReviewDecision.MANUAL_CORRECTION

    # Active cases: case1 must be marked SUPERSEDED, case2 is ACTIVE
    active_cases = await repo.active_review_cases_before(datetime(2099, 1, 1, tzinfo=timezone.utc))
    assert len(active_cases) == 1
    assert active_cases[0].case_id == "case_002"

    # Query by job_id or chain_id
    active_by_job = await repo.active_review_feedback(job_id="job_test_store_1")
    assert len(active_by_job) == 1
    assert active_by_job[0].feedback_id == "fb_002"

    active_by_chain = await repo.active_review_feedback(chain_id="chain_core_1")
    assert len(active_by_chain) == 1
    assert active_by_chain[0].feedback_id == "fb_002"

    # 3. Retract fb2
    await repo.append_retraction_event(
        feedback_id="fb_002",
        actor_subject="po_alice",
        reason="Mistake in partition definition",
    )

    active_after_retract = await repo.active_review_feedback(review_id="rev_test_store_1")
    assert len(active_after_retract) == 0

    active_cases_after_retract = await repo.active_review_cases_before(datetime(2099, 1, 1, tzinfo=timezone.utc))
    assert len(active_cases_after_retract) == 0


async def test_training_review_groups_before(repo: SnapshotRepository):
    session, exposures = _make_session_and_exposures()
    await repo.persist_review_bundle(session, exposures)

    now = datetime.now(timezone.utc)
    ev = CandidateDisplayEvent(
        display_event_id="disp_1",
        review_id="rev_test_store_1",
        candidate_id="cand_1",
        displayed_rank=0,
        exposure_policy="ALL_EVALUATED",
        surface="VALIDATION_VIEW_TOP_CARD",
        rendered_at=now,
    )
    await repo.append_candidate_display_events([ev])

    fb = ReviewFeedback(
        feedback_id="fb_001",
        review_id="rev_test_store_1",
        candidate_id="cand_1",
        reviewer_subject="po_alice",
        reviewer_role="PRODUCT_OWNER",
        domain_scope=("IP_NETWORK",),
        decision=ReviewDecision.APPROVE,
        confidence=0.9,
        reason_policy_version="v1",
        reason_codes=("PLAUSIBLE_SUBGRAPH",),
        reason_text="Approved",
        truth_tier=TruthTier.PO_ASSERTED,
    )
    await repo.append_review_feedback(fb)

    cutoff = datetime(2099, 1, 1, tzinfo=timezone.utc)
    groups = await repo.training_review_groups_before(cutoff)
    assert len(groups) == 1

    grp = groups[0]
    assert grp["review_session"].review_id == "rev_test_store_1"
    assert len(grp["candidate_exposures"]) == 2
    assert len(grp["candidate_display_events"]) == 1
    assert len(grp["active_feedbacks"]) == 1
    assert grp["active_feedbacks"][0].feedback_id == "fb_001"


async def test_cutoff_excludes_future_lifecycle_events(repo: SnapshotRepository):
    """Verify that retractions happening AFTER cutoff do NOT retroactively deactivate feedback in past cutoff queries."""
    session, exposures = _make_session_and_exposures("rev_test_store_future_lc")
    await repo.persist_review_bundle(session, exposures)

    t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2_cutoff = datetime(2026, 9, 5, 0, 0, 0, tzinfo=timezone.utc)
    t3_retract = datetime(2026, 9, 10, 10, 0, 0, tzinfo=timezone.utc)

    fb = ReviewFeedback(
        feedback_id="fb_cutoff_test",
        review_id="rev_test_store_future_lc",
        candidate_id="cand_1",
        decision=ReviewDecision.APPROVE,
        confidence=0.9,
        truth_tier=TruthTier.PO_ASSERTED,
        created_at=t1,
    )
    await repo.append_review_feedback(fb)

    # Historical cutoff query at t2 (before retraction) must see active feedback
    groups_before_retract = await repo.training_review_groups_before(t2_cutoff)
    assert len(groups_before_retract) == 1
    assert len(groups_before_retract[0]["active_feedbacks"]) == 1

    # Retract at t3 (future relative to t2)
    await repo.append_retraction_event(
        feedback_id="fb_cutoff_test",
        actor_subject="supervisor",
        reason="Retracted later",
        created_at=t3_retract,
    )

    # Historical cutoff query at t2 MUST STILL see active feedback (no future leakage!)
    groups_at_t2 = await repo.training_review_groups_before(t2_cutoff)
    assert len(groups_at_t2) == 1
    assert len(groups_at_t2[0]["active_feedbacks"]) == 1

    # Cutoff query after retraction (e.g. t4) must see retraction took effect
    t4_after = datetime(2026, 9, 15, 0, 0, 0, tzinfo=timezone.utc)
    groups_at_t4 = await repo.training_review_groups_before(t4_after)
    assert len(groups_at_t4) == 0  # no active feedback left in session


async def test_acceptance_postgres_feedback_to_ranker_artifact(repo: SnapshotRepository, tmp_path):
    """End-to-end acceptance test:
    PO feedback -> PostgreSQL -> restart -> training_review_groups_before(cutoff)
    -> feature/label materialization -> non-empty train/val/test -> train XGBRanker
    -> save model + manifest -> reload -> identical predictions.
    """
    import numpy as np
    from review_learning import (
        RankerArtifactManifest,
        build_data_profile,
        evaluate_deterministic_baseline,
        evaluate_linear_baseline,
        evaluate_predictions,
        load_production_ranker_artifact,
        load_ranker_artifact,
        materialize_candidate_features,
        materialize_training_corpus_from_repository_groups,
        save_ranker_artifact,
        sign_ranker_artifact,
        train_best_ranker,
    )
    from review_learning.features import FEATURE_SCHEMA_VERSION
    from review_learning.labels import LABEL_POLICY_VERSION
    from review_learning.contracts import canonical_fingerprint

    cutoff = datetime(2026, 9, 15, 0, 0, 0, tzinfo=timezone.utc)
    operations = ["REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS"]

    # 1. Generate 14 review sessions across 7 distinct lineages (2 sessions per lineage)
    # This guarantees sufficient lineage diversity for train (>=4), val (>=1), test (>=1)
    for lin_idx in range(7):
        lin_id = f"lineage_acc_{lin_idx:02d}"
        for s_idx in range(2):
            rev_id = f"rev_test_store_acc_{lin_idx}_{s_idx}"
            s_time = datetime(2026, 9, 1 + lin_idx, 10 + s_idx, 0, 0, tzinfo=timezone.utc)
            chosen_op = operations[(lin_idx * 2 + s_idx) % len(operations)]

            sess = ReviewSession(
                review_id=rev_id,
                job_id=f"job_test_store_{rev_id}",
                snapshot_id=f"snap_{rev_id}",
                snapshot_version="v1",
                chain_id=f"chain_{lin_idx}",
                review_time=s_time,
                source_kind="SYNTHETIC_TEST",
                lineage_component_id=lin_id,
                candidate_set_fingerprint=f"cs_fp_{rev_id}",
                generator_version="v1",
                config_version="v1",
                delay_model_version="delay_v1",
                retrieval_version=None,
                exposure_policy="ALL_EVALUATED",
                created_at=s_time,
            )

            # Candidate 1: Rank 1 by heuristic, but high blast radius and low past approval -> REJECTED
            det_ctx1 = {
                "raw_score": 0.95,
                "benefit": 3.0,
                "hard_gate_failures": [],
                "partition_delta": {"delta_k": 1},
                "metric_deltas": {"weak_member_count": -3.0, "audit_conductance": -0.2},
                "before_metrics": {"weak_member_count": 3.0},
                "edit_cost": {"members_moved": 8, "chains_created": 2, "chains_removed": 1},
                "topology_dep_hop_available": True,
            }
            temp_ctx1 = {"status": "AVAILABLE", "delay_score_mean": 0.20, "atypical_fraction": 0.70, "fallback_fraction": 0.0}
            case_ctx1 = {"status": "AVAILABLE", "approved_ratio": 0.10, "max_similarity": 0.90}
            flat_f1 = materialize_candidate_features(
                operation=chosen_op,
                deterministic_context=det_ctx1,
                temporal_context=temp_ctx1,
                case_context=case_ctx1,
                hard_gate_status="PASSED",
                pareto_state="FRONTIER_SELECTED",
                source_kind="SYNTHETIC_TEST",
            )
            fp1 = canonical_fingerprint(flat_f1)
            c_fp1 = canonical_fingerprint({"cid": f"{rev_id}_c1", "op": chosen_op, "fp": fp1})

            exp1 = CandidateExposure(
                review_id=rev_id,
                candidate_id=f"{rev_id}_c1",
                candidate_fingerprint=c_fp1,
                operation=chosen_op,
                original_rank=1,
                displayed_rank=1,
                shown_to_reviewer=True,
                deterministic_eligibility="HARD_GATES_PASSED",
                hard_gate_status="PASSED",
                pareto_state="FRONTIER_SELECTED",
                deterministic_context=det_ctx1,
                case_context=case_ctx1,
                temporal_context=temp_ctx1,
                feature_fingerprint=fp1,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                feature_payload={"features": flat_f1, "exact_metrics": det_ctx1},
                created_at=s_time,
            )

            # Candidate 2: Rank 2 by heuristic, but minimal disruption and high past approval -> APPROVED
            det_ctx2 = {
                "raw_score": 0.60,
                "benefit": 1.6,
                "hard_gate_failures": [],
                "partition_delta": {"delta_k": 1},
                "metric_deltas": {"weak_member_count": -1.5, "audit_conductance": -0.05},
                "before_metrics": {"weak_member_count": 3.0},
                "edit_cost": {"members_moved": 1, "chains_created": 0, "chains_removed": 0},
                "topology_dep_hop_available": True,
            }
            temp_ctx2 = {"status": "AVAILABLE", "delay_score_mean": 0.90, "atypical_fraction": 0.05, "fallback_fraction": 0.0}
            case_ctx2 = {"status": "AVAILABLE", "approved_ratio": 0.95, "max_similarity": 0.92}
            flat_f2 = materialize_candidate_features(
                operation="MOVE_MEMBER",
                deterministic_context=det_ctx2,
                temporal_context=temp_ctx2,
                case_context=case_ctx2,
                hard_gate_status="PASSED",
                pareto_state="FRONTIER_SELECTED",
                source_kind="SYNTHETIC_TEST",
            )
            fp2 = canonical_fingerprint(flat_f2)
            c_fp2 = canonical_fingerprint({"cid": f"{rev_id}_c2", "op": "MOVE_MEMBER", "fp": fp2})

            exp2 = CandidateExposure(
                review_id=rev_id,
                candidate_id=f"{rev_id}_c2",
                candidate_fingerprint=c_fp2,
                operation="MOVE_MEMBER",
                original_rank=2,
                displayed_rank=2,
                shown_to_reviewer=True,
                deterministic_eligibility="HARD_GATES_PASSED",
                hard_gate_status="PASSED",
                pareto_state="FRONTIER_SELECTED",
                deterministic_context=det_ctx2,
                case_context=case_ctx2,
                temporal_context=temp_ctx2,
                feature_fingerprint=fp2,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                feature_payload={"features": flat_f2, "exact_metrics": det_ctx2},
                created_at=s_time,
            )

            # Persist bundle to database
            await repo.persist_review_bundle(sess, [exp1, exp2])

            # Append Feedback: Candidate 1 REJECT, Candidate 2 APPROVE (TruthTier.TEST_FIXTURE)
            fb_time = datetime(2026, 9, 1 + lin_idx, 11 + s_idx, 0, 0, tzinfo=timezone.utc)
            fb1 = ReviewFeedback(
                feedback_id=f"fb_{rev_id}_1",
                review_id=rev_id,
                candidate_id=f"{rev_id}_c1",
                reviewer_subject="test_fixture",
                reviewer_role="PRINCIPAL_OPERATOR",
                decision=ReviewDecision.REJECT,
                confidence=0.90,
                truth_tier=TruthTier.TEST_FIXTURE,
                created_at=fb_time,
            )
            fb2 = ReviewFeedback(
                feedback_id=f"fb_{rev_id}_2",
                review_id=rev_id,
                candidate_id=f"{rev_id}_c2",
                reviewer_subject="test_fixture",
                reviewer_role="PRINCIPAL_OPERATOR",
                decision=ReviewDecision.APPROVE,
                confidence=0.95,
                truth_tier=TruthTier.TEST_FIXTURE,
                created_at=fb_time,
            )
            await repo.append_review_feedback(fb1)
            await repo.append_review_feedback(fb2)

    # 2. Simulate API/Worker Restart: create a fresh SnapshotRepository from the same sessionmaker
    restarted_repo = SnapshotRepository(repo.sessions)

    # 3. Fetch review groups before cutoff from restarted repository
    fetched_groups = await restarted_repo.training_review_groups_before(cutoff)
    assert len(fetched_groups) == 14

    # 4. Materialize training corpus
    corpus = materialize_training_corpus_from_repository_groups(fetched_groups, cutoff=cutoff)

    # Assert valid non-empty splits
    assert corpus.train.num_groups >= 6
    assert corpus.val.num_groups >= 2
    assert corpus.test.num_groups >= 2
    assert corpus.train.num_candidates > 0
    assert corpus.val.num_candidates > 0
    assert corpus.test.num_candidates > 0

    # Lineage holdout invariant: 0 lineage overlap
    train_lins = set(corpus.train.lineages)
    val_lins = set(corpus.val.lineages)
    test_lins = set(corpus.test.lineages)
    assert train_lins.isdisjoint(val_lins)
    assert train_lins.isdisjoint(test_lins)
    assert val_lins.isdisjoint(test_lins)

    # Features check: exactly 43 features, all finite
    for x in corpus.train.X:
        assert len(x) == 43
        assert all(np.isfinite(val) for val in x)
    for x in corpus.val.X:
        assert len(x) == 43
        assert all(np.isfinite(val) for val in x)
    for x in corpus.test.X:
        assert len(x) == 43
        assert all(np.isfinite(val) for val in x)

    # Data Profile verification
    profile = build_data_profile(corpus)
    assert profile.lineage_overlap_detected is False
    assert profile.total_groups == 14
    assert len(profile.operation_coverage) >= 3

    # 5. Train XGBRanker via hyperparameter grid search
    model, best_metrics, history = train_best_ranker(
        train_ds=corpus.train,
        val_ds=corpus.val,
        n_jobs=2,
    )
    assert model is not None
    best_params = history[0]["params"]

    manifest = RankerArtifactManifest(
        model_version="v1_acc_test",
        model_family="XGBRanker",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        label_policy_version=LABEL_POLICY_VERSION,
        training_cutoff=cutoff.isoformat(),
        corpus_fingerprint=corpus.corpus_fingerprint,
        hyperparameters=best_params,
        metrics=best_metrics,
        slice_metrics={},
        artifact_sha256="",
        lineage_fingerprint="acc_lineage_fp",
        bundle_checksums={},
        dependency_versions={"python": "3.12"},
        qid_counts={"train": corpus.train.num_groups, "val": corpus.val.num_groups, "test": corpus.test.num_groups},
        operation_coverage=profile.operation_coverage,
        source_kind_mix=profile.source_kind_distribution,
        best_iteration=history[0]["best_iteration"],
        approval_status="DRAFT",
    )

    # 6. Save ranker artifact + manifest + data profile
    art_dir = tmp_path / "artifacts" / "review_ranker" / "v1_acc_test"
    import json
    art_dir.mkdir(parents=True, exist_ok=True)
    (art_dir / "data_profile.json").write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    model_path, manifest_path = save_ranker_artifact(
        model=model,
        manifest=manifest,
        output_dir=art_dir,
    )
    assert (art_dir / "model.json").exists()
    assert (art_dir / "manifest.json").exists()
    assert (art_dir / "data_profile.json").exists()

    # 7. Reload ranker artifact and verify identical predictions
    reloaded_model, reloaded_manifest = load_ranker_artifact(art_dir)
    assert reloaded_manifest.model_version == "v1_acc_test"
    assert len(reloaded_manifest.bundle_checksums) >= 2
    assert reloaded_manifest.artifact_sha256 != ""
    import hashlib
    with open(art_dir / "model.json", "rb") as f:
        expected_hash = hashlib.sha256(f.read()).hexdigest()
    assert reloaded_manifest.artifact_sha256 == expected_hash

    test_preds_orig = model.predict(corpus.test.X)
    test_preds_reloaded = reloaded_model.predict(corpus.test.X)
    np.testing.assert_allclose(test_preds_orig, test_preds_reloaded, atol=1e-5)

    # 8. Evaluate ranking performance on test split
    metrics = evaluate_predictions(corpus.test, list(test_preds_orig))
    baseline = evaluate_deterministic_baseline(corpus.test)
    linear_baseline = evaluate_linear_baseline(corpus.train, corpus.test)
    assert metrics.ndcg_3 > baseline.ndcg_3
    assert metrics.ndcg_3 >= linear_baseline.ndcg_3
    assert metrics.mean_regret <= baseline.mean_regret

    # 9. Verify production artifact loader enforces governance:
    # Fails closed on DRAFT approval status
    with pytest.raises(ValueError, match="not approved for production deployment"):
        load_production_ranker_artifact(art_dir, signing_key="test_signing_key_999")

    # Even when approved and signed, fails closed if source_kind is unapproved or contains forbidden/unapproved truth tiers
    approved_manifest_dict = json.loads(manifest.to_json())
    approved_manifest_dict["approval_status"] = "APPROVED"
    approved_manifest_dict["approved_by"] = "principal_engineer_lead"
    approved_manifest = RankerArtifactManifest.from_json(approved_manifest_dict)
    save_ranker_artifact(model, approved_manifest, art_dir)
    sign_ranker_artifact(art_dir, principal_id="principal_engineer_lead", signing_key="test_signing_key_999")

    with pytest.raises(ValueError, match="(unapproved source kinds|unapproved truth tiers|forbidden non-production truth tiers)"):
        load_production_ranker_artifact(art_dir, signing_key="test_signing_key_999")

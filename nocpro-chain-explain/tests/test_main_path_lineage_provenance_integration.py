from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from configuration import load_analysis_config
from evolution import GlobalEpisodeDag, LineageConfig, LineageNodeKey
from libs.contracts import load_package
from nocpro_api.persistence.models import Base
from nocpro_api.persistence.repository import SnapshotRepository
from nocpro_api.review_principal import ReviewerPrincipal
from nocpro_api.workspace import Workspace
from review_learning import materialize_training_corpus_from_repository_groups
from tests.test_counterfactual_analysis import _member, _metric_computer
from tier2.counterfactual import CounterfactualJobManager
from tier2.counterfactual.jobs import JobStatus

pytestmark = pytest.mark.anyio


def _config():
    return load_analysis_config("config/thresholds/e2e-counterfactual.yaml")


def _multi_candidate_package(snapshot_id: str = "s1", snapshot_time: str = "2026-01-01T00:00:00Z"):
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
            {"alarm_id": a, "snapshot_id": snapshot_id, "raw": {}}
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


async def test_main_path_lineage_provenance_and_timestamps_e2e(tmp_path: Path):
    """Verify that successful Counterfactual job via main submission path:
    1. Replaces any missing or fake lineage with strictly 'LINEAGE_UNAVAILABLE'.
    2. Derives source_kind from package snapshot, never defaulting to fake 'COUNTERFACTUAL_JOB'.
    3. Pins review_time and job_completed_at to job_view.completed_at.
    4. Records submitted_at, started_at, completed_at on job view and persistence payload.
    5. Runs worker thread loop-safety correctly without get_running_loop() errors.
    6. Flushes atomically to database.
    7. Agent 2 Materializer correctly excludes LINEAGE_UNAVAILABLE to protect ground truth.
    8. Verified lineage through real Evolution DAG is accepted into Agent 2 training corpus.
    """
    db_file = tmp_path / "main_path_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", poolclass=NullPool, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repo = SnapshotRepository(sessions)

    ws: Workspace | None = None
    try:
        # =========================================================================
        # Part A: Missing lineage -> LINEAGE_UNAVAILABLE -> excluded by Agent 2
        # =========================================================================
        ws = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
        ws.package = _multi_candidate_package(snapshot_id="s1")
        ws.analyze = lambda chain_id: _multi_candidate_tier1b()
        ws.review_jobs = CounterfactualJobManager(metric_computer=_metric_computer)
        ws.attach_persistence(repo, coordinator=None)

        # 1. Submit review job through workspace main path without lineage
        submission = await ws.submit_review("C")
        assert submission.job_id is not None

        # 2. Wait for job to complete in worker thread pool
        job_view = await asyncio.wait_for(
            asyncio.to_thread(ws.review_jobs.wait, submission.job_id), timeout=10
        )
        assert job_view.status == JobStatus.SUCCEEDED
        assert job_view.result is not None

        # Verify timestamps are populated and monotonic
        assert job_view.submitted_at is not None
        assert job_view.started_at is not None
        assert job_view.completed_at is not None
        assert job_view.submitted_at <= job_view.started_at <= job_view.completed_at

        # 3. Flush asynchronous background persistence tasks with timeout
        await asyncio.wait_for(ws.flush_review_persistence(), timeout=10)

        # 4. Verify stored job record in SQLite database and payload timestamps
        stored_job = await asyncio.wait_for(repo.counterfactual_job(submission.job_id), timeout=5)
        assert stored_job is not None
        assert stored_job.status == "SUCCEEDED"
        payload = job_view.persistence_payload()
        assert payload["submitted_at"] == job_view.submitted_at.isoformat()
        assert payload["started_at"] == job_view.started_at.isoformat()
        assert payload["completed_at"] == job_view.completed_at.isoformat()

        # 5. Verify review session generated by _on_job_success callback
        stored_session = await asyncio.wait_for(
            repo.get_review_session_by_job_id(submission.job_id), timeout=5
        )
        assert stored_session is not None
        assert stored_session.job_id == submission.job_id

        # Invariant 1: Lineage is strictly LINEAGE_UNAVAILABLE (no fake fallback IDs)
        assert stored_session.lineage_component_id == "LINEAGE_UNAVAILABLE"
        assert not stored_session.lineage_component_id.startswith("fallback_lineage:")
        assert not stored_session.lineage_component_id.startswith("lineage:")

        # Invariant 2: Source kind is real/unavailable, NEVER fake COUNTERFACTUAL_JOB
        assert stored_session.source_kind in {"REAL_LIVE", "REAL_EXPORT_REPLAY", "SOURCE_KIND_UNAVAILABLE"}
        assert stored_session.source_kind != "COUNTERFACTUAL_JOB"

        # Invariant 3: Pinned completed_at and review_time match
        assert stored_session.job_completed_at == job_view.completed_at
        assert stored_session.review_time == job_view.completed_at

        # 6. Verify candidate exposures were persisted
        stored_exposures = await asyncio.wait_for(
            repo.get_candidate_exposures(stored_session.review_id), timeout=5
        )
        assert len(stored_exposures) == 2

        # 7. Submit valid feedback with authorized PRODUCT_OWNER role
        principal = ReviewerPrincipal(
            subject="e2e_po_tester",
            role="PRODUCT_OWNER",
            domain_scope=(stored_session.review_domain,),
            auth_type="TEST",
        )
        fb_record = await ws.record_operator_feedback(
            job_id=submission.job_id,
            payload={
                "candidate_id": stored_exposures[0].candidate_id,
                "decision": "APPROVED",
                "reason": "Verified via main path e2e test",
            },
            principal=principal,
        )
        assert fb_record["feedback_id"].startswith("fb_")
        fb_record_2 = await ws.record_operator_feedback(
            job_id=submission.job_id,
            payload={
                "candidate_id": stored_exposures[1].candidate_id,
                "decision": "REJECTED",
                "reason": "Verified via main path e2e test",
            },
            principal=principal,
        )
        assert fb_record_2["feedback_id"].startswith("fb_")

        # 8. Materialize: Agent 2 identifies LINEAGE_UNAVAILABLE and excludes it from training corpus
        cutoff = datetime.now(timezone.utc) + timedelta(days=1)
        groups = await asyncio.wait_for(repo.training_review_groups_before(cutoff), timeout=5)
        assert len(groups) == 1
        assert groups[0]["review_session"].job_id == submission.job_id

        corpus_a = materialize_training_corpus_from_repository_groups(groups, cutoff=cutoff)
        assert corpus_a is not None
        # Must be excluded from training/validation splits
        assert corpus_a.train.num_groups == 0
        assert corpus_a.val.num_groups == 0
        assert len(corpus_a.excluded_groups) == 1
        assert corpus_a.excluded_groups[0].reason == "LINEAGE_UNAVAILABLE"
        assert corpus_a.excluded_groups[0].review_id == stored_session.review_id

        # =========================================================================
        # Part B: Real Evolution DAG lineage -> resolved by Workspace -> accepted
        # =========================================================================
        # Build real multi-snapshot evolution DAG with temporal alarm transitions
        snap_prior = _multi_candidate_package(snapshot_id="s1_prior", snapshot_time="2026-01-01T00:00:00Z")
        snap_current = _multi_candidate_package(snapshot_id="s2_current", snapshot_time="2026-01-01T00:01:00Z")

        dag = GlobalEpisodeDag()
        dag_cfg = LineageConfig(config_version="test-v1", m_min=1)
        dag.apply_snapshot(snap_prior, previous=None, config=dag_cfg)
        dag.apply_snapshot(snap_current, previous=snap_prior, config=dag_cfg)

        # Compute independent expected canonical lineage from the DAG
        node_key = LineageNodeKey("s2_current", "1", "C")
        expected_lineage = dag.canonical_lineage(node_key)
        assert expected_lineage is not None
        assert not expected_lineage.startswith("fallback_lineage:")
        assert not expected_lineage.startswith("lineage:")

        # Configure workspace with real package and real evolution DAG
        ws.package = snap_current
        ws._local_evolution_dag = dag
        if "C" in ws.lineage_by_chain:
            del ws.lineage_by_chain["C"]

        # Submit review: workspace resolves canonical lineage through the evolution DAG
        sub_b = await ws.submit_review("C")
        job_view_b = await asyncio.wait_for(
            asyncio.to_thread(ws.review_jobs.wait, sub_b.job_id), timeout=10
        )
        assert job_view_b.status == JobStatus.SUCCEEDED

        await asyncio.wait_for(ws.flush_review_persistence(), timeout=10)

        stored_session_b = await asyncio.wait_for(
            repo.get_review_session_by_job_id(sub_b.job_id), timeout=5
        )
        assert stored_session_b is not None
        # Proves full resolution: Evolution DAG -> canonical_lineage -> persisted ReviewSession
        assert stored_session_b.lineage_component_id == expected_lineage

        stored_exposures_b = await asyncio.wait_for(
            repo.get_candidate_exposures(stored_session_b.review_id), timeout=5
        )
        assert len(stored_exposures_b) == 2

        fb_record_b = await ws.record_operator_feedback(
            job_id=sub_b.job_id,
            payload={
                "candidate_id": stored_exposures_b[0].candidate_id,
                "decision": "APPROVED",
                "reason": "Verified lineage training acceptance",
            },
            principal=principal,
        )
        assert fb_record_b["feedback_id"].startswith("fb_")
        fb_record_b2 = await ws.record_operator_feedback(
            job_id=sub_b.job_id,
            payload={
                "candidate_id": stored_exposures_b[1].candidate_id,
                "decision": "REJECTED",
                "reason": "Verified lineage training acceptance",
            },
            principal=principal,
        )
        assert fb_record_b2["feedback_id"].startswith("fb_")

        groups_b = await asyncio.wait_for(repo.training_review_groups_before(cutoff), timeout=5)
        verified_group = [g for g in groups_b if g["review_session"].job_id == sub_b.job_id]
        assert len(verified_group) == 1

        corpus_b = materialize_training_corpus_from_repository_groups(verified_group, cutoff=cutoff)
        total_groups_b = corpus_b.train.num_groups + corpus_b.val.num_groups + corpus_b.test.num_groups
        assert total_groups_b == 1
        assert len(corpus_b.excluded_groups) == 0
        all_lineages_b = corpus_b.train.lineages + corpus_b.val.lineages + corpus_b.test.lineages
        assert all_lineages_b == [expected_lineage]
        assert corpus_b.corpus_fingerprint is not None

    finally:
        if ws is not None:
            ws.close()
        await engine.dispose()

from __future__ import annotations

import asyncio
import os

import pytest

from configuration import load_analysis_config
from nocpro_api.persistence import Database, SnapshotRepository
from tier2.counterfactual import CounterfactualJobManager
from tests.test_counterfactual_analysis import _metric_computer, _tier1b
from tests.test_counterfactual_evaluator import _package


pytestmark = pytest.mark.postgres


def test_counterfactual_job_lifecycle_and_result_are_persisted() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise() -> None:
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        manager = CounterfactualJobManager(metric_computer=_metric_computer)
        try:
            submission = manager.submit(
                _package(),
                "C",
                tier1b_artifact=_tier1b(),
                audit_artifact=None,
                analysis_config=load_analysis_config(
                    "config/thresholds/e2e-counterfactual.yaml"
                ),
            )
            view = manager.wait(submission.job_id)
            await repository.persist_counterfactual_job(view.persistence_payload())

            stored = await repository.counterfactual_job(view.job_id)
            assert stored is not None
            assert stored.status == "SUCCEEDED"
            assert stored.identity["snapshot_version"] == "1"
            assert stored.result is not None
            assert stored.result["recommendation_status"] in {
                "AVAILABLE",
                "NO_CLEAR_ALTERNATIVE",
            }

            latest = await repository.latest_compatible_counterfactual_job(
                snapshot_id="s1",
                snapshot_version="1",
                chain_id="C",
                cache_fingerprint=view.cache_fingerprint,
            )
            assert latest is not None
            assert latest.job_id == view.job_id
        finally:
            manager.shutdown()
            await database.close()

    asyncio.run(exercise())


def test_counterfactual_job_identity_cannot_be_rewritten() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise() -> None:
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        manager = CounterfactualJobManager(metric_computer=_metric_computer)
        try:
            submission = manager.submit(
                _package(),
                "C",
                tier1b_artifact=_tier1b(),
                audit_artifact=None,
                analysis_config=load_analysis_config(
                    "config/thresholds/e2e-counterfactual.yaml"
                ),
            )
            payload = manager.wait(submission.job_id).persistence_payload()
            await repository.persist_counterfactual_job(payload)
            changed = dict(payload)
            changed["snapshot_version"] = "different"
            with pytest.raises(ValueError, match="identity is immutable"):
                await repository.persist_counterfactual_job(changed)
        finally:
            manager.shutdown()
            await database.close()

    asyncio.run(exercise())


def test_operator_feedback_lifecycle_persisted() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise() -> None:
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        try:
            feedback_payload = {
                "feedback_id": "fb-test-pg-1",
                "job_id": "job-pg-1",
                "snapshot_id": "s1",
                "snapshot_version": "1",
                "chain_id": "C",
                "candidate_id": "cand-1",
                "operation": "SPLIT_CHAIN",
                "decision": "APPROVED",
                "operator_id": "pg_operator",
                "reason": "Confirmed split",
                "partition_delta": {"before": [["C", ["A1", "A2"]]], "after": [["C", ["A1"]], ["C2", ["A2"]]]},
            }
            stored = await repository.persist_operator_feedback(feedback_payload)
            assert stored.feedback_id == "fb-test-pg-1"
            assert stored.decision == "APPROVED"
            assert stored.mutation_dispatched is False

            # Query by job
            by_job = await repository.operator_feedback_for_job("job-pg-1")
            assert len(by_job) >= 1
            assert any(f.feedback_id == "fb-test-pg-1" for f in by_job)

            # Query by chain
            by_chain = await repository.operator_feedback_for_chain("C")
            assert len(by_chain) >= 1
            assert any(f.feedback_id == "fb-test-pg-1" for f in by_chain)
        finally:
            await database.close()

    asyncio.run(exercise())

"""Focused persistence contract for immutable quality receipts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from nocpro_api.persistence.repository import _canonical_sha256, _receipt_revision, SnapshotRepository


def _assessment() -> dict:
    return {
        "method": "HEURISTIC_V1", "status": "EVALUATED", "readiness": "READY",
        "readiness_policy_version": "quality-readiness-v1", "reason_codes": [],
        "evidence_coverage": {"membership": {"ratio": 0.82531}},
        "dimensions": [{"name": "role_coverage", "score": 0.82531}],
        "score": 0.82531, "stars": 4, "label": "Khá vững",
        "available_dimension_count": 1,
    }


def test_revision_is_canonical_and_excludes_publication_metadata():
    assessment = _assessment()
    refs = {"review_artifact_fingerprint": "a" * 64}
    revision = _receipt_revision(assessment, refs)
    shuffled = dict(reversed(list(assessment.items())))
    shuffled["created_at"] = "tomorrow"
    shuffled["progress_percent"] = 99
    assert _receipt_revision(shuffled, refs) == revision
    assert _receipt_revision({**assessment, "score": 0.82532}, refs) != revision
    assert _receipt_revision(assessment, {**refs, "review_artifact_fingerprint": "b" * 64}) != revision
    assert _receipt_revision(assessment, {**refs, "review_job_id": "new-job"}) == revision
    assert _receipt_revision({**assessment, "readiness_policy_version": "quality-readiness-v2"}, refs) != revision


def test_verified_receipt_requires_exact_source_and_preserves_precision():
    async def exercise():
        identity = {
            "identity_version": "analysis-identity-v1",
            "snapshot_id": "s1", "snapshot_version": "v1", "chain_id": "c1",
            "topology_version": "topo-1", "analysis_config_version": "cfg-1",
            "review_config_version": "review-1", "pipeline_version": "DETERMINISTIC_QUALITY_V6",
        }
        source = {
            "pipeline_version": identity["pipeline_version"],
            "config_version": identity["analysis_config_version"],
            "review_config_version": identity["review_config_version"],
            "snapshot_id": "s1", "snapshot_version": "v1", "topology_version": "topo-1",
            "chain_id": "c1", "deep_dive_job_id": None,
            "deep_dive_cache_fingerprint": None, "counterfactual_job_id": "job-1",
            "counterfactual_cache_fingerprint": "a" * 64,
        }
        identity["input_fingerprint"] = _canonical_sha256(source)
        review_identity = {
            "snapshot_id": "s1", "snapshot_version": "v1", "chain_id": "c1",
            "topology_version": "topo-1", "analysis_version": "cfg-1",
            "config_version": "review-1", "engine_version": "review-engine-1",
            "tier1b_artifact_fingerprint": "b" * 64,
        }
        projected_review_identity = {
            "identity_version": "analysis-identity-v1", "snapshot_id": "s1",
            "snapshot_version": "v1", "chain_id": "c1", "topology_version": "topo-1",
            "analysis_config_version": "cfg-1", "review_config_version": "review-1",
            "pipeline_version": "review-engine-1", "input_fingerprint": "b" * 64,
        }
        projection = {
            "projection_version": "CHAIN_OVERVIEW_V6", "analysis_identity": identity,
            "review_analysis_identity": projected_review_identity,
            "review_artifact_revision": {"resource_kind": "counterfactual_review", "fingerprint": "a" * 64},
            "snapshot_id": "s1", "snapshot_version": "v1", "chain_id": "c1",
            "config_version": "cfg-1", "review_config_version": "review-1",
            "topology_version": "topo-1", "pipeline_version": "DETERMINISTIC_QUALITY_V6",
            "input_fingerprint": identity["input_fingerprint"],
        }
        payload = {
            "snapshot_id": "s1", "snapshot_version": "v1", "chain_id": "c1",
            "input_fingerprint": identity["input_fingerprint"],
            "assessment_version": "HEURISTIC_V1", "assessment": _assessment(),
            "overview_projection": projection, "counterfactual_job_id": "job-1",
        }
        from nocpro_api.persistence.models import CounterfactualJobRecord
        review = CounterfactualJobRecord(
            job_id="job-1", snapshot_id="s1", snapshot_version="v1", chain_id="c1",
            cache_fingerprint="a" * 64, status="SUCCEEDED", progress_percent=100,
            identity_payload=review_identity, result_payload={"review": "complete"},
        )
        session = AsyncMock()
        session.get.return_value = review
        repository = SnapshotRepository(AsyncMock())
        receipt = await repository._verified_quality_receipt_values(session, payload)
        assert receipt is not None
        assert receipt["assessment"]["score"] == 0.82531
        assert receipt["identity_digest"] == _canonical_sha256(identity)
        assert receipt["artifact_revision"] == _receipt_revision(receipt["assessment"], receipt["source_artifact_refs"])

        mismatched = deepcopy(payload)
        mismatched["overview_projection"]["review_artifact_revision"]["fingerprint"] = "c" * 64
        assert await repository._verified_quality_receipt_values(session, mismatched) is None
        mismatched = deepcopy(payload)
        mismatched["input_fingerprint"] = "d" * 64
        assert await repository._verified_quality_receipt_values(session, mismatched) is None
        review.status = "RUNNING"
        assert await repository._verified_quality_receipt_values(session, payload) is None
        session.get.return_value = None
        assert await repository._verified_quality_receipt_values(session, payload) is None

    asyncio.run(exercise())


@pytest.mark.postgres
def test_postgres_receipt_replay_conflict_and_quality_journal_are_atomic(monkeypatch):
    """Runs only against the explicitly configured local PostgreSQL test DB."""
    from uuid import uuid4

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from nocpro_api.persistence.change_journal import journal_position
    from nocpro_api.persistence.models import (
        Base, ChainQualityAssessmentRecord, ChangeEventClockModel,
        ChangeEventModel, QualityEvaluationReceiptRecord,
    )
    import os
    from sqlalchemy.engine import make_url

    database_url = os.environ.get("NOCPRO_CHANGE_JOURNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("NOCPRO_CHANGE_JOURNAL_TEST_DATABASE_URL is not configured")
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql" or parsed.host not in {
        "localhost", "127.0.0.1", "::1", "postgres"
    } or "test" not in (parsed.database or "").lower():
        pytest.fail("receipt PostgreSQL test requires a local database with 'test' in its name")
    database_url = parsed.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    monkeypatch.setenv("NOCPRO_LIVE_UPDATES_ENABLED", "true")

    async def exercise():
        engine = create_async_engine(database_url)
        schema = f"test_quality_receipt_{uuid4().hex}"
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            scoped = engine.execution_options(schema_translate_map={None: schema})
            async with scoped.begin() as connection:
                await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[
                    ChainQualityAssessmentRecord.__table__,
                    QualityEvaluationReceiptRecord.__table__,
                    ChangeEventClockModel.__table__, ChangeEventModel.__table__,
                ]))
            sessions = async_sessionmaker(scoped, expire_on_commit=False)
            async with sessions.begin() as session:
                session.add(ChangeEventClockModel(singleton_id=1, epoch=uuid4(), revision=0))
            repository = SnapshotRepository(sessions)
            identity = {
                "identity_version": "analysis-identity-v1", "snapshot_id": "s1",
                "snapshot_version": "v1", "chain_id": "c1", "topology_version": "topo-1",
                "analysis_config_version": "cfg-1", "review_config_version": "review-1",
                "pipeline_version": "DETERMINISTIC_QUALITY_V6", "input_fingerprint": "a" * 64,
            }
            payload = {
                "snapshot_id": "s1", "snapshot_version": "v1", "chain_id": "c1",
                "input_fingerprint": "a" * 64, "assessment_version": "HEURISTIC_V1",
                "assessment": _assessment(),
                "overview_projection": {"analysis_identity": identity},
            }
            receipt = {
                "receipt_id": uuid4().hex, "identity_digest": _canonical_sha256(identity),
                "artifact_revision": _receipt_revision(_assessment(), {"review_artifact_fingerprint": "a" * 64}),
                "analysis_identity": identity, "assessment": _assessment(),
                "source_artifact_refs": {"review_artifact_fingerprint": "a" * 64},
            }
            repository._verified_quality_receipt_values = AsyncMock(return_value=receipt)
            await repository.persist_chain_quality_assessment(payload)
            assert len(await repository.list_quality_evaluation_receipts(identity_digest=receipt["identity_digest"])) == 1
            assert (await journal_position(sessions)).revision == 1
            await repository.persist_chain_quality_assessment(payload)
            assert len(await repository.list_quality_evaluation_receipts(identity_digest=receipt["identity_digest"])) == 1
            assert (await journal_position(sessions)).revision == 1

            conflicting = {**receipt, "receipt_id": uuid4().hex, "assessment": {**_assessment(), "score": 0.9}}
            repository._verified_quality_receipt_values = AsyncMock(return_value=conflicting)
            changed_payload = {**payload, "assessment": {**_assessment(), "stars": 3}}
            with pytest.raises(RuntimeError, match="integrity conflict"):
                await repository.persist_chain_quality_assessment(changed_payload)
            stored = await repository.chain_quality_assessment(snapshot_id="s1", snapshot_version="v1", chain_id="c1")
            assert stored is not None and stored.stars == 4
            assert (await journal_position(sessions)).revision == 1
            assert len(await repository.list_quality_evaluation_receipts(identity_digest=receipt["identity_digest"])) == 1
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()

    asyncio.run(exercise())

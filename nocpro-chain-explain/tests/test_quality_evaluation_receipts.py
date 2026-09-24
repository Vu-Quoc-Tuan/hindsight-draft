"""Focused persistence contract for immutable quality receipts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from nocpro_api.cohesion_advisor import build_chain_quality_assessment
from nocpro_api.persistence.repository import _canonical_sha256, _receipt_revision, SnapshotRepository


def _assessment() -> dict:
    return build_chain_quality_assessment(
        alarm_count=3, role_counts={"CORE": 2, "WEAK": 1},
        mapped_alarm_count=3, mapped_device_count=3, total_device_count=3,
        topology_status="AVAILABLE", connected_pair_count=2, pair_total=3,
        evaluated_pair_count=3, audit_status="NOT_EVALUATED", audit_verdict=None,
        over_merge_strength=None, recommendation_count=0,
        recommendation_status="NO_CLEAR_ALTERNATIVE",
        recommendation_evaluation_completed=True,
    )


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
        assert receipt["assessment"]["score"] == pytest.approx((0.15 + 0.2 * (2 / 3) + 0.15 + 0.15 * (2 / 3)) / 0.65)
        assert receipt["assessment"]["dimensions"][1] == {
            "name": "member_consistency", "value": 1.0 - (1 / 3), "weight": 0.20,
        }
        assert receipt["source_artifact_refs"]["audit_artifact_id"] is None
        assert receipt["source_artifact_refs"]["audit_artifact_fingerprint"] is None
        assert receipt["identity_digest"] == _canonical_sha256(identity)
        assert receipt["artifact_revision"] == _receipt_revision(receipt["assessment"], receipt["source_artifact_refs"])
        for incomplete in (
            {"score": None}, {"dimensions": []},
            {"score": float("nan")},
        ):
            assert await repository._verified_quality_receipt_values(
                session, {**payload, "assessment": {**payload["assessment"], **incomplete}}
            ) is None

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

        from audit import AuditVerdict, StructuralAuditResult
        from tier2.audit_artifact import (
            AUDIT_ANALYSIS_VERSION, audit_artifact_to_dict,
            build_review_audit_artifact, chain_membership_fingerprint,
        )
        from nocpro_api.persistence.models import AuditArtifactRecord

        members = ("a1", "a2", "a3")
        artifact = build_review_audit_artifact(
            snapshot_id="s1", snapshot_version="v1", chain_id="c1",
            members=members,
            structural_audit=StructuralAuditResult(
                chain_id="c1", verdict=AuditVerdict.NO_LOW_CONDUCTANCE_CUT,
                best_cut=None, scored_candidates=(), epsilon=None, reason="exact",
            ),
            analysis_version=AUDIT_ANALYSIS_VERSION,
            analysis_config_version="cfg-1", topology_version="topo-1",
        )
        audit_row = AuditArtifactRecord(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            artifact_fingerprint=artifact.artifact_fingerprint,
            snapshot_id="s1", snapshot_version="v1", chain_id="c1",
            chain_fingerprint=artifact.chain_fingerprint,
            analysis_version=AUDIT_ANALYSIS_VERSION,
            analysis_config_version="cfg-1", status="AVAILABLE", mode="EXACT",
            payload=audit_artifact_to_dict(artifact),
        )
        audit_assessment = build_chain_quality_assessment(
            alarm_count=3, role_counts={"CORE": 3},
            mapped_alarm_count=0, mapped_device_count=0, total_device_count=3,
            topology_status="UNAVAILABLE", connected_pair_count=0, pair_total=0,
            evaluated_pair_count=0, audit_status="EVALUATED",
            audit_verdict="NO_LOW_CONDUCTANCE_CUT", over_merge_strength="NONE",
            recommendation_count=0, recommendation_status="NO_CLEAR_ALTERNATIVE",
            recommendation_evaluation_completed=True,
        )
        audit_payload = {
            **payload, "assessment": audit_assessment,
            "chain_membership_fingerprint": chain_membership_fingerprint(members),
            "audit_artifact_ref": {
                "artifact_id": artifact.artifact_id,
                "artifact_fingerprint": artifact.artifact_fingerprint,
            },
        }
        review.status = "SUCCEEDED"

        async def persisted_row(model, key):
            if model is CounterfactualJobRecord:
                return review
            if model is AuditArtifactRecord and key == artifact.artifact_id:
                return audit_row
            return None

        session.get.side_effect = persisted_row
        verified = await repository._verified_quality_receipt_values(session, audit_payload)
        assert verified is not None
        assert verified["source_artifact_refs"]["audit_artifact_id"] == artifact.artifact_id
        assert verified["source_artifact_refs"]["audit_artifact_fingerprint"] == artifact.artifact_fingerprint
        saved_row = audit_row
        audit_row = None
        assert await repository._verified_quality_receipt_values(session, audit_payload) is None
        audit_row = saved_row

        for alteration in (
            {"audit_artifact_ref": None},
            {"audit_artifact_ref": {"artifact_id": artifact.artifact_id, "artifact_fingerprint": "f" * 64}},
            {"chain_membership_fingerprint": "f" * 64},
        ):
            assert await repository._verified_quality_receipt_values(
                session, {**audit_payload, **alteration}
            ) is None
        for field, wrong in (
            ("snapshot_id", "other-snapshot"),
            ("snapshot_version", "other-version"),
            ("chain_id", "other-chain"),
            ("chain_fingerprint", "f" * 64),
            ("analysis_version", "other-analysis"),
            ("analysis_config_version", "other-config"),
            ("artifact_fingerprint", "f" * 64),
        ):
            original = getattr(audit_row, field)
            setattr(audit_row, field, wrong)
            assert await repository._verified_quality_receipt_values(session, audit_payload) is None
            setattr(audit_row, field, original)
        audit_row.payload = {**audit_row.payload, "topology_version": "other-topology"}
        assert await repository._verified_quality_receipt_values(session, audit_payload) is None
        audit_row.payload = audit_artifact_to_dict(artifact)
        audit_row.payload = {**audit_row.payload, "verdict": "CANDIDATE_SPLIT"}
        assert await repository._verified_quality_receipt_values(session, audit_payload) is None

    asyncio.run(exercise())


@pytest.mark.postgres
def test_postgres_receipt_replay_conflict_and_quality_journal_are_atomic(monkeypatch):
    """Runs only against the explicitly configured local PostgreSQL test DB."""
    from uuid import uuid4

    from pathlib import Path
    from alembic.config import Config
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import text, update, delete
    from sqlalchemy.exc import DBAPIError
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
                    ChangeEventClockModel.__table__, ChangeEventModel.__table__,
                ]))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                migration_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
                migration = ScriptDirectory.from_config(migration_config).get_revision("0022").module

                def apply_receipt_migration(sync):
                    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(sync)))
                    migration.upgrade()

                await connection.run_sync(apply_receipt_migration)
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
            for mutation in (
                update(QualityEvaluationReceiptRecord).where(
                    QualityEvaluationReceiptRecord.receipt_id == receipt["receipt_id"]
                ).values(artifact_revision="f" * 64),
                delete(QualityEvaluationReceiptRecord).where(
                    QualityEvaluationReceiptRecord.receipt_id == receipt["receipt_id"]
                ),
            ):
                with pytest.raises(DBAPIError, match="quality evaluation receipts are immutable"):
                    async with sessions.begin() as session:
                        await session.execute(mutation)
            assert len(await repository.list_quality_evaluation_receipts(identity_digest=receipt["identity_digest"])) == 1
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

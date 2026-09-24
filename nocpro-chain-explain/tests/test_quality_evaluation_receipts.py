"""Focused persistence contract for immutable quality receipts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
    assert _receipt_revision(assessment, {**refs, "review_result_fingerprint": "c" * 64}) != revision
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
            "review_result": {"review": "complete"},
            "deep_dive_result": None,
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
        assert receipt["source_artifact_refs"]["review_result_fingerprint"] == _canonical_sha256(review.result_payload)
        assert receipt["source_artifact_refs"]["deep_dive_result_fingerprint"] is None
        assert receipt["identity_digest"] == _canonical_sha256(identity)
        assert receipt["artifact_revision"] == _receipt_revision(receipt["assessment"], receipt["source_artifact_refs"])
        unavailable_assessment = {
            **payload["assessment"], "status": "UNAVAILABLE", "readiness": "INSUFFICIENT",
            "stars": None, "score": None, "dimensions": [],
            "available_dimension_count": 0,
            "reason_codes": ["INSUFFICIENT_INDEPENDENT_EVIDENCE"],
        }
        unavailable = await repository._verified_quality_receipt_values(
            session, {**payload, "assessment": unavailable_assessment}
        )
        assert unavailable is not None
        assert unavailable["assessment"]["status"] == "UNAVAILABLE"
        assert unavailable["assessment"]["reason_codes"] == ["INSUFFICIENT_INDEPENDENT_EVIDENCE"]
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
        session.get.return_value = review
        review.status = "SUCCEEDED"
        changed_result = {**payload, "review_result": {"review": "changed"}}
        assert await repository._verified_quality_receipt_values(session, changed_result) is None
        assert await repository._verified_quality_receipt_values(
            session, {key: value for key, value in payload.items() if key != "review_result"}
        ) is None
        review.result_payload = {"review": "different"}
        assert await repository._verified_quality_receipt_values(session, payload) is None
        review.result_payload = {"review": "complete"}

        from nocpro_api.persistence.models import DeepDiveJobRecord
        deep = DeepDiveJobRecord(
            job_id="deep-1", snapshot_id="s1", snapshot_version="v1", chain_id="c1",
            cache_fingerprint="d" * 64, analysis_config_version="cfg-1",
            topology_version="topo-1", status="SUCCEEDED", progress_percent=100,
            cache_hit=False, result_payload={"analysis": {"value": 1}},
        )
        with_deep = deepcopy(payload)
        with_deep["deep_dive_job_id"] = deep.job_id
        with_deep["deep_dive_result"] = deepcopy(deep.result_payload)
        deep_source = {
            **source, "deep_dive_job_id": deep.job_id,
            "deep_dive_cache_fingerprint": deep.cache_fingerprint,
        }
        with_deep["input_fingerprint"] = _canonical_sha256(deep_source)
        with_deep["overview_projection"]["input_fingerprint"] = with_deep["input_fingerprint"]
        with_deep["overview_projection"]["analysis_identity"]["input_fingerprint"] = with_deep["input_fingerprint"]

        async def source_row(model, key):
            if model is CounterfactualJobRecord:
                return review
            if model is DeepDiveJobRecord:
                return deep
            return None

        session.get.side_effect = source_row
        deep_receipt = await repository._verified_quality_receipt_values(session, with_deep)
        assert deep_receipt is not None
        assert deep_receipt["source_artifact_refs"]["deep_dive_result_fingerprint"] == _canonical_sha256(deep.result_payload)
        deep.result_payload = {"analysis": {"value": 2}}
        assert await repository._verified_quality_receipt_values(session, with_deep) is None
        with_deep["deep_dive_result"] = deepcopy(deep.result_payload)
        changed_deep_receipt = await repository._verified_quality_receipt_values(session, with_deep)
        assert changed_deep_receipt is not None
        assert changed_deep_receipt["artifact_revision"] != deep_receipt["artifact_revision"]
        session.get.side_effect = None
        session.get.return_value = review

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


def test_missing_receipt_blocks_quality_before_any_write():
    async def exercise():
        sessions = MagicMock()
        session = sessions.begin.return_value.__aenter__.return_value
        repository = SnapshotRepository(sessions)
        repository._verified_quality_receipt_values = AsyncMock(return_value=None)
        payload = {
            "snapshot_id": "s1", "snapshot_version": "v1", "chain_id": "c1",
            "input_fingerprint": "a" * 64, "assessment_version": "HEURISTIC_V1",
            "assessment": _assessment(),
        }
        with pytest.raises(RuntimeError, match="quality receipt provenance unavailable"):
            await repository.persist_chain_quality_assessment(payload)
        session.execute.assert_not_awaited()

    asyncio.run(exercise())


def test_succeeded_job_result_replay_is_immutable_on_both_review_write_paths():
    from nocpro_api.persistence.models import CounterfactualJobRecord, DeepDiveJobRecord

    async def exercise():
        sessions = MagicMock()
        session = sessions.begin.return_value.__aenter__.return_value
        repository = SnapshotRepository(sessions)
        review_payload = {
            "job_id": "review-1", "snapshot_id": "s1", "snapshot_version": "v1",
            "chain_id": "c1", "cache_fingerprint": "a" * 64,
            "identity": {"id": "one"}, "status": "SUCCEEDED",
            "progress_percent": 100, "cache_hit": False,
            "result": {"facts": {"a": 1, "b": 2}},
        }
        review = CounterfactualJobRecord(
            job_id="review-1", snapshot_id="s1", snapshot_version="v1",
            chain_id="c1", cache_fingerprint="a" * 64,
            identity_payload={"id": "one"}, status="SUCCEEDED", progress_percent=100,
            cache_hit=False, result_payload={"facts": {"b": 2, "a": 1}},
        )
        deep_payload = {
            "job_id": "deep-1", "snapshot_id": "s1", "snapshot_version": "v1",
            "chain_id": "c1", "cache_fingerprint": "b" * 64,
            "analysis_config_version": "cfg-1", "topology_version": "topo-1",
            "status": "SUCCEEDED", "progress_percent": 100, "cache_hit": False,
            "result": {"analysis": 1},
        }
        deep = DeepDiveJobRecord(
            job_id="deep-1", snapshot_id="s1", snapshot_version="v1",
            chain_id="c1", cache_fingerprint="b" * 64,
            analysis_config_version="cfg-1", topology_version="topo-1",
            status="SUCCEEDED", progress_percent=100, cache_hit=False,
            result_payload={"analysis": 1},
        )

        async def row(model, key, **kwargs):
            return review if model is CounterfactualJobRecord else deep

        session.get.side_effect = row
        repository.counterfactual_job = AsyncMock(return_value=repository._stored_counterfactual(review))
        repository.deep_dive_job = AsyncMock(return_value=repository._stored_deep_dive(deep))
        assert (await repository.persist_counterfactual_job(review_payload)).result == review.result_payload
        assert (await repository.persist_deep_dive_job(deep_payload)).result == deep.result_payload
        session.execute.assert_not_awaited()
        with pytest.raises(ValueError, match="result integrity conflict"):
            await repository.persist_counterfactual_job({**review_payload, "result": {"facts": {"a": 9}}})
        with pytest.raises(ValueError, match="result integrity conflict"):
            await repository.persist_deep_dive_job({**deep_payload, "result": {"analysis": 9}})
        bundle = SimpleNamespace(
            review_id="bundle-1", job_id="review-1", candidate_set_fingerprint="c" * 64,
            snapshot_id="s1", snapshot_version="v1", chain_id="c1",
            lineage_component_id=None,
        )
        with pytest.raises(ValueError, match="result integrity conflict"):
            await repository.persist_succeeded_job_and_review_bundle(
                {**review_payload, "result": {"facts": {"a": 9}}}, bundle, ()
            )
        from nocpro_api.persistence.models import ReviewSessionModel
        async def bundle_row(model, key, **kwargs):
            if model is CounterfactualJobRecord:
                return review
            if model is ReviewSessionModel:
                return bundle
            return None
        session.get.side_effect = bundle_row
        session.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        await repository.persist_succeeded_job_and_review_bundle(review_payload, bundle, ())
        assert review.result_payload == {"facts": {"b": 2, "a": 1}}
        session.execute.assert_not_awaited()

    asyncio.run(exercise())


def test_concurrent_bundle_conflict_reloads_and_verifies_job_and_review_rows():
    from review_learning.contracts import ImmutableReviewConflict
    from nocpro_api.persistence.models import CounterfactualJobRecord, ReviewSessionModel
    from sqlalchemy.dialects import postgresql

    async def exercise():
        sessions = MagicMock()
        db_session = sessions.begin.return_value.__aenter__.return_value
        repository = SnapshotRepository(sessions)
        job_payload = {
            "job_id": "job-race", "snapshot_id": "s1", "snapshot_version": "v1",
            "chain_id": "c1", "cache_fingerprint": "a" * 64,
            "status": "SUCCEEDED", "progress_percent": 100, "cache_hit": False,
            "identity": {"snapshot_id": "s1", "snapshot_version": "v1"},
            "result": {"facts": {"a": 1}}, "error": None,
        }
        review_session = SimpleNamespace(
            review_id="review-race", job_id="job-race", snapshot_id="s1",
            snapshot_version="v1", chain_id="c1", review_time="2026-09-25T00:00:00Z",
            source_kind="OPERATOR_REVIEW", lineage_component_id=None,
            candidate_set_fingerprint="b" * 64, generator_version="gen-1",
            config_version="cfg-1", delay_model_version=None, retrieval_version=None,
            exposure_policy="ALL_EVALUATED", status="COMPLETED", review_domain="TEST",
            snapshot_observed_at=None, job_completed_at=None,
            source_alarm_universe_fingerprint=None, created_at="2026-09-25T00:00:00Z",
        )
        exposures = [SimpleNamespace(
            review_id="review-race", candidate_id="candidate-1",
            candidate_fingerprint="c" * 64, operation="REMOVE", original_rank=1,
            displayed_rank=1, deterministic_eligibility="ELIGIBLE",
            hard_gate_status="PASSED", pareto_state="FRONTIER_SELECTED",
            deterministic_context={}, case_context={}, temporal_context={},
            feature_fingerprint="d" * 64, feature_schema_version="cf-features-v1",
            feature_payload={}, created_at="2026-09-25T00:00:00Z",
        )]
        existing_job = SimpleNamespace(
            snapshot_id="s1", snapshot_version="v1", chain_id="c1",
            cache_fingerprint="a" * 64, identity_payload=job_payload["identity"],
            status="SUCCEEDED", result_payload=job_payload["result"],
        )
        existing_session = SimpleNamespace(
            job_id="job-race", candidate_set_fingerprint="b" * 64,
            snapshot_id="s1", snapshot_version="v1", chain_id="c1",
            lineage_component_id=None,
        )
        get_calls = 0

        async def get(model, key, **kwargs):
            nonlocal get_calls
            get_calls += 1
            if get_calls == 1 or get_calls == 3:
                return None
            if model is CounterfactualJobRecord:
                return existing_job
            if model is ReviewSessionModel:
                return existing_session
            return None

        db_session.get = AsyncMock(side_effect=get)
        conflict_result = MagicMock()
        conflict_result.scalar_one_or_none.return_value = None
        db_session.execute = AsyncMock(side_effect=[conflict_result, conflict_result])
        db_session.scalars = AsyncMock(return_value=SimpleNamespace(
            all=lambda: [SimpleNamespace(candidate_id="candidate-1", candidate_fingerprint="c" * 64)]
        ))

        await repository.persist_succeeded_job_and_review_bundle(
            job_payload, review_session, exposures
        )

        assert db_session.get.await_count == 4
        assert db_session.execute.await_count == 2
        statements = [call.args[0] for call in db_session.execute.await_args_list]
        compiled = [str(statement.compile(dialect=postgresql.dialect())) for statement in statements]
        assert "ON CONFLICT (job_id) DO NOTHING" in compiled[0]
        assert "ON CONFLICT (review_id) DO NOTHING" in compiled[1]
        db_session.add.assert_not_called()

        successful_insert = MagicMock()
        successful_insert.scalar_one_or_none.return_value = "different-job"
        db_session.get = AsyncMock(side_effect=[None, existing_session])
        db_session.execute = AsyncMock(return_value=successful_insert)
        with pytest.raises(ImmutableReviewConflict):
            await repository.persist_succeeded_job_and_review_bundle(
                {**job_payload, "job_id": "different-job"},
                SimpleNamespace(**{**vars(review_session), "job_id": "different-job"}),
                exposures,
            )

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
        CounterfactualJobRecord, DeepDiveJobRecord,
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
                    CounterfactualJobRecord.__table__, DeepDiveJobRecord.__table__,
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
            repository._verified_quality_receipt_values.return_value = None
            with pytest.raises(RuntimeError, match="quality receipt provenance unavailable"):
                await repository.persist_chain_quality_assessment(payload)
            assert await repository.chain_quality_assessment(
                snapshot_id="s1", snapshot_version="v1", chain_id="c1"
            ) is None
            assert (await journal_position(sessions)).revision == 0
            assert await repository.list_quality_evaluation_receipts(identity_digest=receipt["identity_digest"]) == []
            repository._verified_quality_receipt_values.return_value = receipt
            await repository.persist_chain_quality_assessment(payload)
            assert len(await repository.list_quality_evaluation_receipts(identity_digest=receipt["identity_digest"])) == 1
            assert (await journal_position(sessions)).revision == 1

            for writer, reader, job_payload in (
                (repository.persist_counterfactual_job, repository.counterfactual_job, {
                    "job_id": uuid4().hex, "snapshot_id": "s1", "snapshot_version": "v1",
                    "chain_id": "c1", "cache_fingerprint": "a" * 64,
                    "identity": {"source": "review"}, "status": "SUCCEEDED",
                    "progress_percent": 100, "cache_hit": False,
                    "result": {"facts": {"a": 1, "b": 2}},
                }),
                (repository.persist_deep_dive_job, repository.deep_dive_job, {
                    "job_id": uuid4().hex, "snapshot_id": "s1", "snapshot_version": "v1",
                    "chain_id": "c1", "cache_fingerprint": "b" * 64,
                    "analysis_config_version": "cfg-1", "topology_version": "topo-1",
                    "status": "SUCCEEDED", "progress_percent": 100, "cache_hit": False,
                    "result": {"facts": {"a": 1, "b": 2}},
                }),
            ):
                await writer(job_payload)
                replay = {**job_payload, "result": {"facts": {"b": 2, "a": 1}}}
                await writer(replay)
                with pytest.raises(ValueError, match="result integrity conflict"):
                    await writer({**job_payload, "result": {"facts": {"a": 9}}})
                assert (await reader(job_payload["job_id"])).result == job_payload["result"]

            repository._verified_quality_receipt_values.return_value = None
            with pytest.raises(RuntimeError, match="quality receipt provenance unavailable"):
                await repository.persist_chain_quality_assessment(
                    {**payload, "assessment": {**_assessment(), "stars": 3}}
                )
            assert (await journal_position(sessions)).revision == 1
            assert (await repository.chain_quality_assessment(
                snapshot_id="s1", snapshot_version="v1", chain_id="c1"
            )).stars == 4
            repository._verified_quality_receipt_values.return_value = receipt
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

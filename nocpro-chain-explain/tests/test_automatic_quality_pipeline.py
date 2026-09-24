from __future__ import annotations

import asyncio
import copy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from nocpro_api.persistence.repository import StoredDeepDiveJob
from nocpro_api.quality_background import (
    SnapshotQualityRunner,
    _SnapshotSource,
    _is_terminal_quality_row,
)
from nocpro_api.workspace import Workspace, _topology_version
from tier2.counterfactual.jobs import artifact_fingerprint
from tier2.counterfactual.models import ReviewIdentity

from tests.test_api import _payload


def test_old_quality_pipeline_projection_is_not_terminal():
    row = SimpleNamespace(
        status="UNAVAILABLE",
        stars=None,
        payload={"overview_projection": {
            "projection_version": "CHAIN_OVERVIEW_V1",
            "pipeline_version": "DETERMINISTIC_QUALITY_V1",
            "config_version": "cfg-1",
            "topology_version": "topology-1",
        }},
    )

    assert not _is_terminal_quality_row(
        row,
        expected_config_version="cfg-1",
        expected_topology_version="topology-1",
    )


class DeepDiveRepositoryStub:
    def __init__(self) -> None:
        self.deep_dive_payloads: list[dict] = []

    async def persist_deep_dive_job(self, payload: dict):
        self.deep_dive_payloads.append(payload)
        return payload

    async def persist_audit_artifact(self, artifact):
        return artifact


def test_successful_deep_dive_automatically_submits_counterfactual(monkeypatch):
    monkeypatch.setenv("NOCPRO_AUTO_CHAIN_QUALITY", "true")

    async def exercise() -> None:
        workspace = Workspace()
        workspace.replace_snapshot(_payload())
        repository = DeepDiveRepositoryStub()
        submit_review = AsyncMock()
        monkeypatch.setattr(workspace, "submit_review", submit_review)
        workspace.attach_persistence(repository, SimpleNamespace())
        try:
            workspace.submit_deep_dive("C1")
            for _ in range(100):
                await asyncio.sleep(0.01)
                await workspace.flush_deep_dive_persistence()
                if submit_review.await_count:
                    break
            submit_review.assert_awaited_once_with("C1")
            assert repository.deep_dive_payloads[-1]["status"] == "SUCCEEDED"
        finally:
            workspace.close()

    asyncio.run(exercise())


def test_quality_materialization_is_provider_free(monkeypatch):
    monkeypatch.setenv("NOCPRO_AUTO_CHAIN_QUALITY", "true")

    class QualityRepositoryStub:
        def __init__(self) -> None:
            self.payload = None

        async def persist_chain_quality_assessment(self, payload):
            self.payload = payload
            return payload

    async def exercise() -> None:
        workspace = Workspace()
        workspace.replace_snapshot(_payload())
        repository = QualityRepositoryStub()
        workspace.repository = repository
        _, _, cache_key = workspace._deep_dive_context("C1")
        deep_dive = SimpleNamespace(
            job_id="deep-1",
            status="SUCCEEDED",
            result=object(),
            audit_artifact=object(),
            cache_key=cache_key,
        )
        monkeypatch.setattr(
            workspace.jobs,
            "latest_compatible",
            lambda *_args, **_kwargs: deep_dive,
        )
        monkeypatch.setattr(
            "nocpro_api.workspace.public_review_result",
            lambda *_args, **_kwargs: {"recommendation_status": "AVAILABLE"},
        )
        monkeypatch.setattr(
            "nocpro_api.cohesion_advisor.extract_cohesion_context",
            lambda **_kwargs: {
                "quality_assessment": {
                    "method": "HEURISTIC_V1",
                    "status": "EVALUATED",
                    "readiness": "READY",
                    "readiness_policy_version": "quality-readiness-v1",
                    "reason_codes": [],
                    "evidence_coverage": {},
                    "stars": 4,
                    "label": "Khá vững",
                    "available_dimension_count": 6,
                    "reasons": ["deterministic"],
                },
                "recommendations": {
                    "status": "AVAILABLE",
                    "evaluation_completed": True,
                },
                "topology": {
                    "mapped_resources": ["R1", "R2"],
                    "display_paths_truncated": False,
                    "display_paths": [{
                        "source": "R1",
                        "target": "R2",
                        "source_devices": ["A1"],
                        "target_devices": ["A2"],
                        "hop_count": 1,
                        "path": ["R1", "R2"],
                        "relation_type": "IP_ADJACENCY",
                        "traversal_semantic": "UNDIRECTED_STRUCTURAL_CONNECTIVITY",
                    }],
                },
                },
            )
        identity = ReviewIdentity(
            snapshot_id="s1",
            snapshot_version="1",
            chain_id="C1",
            alarm_universe_fingerprint="alarms-C1",
            analysis_version=workspace.config.config_version,
            engine_version="counterfactual-p1-v1",
            config_version=(
                workspace.config.counterfactual.config_version
                if workspace.config.counterfactual is not None
                else "UNAVAILABLE"
            ),
            tier1b_artifact_fingerprint="tier1b-C1-v1",
            topology_version=_topology_version(workspace.require_package()),
        )
        workspace._review_context = AsyncMock(
            return_value=(workspace.require_package(), None, None, identity)
        )
        review_view = SimpleNamespace(
            job_id="review-1",
            chain_id="C1",
            identity=identity,
            result=object(),
        )
        try:
            await workspace._materialize_chain_quality(review_view)
            assert repository.payload is not None
            assert repository.payload["assessment"]["stars"] == 4
            assert repository.payload["stage"] == "DETERMINISTIC_COMPLETE"
            assert repository.payload["recommendation_status"] == "AVAILABLE"
            projection = repository.payload["overview_projection"]
            assert projection["projection_version"] == "CHAIN_OVERVIEW_V6"
            assert projection["review_analysis_identity"]["chain_id"] == "C1"
            assert projection["review_analysis_identity"]["input_fingerprint"] == "tier1b-C1-v1"
            assert projection["review_artifact_revision"] == {
                "resource_kind": "counterfactual_review",
                "fingerprint": artifact_fingerprint(identity.cache_tuple()),
            }
            assert "display_paths" in projection["topology"]
            assert "mapped_resources" in projection["topology"]
            assert projection["topology"]["display_paths_truncated"] is False
            assert projection["pipeline_version"] == "DETERMINISTIC_QUALITY_V6"
            assert projection["quality_assessment"]["stars"] == 4
            assert repository.payload["assessment"]["evidence_ids"]
            assert projection["quality_assessment"]["evidence_ids"] == repository.payload["assessment"]["evidence_ids"]
            assert all(
                evidence_id.startswith("ev1_") and len(evidence_id) == 68
                for evidence_id in repository.payload["assessment"]["evidence_ids"]
            )
            assert isinstance(repository.payload["assessment"]["reason_evidence_ids"], dict)
            assert projection["snapshot_id"] == "s1"
            assert projection["snapshot_version"] == "1"
            assert projection["input_fingerprint"] == repository.payload["input_fingerprint"]
        finally:
            workspace.close()

    asyncio.run(exercise())


def test_stale_review_config_is_not_materialized_as_current_quality(monkeypatch):
    async def exercise() -> None:
        workspace = Workspace()
        workspace.replace_snapshot(_payload())
        workspace.update_parameters({"s_min": 0.65})

        class QualityRepositoryStub:
            payload = None

            async def persist_chain_quality_assessment(self, payload):
                self.payload = payload
                return payload

        repository = QualityRepositoryStub()
        workspace.repository = repository
        package = workspace.require_package()
        identity = SimpleNamespace(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            topology_version=_topology_version(package),
            analysis_version="v1",
            config_version=(
                workspace.config.counterfactual.config_version
                if workspace.config.counterfactual is not None
                else "UNAVAILABLE"
            ),
            cache_tuple=lambda: ("old-config-review",),
        )
        review_view = SimpleNamespace(
            job_id="review-old-config",
            chain_id="C1",
            identity=identity,
            result={},
        )
        extract_context = Mock(return_value={
            "quality_assessment": {},
            "recommendations": {},
        })
        monkeypatch.setattr(
            "nocpro_api.cohesion_advisor.extract_cohesion_context",
            extract_context,
        )
        monkeypatch.setattr(
            "nocpro_api.cohesion_advisor.build_chain_overview_projection",
            lambda _context: {},
        )
        workspace._deep_dive_context = lambda _chain_id: (package, None, None)
        workspace.jobs.latest_compatible = lambda _key: None
        workspace.latest_deep_dive = AsyncMock(return_value=None)
        workspace.latest_audit_visualization = AsyncMock(
            return_value=SimpleNamespace(audit_artifact=None)
        )
        workspace.analyze = lambda _chain_id: object()
        try:
            await workspace._materialize_chain_quality(review_view)
            assert extract_context.call_count == 0
            assert repository.payload is None
        finally:
            workspace.close()

    asyncio.run(exercise())


def test_reconciliation_replaces_stale_review_once_and_reattaches_to_persisted_current_queue(monkeypatch):
    monkeypatch.setenv("NOCPRO_AUTO_CHAIN_QUALITY", "true")

    async def exercise() -> None:
        workspace = Workspace()
        workspace.replace_snapshot(_payload())
        package = workspace.require_package()
        config = workspace.config
        current_identity = ReviewIdentity(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id="C1",
            alarm_universe_fingerprint="alarms-current",
            analysis_version=config.config_version,
            engine_version="counterfactual-p1-v1",
            config_version=(
                config.counterfactual.config_version
                if config.counterfactual is not None
                else "UNAVAILABLE"
            ),
            tier1b_artifact_fingerprint="tier1b-current",
            topology_version=_topology_version(package),
        )
        stale_identity = replace(
            current_identity,
            analysis_version="old-analysis-config",
            config_version="old-review-config",
        )
        stale_succeeded = SimpleNamespace(
            status="SUCCEEDED",
            identity=stale_identity,
            submitted_at=datetime.now(timezone.utc),
        )
        manager_jobs = [stale_succeeded]
        current_queued = SimpleNamespace(
            status="QUEUED",
            identity=current_identity,
            submitted_at=datetime.now(timezone.utc),
        )
        class RepositoryStub:
            current_review = None

            async def list_chain_quality_assessments(self, *, snapshot_id, snapshot_version):
                return []

            async def active_quality_chain_ids(self, *, snapshot_id, snapshot_version):
                return set()

            async def latest_counterfactual_job_for_identity(
                self, *, cache_fingerprint, **_kwargs
            ):
                if self.current_review is None:
                    return None
                assert cache_fingerprint == self.current_review.cache_fingerprint
                return self.current_review

        repository = RepositoryStub()
        workspace.repository = repository
        workspace._deep_dive_context = lambda _chain_id: (package, None, "deep-key")
        workspace.jobs.latest_compatible = lambda _key: SimpleNamespace(status="SUCCEEDED")
        workspace._materialize_persisted_chain_quality_if_available = AsyncMock(return_value=False)
        workspace._review_context = AsyncMock(
            return_value=(package, None, None, current_identity)
        )
        workspace.review_jobs.latest_for_identity = lambda identity: next(
            (
                candidate
                for candidate in reversed(manager_jobs)
                if candidate.identity.cache_tuple() == identity.cache_tuple()
            ),
            None,
        )

        async def submit_current_review(_chain_id):
            repository.current_review = SimpleNamespace(
                job_id="review-current-queued",
                snapshot_id=package.snapshot.snapshot_id,
                snapshot_version=package.snapshot.snapshot_version,
                chain_id="C1",
                cache_fingerprint=artifact_fingerprint(current_identity.cache_tuple()),
                identity=asdict(current_identity),
                status="QUEUED",
            )
            return current_queued

        submit_review = AsyncMock(side_effect=submit_current_review)
        workspace.submit_review = submit_review
        try:
            first = await workspace.resume_snapshot_quality()
            second = await workspace.resume_snapshot_quality()

            assert first["review_submitted"] == 1
            assert second["review_submitted"] == 0
            submit_review.assert_awaited_once_with("C1")
            assert stale_succeeded.status == "SUCCEEDED"  # old config is preserved, not reused
        finally:
            workspace.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("change_during_context", ["config", "topology"])
def test_reconciliation_discards_context_when_config_or_topology_changes_during_await(
    monkeypatch, change_during_context
):
    monkeypatch.setenv("NOCPRO_AUTO_CHAIN_QUALITY", "true")

    async def exercise() -> None:
        workspace = Workspace()
        workspace.replace_snapshot(_payload())
        package = workspace.require_package()
        config = workspace.config
        stale_context_identity = ReviewIdentity(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id="C1",
            alarm_universe_fingerprint="alarms-current",
            analysis_version=config.config_version,
            engine_version="counterfactual-p1-v1",
            config_version=(
                config.counterfactual.config_version
                if config.counterfactual is not None
                else "UNAVAILABLE"
            ),
            tier1b_artifact_fingerprint="tier1b-current",
            topology_version=_topology_version(package),
        )

        class RepositoryStub:
            async def list_chain_quality_assessments(self, *, snapshot_id, snapshot_version):
                return []

            async def active_quality_chain_ids(self, *, snapshot_id, snapshot_version):
                return set()

        workspace.repository = RepositoryStub()
        workspace._deep_dive_context = lambda _chain_id: (package, None, "deep-key")
        workspace.jobs.latest_compatible = lambda _key: SimpleNamespace(status="SUCCEEDED")
        workspace._materialize_persisted_chain_quality_if_available = AsyncMock(return_value=False)

        async def change_context(_chain_id):
            if change_during_context == "config":
                workspace.update_parameters({"s_min": 0.65})
            else:
                topology_payload = _payload()
                topology_payload["snapshot"]["topology_ref"] = {
                    "profile_id": "IP_NETWORK",
                    "topology_version": "topology-2",
                }
                workspace.replace_snapshot(topology_payload)
            return package, None, None, stale_context_identity

        workspace._review_context = AsyncMock(side_effect=change_context)
        submit_review = AsyncMock()
        workspace.submit_review = submit_review
        try:
            result = await workspace.resume_snapshot_quality()

            assert result["review_submitted"] == 0
            submit_review.assert_not_awaited()
        finally:
            workspace.close()

    asyncio.run(exercise())


def test_persisted_deep_dive_without_object_audit_uses_compatible_audit_lookup(monkeypatch):
    """Restart DTOs intentionally omit the in-memory-only Audit attribute."""

    async def exercise() -> None:
        workspace = Workspace()
        workspace.replace_snapshot(_payload())
        package = workspace.require_package()
        quality_repository = SimpleNamespace(
            persist_chain_quality_assessment=AsyncMock(return_value=None)
        )
        workspace.repository = quality_repository
        stored_result = {"analysis": {"summary": "persisted"}}
        now = datetime.now(timezone.utc)
        stored_deep_dive = StoredDeepDiveJob(
            job_id="deep-persisted",
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id="C1",
            cache_fingerprint="deep-fingerprint",
            analysis_config_version=workspace.config.config_version,
            topology_version=_topology_version(package),
            status="SUCCEEDED",
            progress_percent=100,
            cache_hit=False,
            result=stored_result,
            error=None,
            created_at=now,
            updated_at=now,
        )
        # This exact persisted type has no audit_artifact attribute. Keep it
        # as-is so direct attribute access regresses with AttributeError.
        workspace._deep_dive_context = lambda _chain_id: (package, None, "cache-key")
        workspace.jobs.latest_compatible = lambda _key: None
        workspace.latest_deep_dive = AsyncMock(return_value=stored_deep_dive)
        audit_artifact = object()
        workspace.latest_audit_visualization = AsyncMock(
            return_value=SimpleNamespace(audit_artifact=audit_artifact)
        )
        workspace.analyze = lambda _chain_id: object()
        received = {}

        def extract_context(**kwargs):
            received.update(kwargs)
            return {
                "quality_assessment": {
                    "method": "HEURISTIC_V1",
                    "status": "EVALUATED",
                    "readiness": "READY",
                    "readiness_policy_version": "quality-readiness-v1",
                    "reason_codes": [],
                    "evidence_coverage": {},
                    "stars": 4,
                    "label": "Khá vững",
                    "available_dimension_count": 3,
                    "reasons": [],
                },
                "recommendations": {"status": "AVAILABLE"},
                "topology": {},
            }

        monkeypatch.setattr(
            "nocpro_api.cohesion_advisor.extract_cohesion_context",
            extract_context,
        )
        monkeypatch.setattr(
            "nocpro_api.cohesion_advisor.build_chain_overview_projection",
            lambda _context: {},
        )
        review_identity = ReviewIdentity(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id="C1",
            alarm_universe_fingerprint="alarms-C1",
            analysis_version=workspace.config.config_version,
            engine_version="counterfactual-p1-v1",
            config_version=(
                workspace.config.counterfactual.config_version
                if workspace.config.counterfactual is not None
                else "UNAVAILABLE"
            ),
            tier1b_artifact_fingerprint="tier1b-C1-v1",
            topology_version=_topology_version(package),
        )
        workspace._review_context = AsyncMock(
            return_value=(package, None, None, review_identity)
        )
        review_view = SimpleNamespace(
            job_id="review-current",
            chain_id="C1",
            identity=review_identity,
            result={"recommendation_status": "AVAILABLE"},
        )
        try:
            await workspace._materialize_chain_quality(review_view)

            workspace.latest_deep_dive.assert_awaited_once_with("C1")
            workspace.latest_audit_visualization.assert_awaited_once_with("C1")
            assert received["deep_dive_analysis"] is stored_result
            assert received["audit_artifact"] is audit_artifact
            quality_repository.persist_chain_quality_assessment.assert_awaited_once()

            workspace.latest_audit_visualization.side_effect = RuntimeError(
                "temporary persisted Audit read failure"
            )
            with pytest.raises(RuntimeError, match="temporary persisted Audit"):
                await workspace._materialize_chain_quality(review_view)
            quality_repository.persist_chain_quality_assessment.assert_awaited_once()
        finally:
            workspace.close()

    asyncio.run(exercise())


def test_background_runner_warms_activation_for_completed_snapshot(monkeypatch):
    """A terminal quality row must not force the next portfolio click cold."""

    class RepositoryStub:
        async def ingest_direct(self, payload):
            return None

    class ActiveWorkspaceStub:
        def __init__(self):
            self.prepared = None

        def store_prepared_activation(self, payload, package, precompute, *, config_version):
            self.prepared = (payload, package, precompute, config_version)

    async def hydrate_payload(payload):
        payload.setdefault("topology", {}).update({
            "edges": [{"edge_id": "edge-1"}],
            "p2_eligible": False,
            "dependency_semantics": "UNAVAILABLE",
        })

    async def exercise() -> None:
        repository = RepositoryStub()
        active_workspace = ActiveWorkspaceStub()
        coordinator = SimpleNamespace(
            workspace=active_workspace,
            _hydrate_payload_topology_if_needed=hydrate_payload,
        )
        runner = SnapshotQualityRunner(
            repository,
            coordinator,
            config_path=Path("config/thresholds/calibrated.yaml"),
        )
        payload = _payload()
        payload["snapshot"]["topology_ref"] = {
            "profile_id": "IP_NETWORK",
            "topology_version": "topology-1",
        }
        payload["topology"] = {"edges": []}
        source = _SnapshotSource(
            snapshot_id="s1",
            snapshot_version="1",
            payload=payload,
            origin="catalog",
        )
        monkeypatch.setattr(
            runner,
            "_source_quality_complete",
            AsyncMock(return_value=True),
        )
        try:
            assert await runner._run_source(source) == "COMPLETE"
            assert active_workspace.prepared is not None
            assert active_workspace.prepared[0]["topology"]["edges"] == []
            assert active_workspace.prepared[1].topology["edges"] == [
                {"edge_id": "edge-1"}
            ]
            assert source.payload["topology"]["edges"] == []
        finally:
            await runner.stop()

    asyncio.run(exercise())


def test_stale_unavailable_quality_is_resubmitted_for_current_config(monkeypatch):
    monkeypatch.setenv("NOCPRO_AUTO_CHAIN_QUALITY", "true")

    class RepositoryStub:
        async def list_chain_quality_assessments(self, *, snapshot_id, snapshot_version):
            return [SimpleNamespace(
                chain_id="C1",
                status="UNAVAILABLE",
                payload={"overview_projection": {
                    "config_version": "old-config",
                    "projection_version": "CHAIN_OVERVIEW_V1",
                    "pipeline_version": "DETERMINISTIC_QUALITY_V1",
                    "topology_version": None,
                }},
            )]

        async def active_quality_chain_ids(self, *, snapshot_id, snapshot_version):
            return set()

        async def latest_compatible_deep_dive_job(self, **_kwargs):
            return None

    async def exercise() -> None:
        workspace = Workspace()
        workspace.replace_snapshot(_payload())
        workspace.attach_persistence(RepositoryStub(), SimpleNamespace())
        submitted = []
        workspace.submit_deep_dive = lambda chain_id: submitted.append(chain_id)
        workspace._materialize_persisted_chain_quality_if_available = AsyncMock(
            return_value=False
        )
        try:
            result = await workspace.resume_snapshot_quality()
            assert result["deep_dive_submitted"] == 1
            assert submitted == ["C1"]
        finally:
            workspace.close()

    asyncio.run(exercise())


def test_background_runner_keeps_newer_live_version_for_same_snapshot_id(monkeypatch):
    """Catalog IDs are not version identities for Kafka/direct-ingested data."""

    catalog_payload = _payload()
    live_payload = copy.deepcopy(catalog_payload)
    live_payload["snapshot"]["snapshot_version"] = "2"

    class RepositoryStub:
        async def list_live_snapshots(self, limit=200, offset=0):
            return [{"snapshot_id": "s1", "snapshot_version": "2"}]

        async def get_ready_snapshot_payload(self, snapshot_id, snapshot_version=None):
            assert snapshot_id == "s1"
            assert snapshot_version == "2"
            return live_payload

    async def exercise() -> None:
        runner = SnapshotQualityRunner(
            RepositoryStub(),
            SimpleNamespace(),
            config_path=Path("config/thresholds/calibrated.yaml"),
        )
        monkeypatch.setattr(
            "nocpro_api.quality_background.list_catalog_presets",
            lambda: [{"snapshot_id": "s1"}],
        )
        monkeypatch.setattr(
            "nocpro_api.quality_background.load_preset_payload",
            lambda snapshot_id: (catalog_payload, None),
        )
        try:
            sources = await runner._sources()
            assert {source.identity for source in sources} == {("s1", "1"), ("s1", "2")}
        finally:
            await runner.stop()

    asyncio.run(exercise())


def test_background_runner_bounds_scheduled_snapshot_tasks(monkeypatch):
    async def exercise() -> None:
        runner = SnapshotQualityRunner(
            SimpleNamespace(),
            SimpleNamespace(workspace=None),
            config_path=Path("config/thresholds/calibrated.yaml"),
        )
        runner.max_workers = 2
        runner._semaphore = asyncio.Semaphore(2)
        runner.interval_seconds = 3600
        sources = [
            _SnapshotSource(
                snapshot_id=f"s{index}",
                snapshot_version="1",
                payload=_payload(),
                origin="catalog",
            )
            for index in range(5)
        ]

        async def get_sources():
            return sources

        started = asyncio.Event()
        release = asyncio.Event()

        async def hold_source(*_args, **_kwargs):
            started.set()
            await release.wait()
            return "STOPPED"

        monkeypatch.setattr(runner, "_sources", get_sources)
        monkeypatch.setattr(runner, "_run_source", hold_source)
        monkeypatch.setattr(
            "nocpro_api.quality_background.effective_topology_version",
            AsyncMock(return_value=None),
        )
        runner.start()
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            await asyncio.sleep(0)
            scheduled = [task for task in runner._source_tasks.values() if not task.done()]
            assert len(scheduled) <= runner.max_workers
        finally:
            release.set()
            await runner.stop()

    asyncio.run(exercise())


def test_background_runner_retries_durable_registration_after_failure():
    class RepositoryStub:
        def __init__(self) -> None:
            self.attempts = 0

        async def ingest_direct(self, _payload):
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("temporary database disconnect")
            return None

    async def exercise() -> None:
        repository = RepositoryStub()
        runner = SnapshotQualityRunner(
            repository,
            SimpleNamespace(),
            config_path=Path("config/thresholds/calibrated.yaml"),
        )
        source = _SnapshotSource(
            snapshot_id="s1",
            snapshot_version="1",
            payload=_payload(),
            origin="catalog",
        )
        try:
            assert await runner._ensure_durable(source) is False
            assert source.identity not in runner._ingested
            assert await runner._ensure_durable(source) is True
            assert repository.attempts == 2
            assert source.identity in runner._ingested
        finally:
            await runner.stop()

    asyncio.run(exercise())

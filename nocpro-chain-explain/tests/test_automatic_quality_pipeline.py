from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from nocpro_api.quality_background import (
    SnapshotQualityRunner,
    _SnapshotSource,
    _is_terminal_quality_row,
)
from nocpro_api.workspace import Workspace, _topology_version

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
        identity = SimpleNamespace(
            snapshot_id="s1",
            snapshot_version="1",
            analysis_version=workspace.config.config_version,
            config_version=(
                workspace.config.counterfactual.config_version
                if workspace.config.counterfactual is not None
                else "UNAVAILABLE"
            ),
            cache_tuple=lambda: ("s1", "1", "C1", "review-v1"),
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
            assert projection["projection_version"] == "CHAIN_OVERVIEW_V3"
            assert "display_paths" in projection["topology"]
            assert "mapped_resources" in projection["topology"]
            assert projection["topology"]["display_paths_truncated"] is False
            assert projection["pipeline_version"] == "DETERMINISTIC_QUALITY_V3"
            assert projection["quality_assessment"]["stars"] == 4
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

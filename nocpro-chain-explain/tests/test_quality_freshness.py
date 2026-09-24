"""Topology changes must invalidate every reader of persisted quality."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from contracts.v1.models import TopologyRef
from libs.contracts import load_validated_package
from libs.contracts.topology_identity import effective_topology_version
from nocpro_api.quality_freshness import projection_staleness_reason, terminal_quality_row_is_current
from nocpro_api.persistence import IngestResult
from nocpro_api.workspace import Workspace
from tests.test_api import _payload
from nocpro_api.routes import (
    _active_unpinned_topology_is_stale,
    _build_persisted_quality_summaries,
    _cohesion_input_fingerprint,
)


def _projection(version: str) -> dict:
    identity = {
        "identity_version": "analysis-identity-v1",
        "snapshot_id": "S1",
        "snapshot_version": "v1",
        "chain_id": "C1",
        "topology_version": version,
        "analysis_config_version": "config-1",
        "review_config_version": "review-config-1",
        "pipeline_version": "DETERMINISTIC_QUALITY_V6",
        "input_fingerprint": "quality-fingerprint-1",
    }
    return {
        "projection_version": "CHAIN_OVERVIEW_V6",
        "pipeline_version": "DETERMINISTIC_QUALITY_V6",
        "snapshot_id": "S1",
        "snapshot_version": "v1",
        "chain_id": "C1",
        "config_version": "config-1",
        "review_config_version": "review-config-1",
        "topology_version": version,
        "input_fingerprint": "quality-fingerprint-1",
        "analysis_identity": identity,
    }


def test_one_quality_freshness_contract_rejects_old_topology():
    old = _projection("topology-1")
    assert projection_staleness_reason(old, topology_version="topology-2") == "TOPOLOGY_MISMATCH"
    old_quality_pipeline = _projection("topology-2")
    old_quality_pipeline["pipeline_version"] = "DETERMINISTIC_QUALITY_V3"
    old_quality_pipeline["analysis_identity"]["pipeline_version"] = "DETERMINISTIC_QUALITY_V3"
    assert projection_staleness_reason(old_quality_pipeline) == "PIPELINE_STALE"
    legacy_projection = _projection("topology-2")
    legacy_projection["projection_version"] = "CHAIN_OVERVIEW_V2"
    assert projection_staleness_reason(
        legacy_projection, topology_version="topology-2"
    ) == "PROJECTION_STALE"
    row = SimpleNamespace(
        snapshot_id="S1", snapshot_version="v1", chain_id="C1",
        input_fingerprint="quality-fingerprint-1",
        status="EVALUATED", stars=4,
        payload={
            "status": "EVALUATED",
            "readiness": "READY",
            "readiness_policy_version": "quality-readiness-v1",
            "reason_codes": [],
            "evidence_coverage": {},
            "stars": 4,
            "overview_projection": old,
        },
    )
    assert not terminal_quality_row_is_current(
        row, snapshot_id="S1", snapshot_version="v1",
        config_version="config-1", topology_version="topology-2",
    )
    chain = SimpleNamespace(
        snapshot_id="S1", snapshot_version="v1", chain_id="C1",
        member_count=2, chain_name="C1", event_span_seconds=1,
    )
    summary = _build_persisted_quality_summaries(
        [chain], [row], [], expected_config_version="config-1",
        expected_topology_versions={("S1", "v1"): "topology-2"},
    )[0]
    assert summary.sturdy_count == 0
    assert summary.unevaluated_count == 1
    assert summary.chain_assessments[0].stars is None


def test_terminal_quality_requires_canonical_row_and_payload_stars_to_match():
    payload = {
        "status": "EVALUATED",
        "readiness": "READY",
        "readiness_policy_version": "quality-readiness-v1",
        "reason_codes": [],
        "evidence_coverage": {},
        "stars": 4,
        "overview_projection": _projection("topology-2"),
    }
    row = SimpleNamespace(
        snapshot_id="S1",
        snapshot_version="v1",
        chain_id="C1",
        input_fingerprint="quality-fingerprint-1",
        status="EVALUATED",
        stars=4,
        payload=payload,
    )

    assert terminal_quality_row_is_current(
        row,
        snapshot_id="S1",
        snapshot_version="v1",
        config_version="config-1",
        topology_version="topology-2",
    )
    row.stars = 3
    assert not terminal_quality_row_is_current(
        row,
        snapshot_id="S1",
        snapshot_version="v1",
        config_version="config-1",
        topology_version="topology-2",
    )


def test_cohesion_cache_fingerprint_tracks_topology_version():
    snapshot = SimpleNamespace(topology_ref=SimpleNamespace(topology_version="topology-1"))
    service = SimpleNamespace(config=SimpleNamespace(config_version="config-1"), package=SimpleNamespace(snapshot=snapshot))
    kwargs = {"audit_artifact": None, "deep_dive_job": None, "review_job": None}
    first = _cohesion_input_fingerprint(service, **kwargs)
    snapshot.topology_ref.topology_version = "topology-2"
    assert _cohesion_input_fingerprint(service, **kwargs) != first


def test_unpinned_snapshot_uses_new_active_topology_without_changing_snapshot_version():
    class TopologyRepository:
        active = "topology-1"

        async def get_active_version(self, profile_id: str):
            assert profile_id == "IP_NETWORK"
            return SimpleNamespace(topology_version=self.active)

    async def exercise():
        repository = TopologyRepository()
        kwargs = {
            "pinned_version": None,
            "explicit_profile": "IP_NETWORK",
            "repository": repository,
        }
        first = await effective_topology_version("live-snapshot", **kwargs)
        repository.active = "topology-2"
        second = await effective_topology_version("live-snapshot", **kwargs)
        pinned = await effective_topology_version(
            "live-snapshot", pinned_version="topology-1",
            explicit_profile="IP_NETWORK", repository=repository,
        )
        assert (first, second, pinned) == ("topology-1", "topology-2", "topology-1")

    asyncio.run(exercise())


def test_open_unpinned_snapshot_is_stale_after_kafka_topology_activation():
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _model, _identity):
            return SimpleNamespace(topology_profile_id="IP_NETWORK", topology_version_ref=None)

    class TopologyRepository:
        active = "topology-2"

        async def get_active_version(self, _profile_id):
            return SimpleNamespace(topology_version=self.active)

    class Repository:
        def sessions(self):
            return Session()

    package = SimpleNamespace(snapshot=SimpleNamespace(
        snapshot_id="S1", snapshot_version="v1",
        topology_ref=SimpleNamespace(profile_id="IP_NETWORK", topology_version="topology-1"),
    ))
    service = SimpleNamespace(repository=Repository())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(topology_repository=TopologyRepository())))
    assert asyncio.run(_active_unpinned_topology_is_stale(service, request, package))


def test_reopening_unpinned_snapshot_rebuilds_old_in_memory_topology():
    payload = _payload()
    snapshot_id = "live_ip_snapshot"
    payload["snapshot"]["snapshot_id"] = snapshot_id
    for collection in ("alarms", "chains", "memberships"):
        for row in payload[collection]:
            row["snapshot_id"] = snapshot_id

    class Repository:
        async def ingest_direct(self, _payload):
            return IngestResult(snapshot_id, "1", "COMPLETE", duplicate=True, completed_now=False)

    class TopologyRepository:
        async def get_active_version(self, _profile):
            return SimpleNamespace(topology_version="topology-2")

    class Coordinator:
        topology_repository = TopologyRepository()

        async def _hydrate_payload_topology_if_needed(self, source):
            pinned = deepcopy(source)
            pinned["snapshot"]["topology_ref"] = {
                "profile_id": "IP_NETWORK", "topology_version": "topology-2",
            }
            return load_validated_package(pinned)

    workspace = Workspace()
    try:
        workspace.replace_snapshot(payload)
        old_package = workspace.require_package()
        old_package.snapshot = replace(
            old_package.snapshot,
            topology_ref=TopologyRef("IP_NETWORK", "topology-1"),
        )
        old_package.topology["edges"] = [{"edge_id": "old"}]
        workspace.repository = Repository()
        workspace.coordinator = Coordinator()

        asyncio.run(workspace.ingest_snapshot(payload))
        assert workspace.require_package() is not old_package
        assert workspace.require_package().snapshot.topology_ref.topology_version == "topology-2"
    finally:
        workspace.close()

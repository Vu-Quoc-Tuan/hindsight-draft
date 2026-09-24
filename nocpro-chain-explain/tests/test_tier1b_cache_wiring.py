"""Tier-1B cache wiring at the Workspace/API service boundary."""

from __future__ import annotations

from dataclasses import replace

from nocpro_api.workspace import Workspace
from tier1a import CacheTier


def _payload(*, snapshot_version: str = "1") -> dict:
    snapshot_id = "tier1b-cache-snapshot"
    alarms = [
        {
            "alarm_id": alarm_id,
            "snapshot_id": snapshot_id,
            "source_kind": "SYNTHETIC_TEST",
            "provenance_class": "SYSTEM_FACT",
            "raw": {"location_code": "SITE-A"},
            "alarm_name": "LINK DOWN",
            "device_code": "D1",
            "node_reference": "R1",
            "canonical_start_time": f"2026-01-01T00:00:0{index}",
        }
        for index, alarm_id in enumerate(("a1", "a2", "a3"), start=1)
    ]
    return {
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": snapshot_id,
            "snapshot_version": snapshot_version,
            "snapshot_time": "2026-01-01T00:00:00",
            "status": "COMPLETE",
            "source": "tier1b-cache-test",
            "source_kind": "SYNTHETIC_TEST",
            "produced_at": "2026-01-01T00:00:00",
        },
        "alarms": alarms,
        "chains": [
            {
                "chain_id": "C1",
                "snapshot_id": snapshot_id,
                "member_count": len(alarms),
                "source_kind": "SYNTHETIC_TEST",
                "provenance_class": "SYSTEM_FACT",
            }
        ],
        "memberships": [
            {
                "chain_id": "C1",
                "alarm_id": alarm["alarm_id"],
                "snapshot_id": snapshot_id,
                "source_kind": "SYNTHETIC_TEST",
            }
            for alarm in alarms
        ],
    }


def test_workspace_tier1b_first_compute_then_cache_hit(monkeypatch) -> None:
    workspace = Workspace()
    workspace.replace_snapshot(_payload())
    calls: list[object] = []
    artifact = object()

    def analyze(*args, **kwargs):
        calls.append((args, kwargs))
        return artifact

    monkeypatch.setattr("nocpro_api.workspace.analyze_chain_configured", analyze)
    initial_hits, initial_misses = workspace.cache.hits, workspace.cache.misses

    assert workspace.analyze("C1") is artifact
    assert workspace.analyze("C1") is artifact

    assert len(calls) == 1
    assert workspace.cache.hits == initial_hits + 1
    assert workspace.cache.misses == initial_misses + 1
    entries = workspace.cache.tier_entries(CacheTier.TIER_1B)
    assert len(entries) == 1
    assert entries[0].snapshot_chain_id == "C1"


def test_workspace_tier1b_config_version_change_misses(monkeypatch) -> None:
    workspace = Workspace()
    workspace.replace_snapshot(_payload())
    calls: list[object] = []

    def analyze(*args, **kwargs):
        artifact = object()
        calls.append(artifact)
        return artifact

    monkeypatch.setattr("nocpro_api.workspace.analyze_chain_configured", analyze)

    first = workspace.analyze("C1")
    workspace.config = replace(workspace.config, config_version="tier1b-cache-v2")
    second = workspace.analyze("C1")

    assert first is not second
    assert len(calls) == 2
    assert {
        entry.key.config_version
        for entry in workspace.cache.tier_entries(CacheTier.TIER_1B)
    } == {"v1", "tier1b-cache-v2"}


def test_workspace_tier1b_snapshot_versions_do_not_collide(monkeypatch) -> None:
    workspace = Workspace()
    calls: list[object] = []

    def analyze(*args, **kwargs):
        artifact = object()
        calls.append(artifact)
        return artifact

    monkeypatch.setattr("nocpro_api.workspace.analyze_chain_configured", analyze)

    workspace.replace_snapshot(_payload(snapshot_version="1"))
    first = workspace.analyze("C1")
    workspace.replace_snapshot(_payload(snapshot_version="2"))
    second = workspace.analyze("C1")

    assert first is not second
    assert len(calls) == 2
    assert {
        entry.key.snapshot_version
        for entry in workspace.cache.tier_entries(CacheTier.TIER_1B)
    } == {"2"}

    workspace.replace_snapshot(_payload(snapshot_version="1"))
    third = workspace.analyze("C1")
    assert third is not first
    assert len(calls) == 3
    assert {
        entry.key.snapshot_version
        for entry in workspace.cache.tier_entries(CacheTier.TIER_1B)
    } == {"1"}


def test_workspace_restart_recomputes_memory_only_tier1b_cache(monkeypatch) -> None:
    calls: list[object] = []

    def analyze(*args, **kwargs):
        artifact = object()
        calls.append(artifact)
        return artifact

    monkeypatch.setattr("nocpro_api.workspace.analyze_chain_configured", analyze)

    first_workspace = Workspace()
    first_workspace.replace_snapshot(_payload())
    first_workspace.analyze("C1")
    first_workspace.close()

    restarted_workspace = Workspace()
    restarted_workspace.replace_snapshot(_payload())
    restarted_workspace.analyze("C1")
    restarted_workspace.close()

    assert len(calls) == 2

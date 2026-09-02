"""Layer 4 — history and evolution sequences (Decisions 1 & 2).

Frozen rules:
  - the canonical unit stays 1 MockSnapshotPackage = 1 snapshot
  - contract v1 gains no multi-snapshot object
  - synthetic snapshots keep source_kind=SYNTHETIC_TEST; HISTORY_BOOTSTRAP is a
    delivery role, not a provenance value
  - history is strictly before the target (ADR-MOCK-0006)
  - known support/lift live only in expected_assertions
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest
import yaml

from nocpro_mock.config import GENERATOR_VERSION
from nocpro_mock.contract import MockSnapshotPackage, SourceKind, validate_package
from nocpro_mock.producer import DirectSnapshotProducer
from nocpro_mock.replay import SequenceRunner, validate_sequence_payloads
from nocpro_mock.scenarios import (
    COUNTERFACTUAL_FIXTURES,
    EVOLUTION_SPLIT_MERGE,
    HISTORY_POSITIVE_LIFT,
    INTEGRATED_TEMPORAL_TOPOLOGY,
    EvolutionEvent,
    ScenarioError,
    SequenceType,
    build_synthetic_snapshot,
    load_sequence_manifest,
    parse_sequence_manifest,
)
from tests.conftest import REPO_ROOT

SYNTHETIC_DIR = REPO_ROOT / "docs/examples/synthetic"
HISTORY_DIR = SYNTHETIC_DIR / "history_positive_lift"
EVOLUTION_DIR = SYNTHETIC_DIR / "evolution_split_merge"
TEMPORAL_TOPOLOGY_DIR = SYNTHETIC_DIR / "temporal_topology"


def _built(directory):
    """Skip when sequence JSON has not been materialized yet."""
    if not (directory / "snapshot_000.json").is_file():
        pytest.skip(f"run 'nocpro-mock build-sequences' first: {directory}")
    return directory


# --------------------------------------------------------------------------
# Contract shape
# --------------------------------------------------------------------------


def test_contract_has_no_multi_snapshot_object():
    """Sequencing must stay orchestration, not a canonical input object."""
    fields = {f.name for f in dataclasses.fields(MockSnapshotPackage)}
    assert "snapshots" not in fields
    assert "sequence" not in fields
    import nocpro_mock.contract as bridge

    for forbidden in ("MegaSequencePackage", "SnapshotSequence", "HistoricalEpisode"):
        assert not hasattr(bridge, forbidden)


# --------------------------------------------------------------------------
# Manifest parsing
# --------------------------------------------------------------------------


def test_history_manifest_parses():
    manifest = load_sequence_manifest(HISTORY_DIR / "sequence.yaml")
    assert manifest.scenario_id == "history_positive_lift_v1"
    assert manifest.sequence_type is SequenceType.HISTORY_BOOTSTRAP
    assert manifest.seed == 42
    assert len(manifest.snapshots) == 4
    assert manifest.target_snapshot == "snapshot_003.json"


def test_history_window_excludes_the_target():
    """ADR-MOCK-0006: the target cannot manufacture its own prior history."""
    manifest = load_sequence_manifest(HISTORY_DIR / "sequence.yaml")
    history = manifest.history_snapshots
    assert history == (
        "snapshot_000.json",
        "snapshot_001.json",
        "snapshot_002.json",
    )
    assert manifest.target_snapshot not in history


def test_history_bootstrap_requires_a_boundary():
    with pytest.raises(ScenarioError, match="history_until_exclusive"):
        parse_sequence_manifest(
            {
                "scenario_id": "x",
                "sequence_type": "HISTORY_BOOTSTRAP",
                "seed": 1,
                "snapshots": ["a.json", "b.json"],
            }
        )


def test_target_must_match_the_history_boundary():
    with pytest.raises(ScenarioError, match="must equal"):
        parse_sequence_manifest(
            {
                "scenario_id": "x",
                "sequence_type": "HISTORY_BOOTSTRAP",
                "seed": 1,
                "snapshots": ["a.json", "b.json", "c.json"],
                "target_snapshot": "c.json",
                "delivery": {"history_until_exclusive": "b.json"},
            }
        )


def test_evolution_manifest_parses():
    manifest = load_sequence_manifest(EVOLUTION_DIR / "sequence.yaml")
    assert manifest.sequence_type is SequenceType.EVOLUTION
    events = [t.expected_event for t in manifest.expected_transitions]
    assert events == [EvolutionEvent.SPLIT, EvolutionEvent.MERGE]


def test_temporal_topology_manifest_covers_required_events():
    manifest = load_sequence_manifest(TEMPORAL_TOPOLOGY_DIR / "sequence.yaml")
    assert manifest.scenario_id == "synthetic_temporal_topology_v1"
    assert manifest.sequence_type is SequenceType.EVOLUTION
    assert len(manifest.snapshots) == 6
    assert [item.expected_event for item in manifest.expected_transitions] == [
        EvolutionEvent.CONTINUE,
        EvolutionEvent.GROW,
        EvolutionEvent.SPLIT,
        EvolutionEvent.MERGE,
        EvolutionEvent.SHRINK,
    ]


def test_evolution_requires_transitions():
    with pytest.raises(ScenarioError, match="requires expected_transitions"):
        parse_sequence_manifest(
            {
                "scenario_id": "x",
                "sequence_type": "EVOLUTION",
                "seed": 1,
                "snapshots": ["a.json", "b.json"],
            }
        )


def test_transitions_must_be_between_consecutive_snapshots():
    with pytest.raises(ScenarioError, match="consecutive"):
        parse_sequence_manifest(
            {
                "scenario_id": "x",
                "sequence_type": "EVOLUTION",
                "seed": 1,
                "snapshots": ["a.json", "b.json", "c.json"],
                "expected_transitions": [
                    {"from": "a.json", "to": "c.json", "expected_event": "SPLIT"}
                ],
            }
        )


def test_unknown_event_is_refused():
    with pytest.raises(ScenarioError, match="unknown expected_event"):
        parse_sequence_manifest(
            {
                "scenario_id": "x",
                "sequence_type": "EVOLUTION",
                "seed": 1,
                "snapshots": ["a.json", "b.json"],
                "expected_transitions": [
                    {"from": "a.json", "to": "b.json", "expected_event": "TELEPORT"}
                ],
            }
        )


def test_single_snapshot_is_not_a_sequence():
    with pytest.raises(ScenarioError, match="at least two snapshots"):
        parse_sequence_manifest(
            {
                "scenario_id": "x",
                "sequence_type": "EVOLUTION",
                "seed": 1,
                "snapshots": ["a.json"],
            }
        )


def test_all_evolution_events_are_expressible():
    """docs 07 §6 lists eight transition kinds; all must be declarable."""
    required = {
        "CONTINUE",
        "GROW",
        "SHRINK",
        "SPLIT",
        "MERGE",
        "RECOMBINATION",
        "CHAIN_ID_CHANGE",
        "SINGLETON_TO_MULTI",
        "MULTI_TO_SINGLETON",
    }
    assert required <= {e.value for e in EvolutionEvent}


# --------------------------------------------------------------------------
# Snapshot building
# --------------------------------------------------------------------------


def test_synthetic_snapshot_keeps_synthetic_provenance():
    """HISTORY_BOOTSTRAP must not overwrite source_kind with BACKFILL."""
    package = build_synthetic_snapshot(
        scenario_id="history_positive_lift_v1",
        seed=42,
        generator_version=GENERATOR_VERSION,
        snapshot_index=0,
        chains={"SYN-CHAIN-H0": ["SYN-ALARM-A1", "SYN-ALARM-B1"]},
        generation_rule="HISTORY_BOOTSTRAP sequence member 0",
    )
    assert package.snapshot.source_kind is SourceKind.SYNTHETIC_TEST
    assert all(a.source_kind is SourceKind.SYNTHETIC_TEST for a in package.alarms)
    assert all(c.source_kind is SourceKind.SYNTHETIC_TEST for c in package.chains)
    assert validate_package(package).ok


def test_synthetic_snapshot_is_deterministic():
    def build():
        return build_synthetic_snapshot(
            scenario_id="split_then_merge_v1",
            seed=42,
            generator_version=GENERATOR_VERSION,
            snapshot_index=1,
            chains={"SYN-CHAIN-B": ["SYN-ALARM-01", "SYN-ALARM-02"]},
        )

    producer = DirectSnapshotProducer()
    assert producer.render(build()) == producer.render(build())


def test_synthetic_snapshot_canonical_times_are_timezone_qualified():
    package = build_synthetic_snapshot(
        scenario_id="synthetic_temporal_contract_v1",
        seed=42,
        generator_version=GENERATOR_VERSION,
        snapshot_index=0,
        chains={"SYN-CHAIN-TIME": ["SYN-ALARM-TIME-1", "SYN-ALARM-TIME-2"]},
    )

    assert datetime.fromisoformat(package.snapshot.snapshot_time).tzinfo is not None
    assert all(
        datetime.fromisoformat(alarm.canonical_start_time).tzinfo is not None
        for alarm in package.alarms
    )


def test_duplicate_member_is_refused():
    with pytest.raises(ValueError, match="lists an alarm twice"):
        build_synthetic_snapshot(
            scenario_id="x",
            seed=1,
            generator_version=GENERATOR_VERSION,
            snapshot_index=0,
            chains={"SYN-CHAIN-A": ["SYN-ALARM-01", "SYN-ALARM-01"]},
        )


# --------------------------------------------------------------------------
# Step-mode replay
# --------------------------------------------------------------------------


def test_history_sequence_steps_in_order():
    runner = SequenceRunner(_built(HISTORY_DIR))
    steps = runner.run()
    assert [s.name for s in steps] == list(runner.manifest.snapshots)
    assert [s.index for s in steps] == [0, 1, 2, 3]


def test_step_returns_none_when_exhausted():
    runner = SequenceRunner(_built(EVOLUTION_DIR))
    for _ in range(len(runner)):
        assert runner.step() is not None
    assert runner.step() is None
    assert runner.exhausted


def test_history_then_target_split():
    runner = SequenceRunner(_built(HISTORY_DIR))
    history, target = runner.history_then_target()
    assert [s.name for s in history] == [
        "snapshot_000.json",
        "snapshot_001.json",
        "snapshot_002.json",
    ]
    assert target is not None
    assert target.name == "snapshot_003.json"
    assert target not in history


def test_history_then_target_rejects_evolution_sequences():
    runner = SequenceRunner(_built(EVOLUTION_DIR))
    with pytest.raises(ValueError, match="HISTORY_BOOTSTRAP"):
        runner.history_then_target()


def test_every_sequence_snapshot_validates():
    for directory in (HISTORY_DIR, EVOLUTION_DIR, TEMPORAL_TOPOLOGY_DIR):
        assert validate_sequence_payloads(_built(directory)) == []


def test_temporal_topology_sequence_carries_exact_versioned_capabilities():
    runner = SequenceRunner(_built(TEMPORAL_TOPOLOGY_DIR))
    for step in runner.run():
        topology = step.payload["topology"]
        assert topology["edges"]
        assert topology["active_paths"]
        assert topology["failure_domains"]
        assert topology["mappings"]
        assert {
            mapping["alarm_id"] for mapping in topology["mappings"]
        } == {alarm["alarm_id"] for alarm in step.payload["alarms"]}
        assert all(
            mapping["mapping_status"] == "EXACT"
            and mapping["mapping_method"] == "EXACT_IDENTITY"
            and mapping["mapping_confidence"] == 1.0
            and mapping["source_version"] == "syn-topo-temporal-v1"
            for mapping in topology["mappings"]
        )
        assert all(
            edge["source_kind"] == "SYNTHETIC_TEST"
            and edge["source_id"] == "synthetic-topology"
            and edge["source_version"] == "syn-topo-temporal-v1"
            for edge in topology["edges"]
        )
        assert step.payload["provenance_manifest"]["generator_version"] == (
            "mockgen-integrated-v1"
        )


def test_each_sequence_file_is_a_single_snapshot_package():
    """No file may contain a bundled list of snapshots."""
    runner = SequenceRunner(_built(EVOLUTION_DIR))
    for step in runner.run():
        assert isinstance(step.payload, dict)
        assert "snapshot" in step.payload
        assert isinstance(step.payload["snapshot"], dict)
        assert "snapshots" not in step.payload


def test_evolution_membership_matches_declared_transitions():
    """1 chain -> 2 chains (SPLIT) -> 1 chain (MERGE), IDs changing each step."""
    runner = SequenceRunner(_built(EVOLUTION_DIR))
    steps = runner.run()
    chain_counts = [len(s.payload["chains"]) for s in steps]
    assert chain_counts == [1, 2, 1]

    ids_per_step = [{c["chain_id"] for c in s.payload["chains"]} for s in steps]
    # Chain IDs are snapshot-scoped, so none may repeat across steps.
    assert ids_per_step[0].isdisjoint(ids_per_step[1])
    assert ids_per_step[1].isdisjoint(ids_per_step[2])
    assert ids_per_step[0].isdisjoint(ids_per_step[2])

    members = [
        {m["alarm_id"] for m in s.payload["memberships"]} for s in steps
    ]
    # Membership is restored at the end even though the chain ID differs.
    assert members[0] == members[2]


def test_history_sequence_repeats_the_family_pair():
    """Support must come from history snapshots, not the target."""
    runner = SequenceRunner(_built(HISTORY_DIR))
    history, target = runner.history_then_target()
    for step in history:
        families = {a.get("alarm_name") for a in step.payload["alarms"]}
        assert families == {"SYN-FAMILY-A", "SYN-FAMILY-B"}
    assert len(history) == 3
    target_families = {a.get("alarm_name") for a in target.payload["alarms"]}
    assert target_families == {"SYN-FAMILY-A", "SYN-FAMILY-B"}


# --------------------------------------------------------------------------
# Expected assertions files
# --------------------------------------------------------------------------


def test_history_assertions_hold_the_known_numbers_only():
    """docs 08: mock must not emit H.support / H.lift as source truth."""
    data = yaml.safe_load(
        (HISTORY_DIR / "expected_assertions.yaml").read_text(encoding="utf-8")
    )
    assert data["expected"]["support"] == 3
    assert data["expected"]["lift_greater_than"] == 1.0
    assert "H.support" in data["must_not_emit"]
    assert "H.lift" in data["must_not_emit"]


def test_history_support_matches_the_generated_history_length():
    data = yaml.safe_load(
        (HISTORY_DIR / "expected_assertions.yaml").read_text(encoding="utf-8")
    )
    manifest = load_sequence_manifest(HISTORY_DIR / "sequence.yaml")
    assert data["expected"]["support"] == len(manifest.history_snapshots)


def test_mock_output_never_contains_history_scores():
    """The forbidden keys must be absent from every emitted snapshot."""
    runner = SequenceRunner(_built(HISTORY_DIR))
    for step in runner.run():
        text = str(step.payload)
        for forbidden in ("H.support", "H.lift", "H.reliability"):
            assert forbidden not in text


def test_fixture_definitions_match_their_manifests():
    for fixture, directory in (
        (HISTORY_POSITIVE_LIFT, HISTORY_DIR),
        (EVOLUTION_SPLIT_MERGE, EVOLUTION_DIR),
        (INTEGRATED_TEMPORAL_TOPOLOGY, TEMPORAL_TOPOLOGY_DIR),
    ):
        manifest = load_sequence_manifest(directory / "sequence.yaml")
        assert fixture.scenario_id == manifest.scenario_id
        assert len(fixture.snapshots) == len(manifest.snapshots)


def test_counterfactual_fixtures_are_reproducible_and_truth_is_external() -> None:
    producer = DirectSnapshotProducer()
    for fixture in COUNTERFACTUAL_FIXTURES:
        package = build_synthetic_snapshot(
            scenario_id=fixture.scenario_id,
            seed=42,
            generator_version=GENERATOR_VERSION,
            snapshot_index=0,
            chains=fixture.snapshot_chains(),
            alarm_profiles=fixture.alarm_profiles,
            generation_rule=f"COUNTERFACTUAL {fixture.mutation} fixture",
        )
        materialized = (
            SYNTHETIC_DIR / fixture.directory / "snapshot_000.json"
        ).read_text(encoding="utf-8")
        assert producer.render(package) == materialized.rstrip("\n")
        assert "truth_partition" not in materialized


def test_alarm_profiles_control_only_explicit_synthetic_fields() -> None:
    package = build_synthetic_snapshot(
        scenario_id="synthetic_profile_contract_v1",
        seed=42,
        generator_version=GENERATOR_VERSION,
        snapshot_index=0,
        chains={"SYN-CHAIN-PROFILE": ["SYN-ALARM-PROFILE"]},
        alarm_profiles={
            "SYN-ALARM-PROFILE": {
                "device_code": "SYN-DEVICE-PROFILE",
                "node_reference": "SYN-REF-PROFILE",
                "start_offset_seconds": 600,
            }
        },
    )
    alarm = package.alarms[0]
    assert alarm.device_code == "SYN-DEVICE-PROFILE"
    assert alarm.node_reference == "SYN-REF-PROFILE"
    assert alarm.canonical_start_time.endswith("00:10:00+00:00")

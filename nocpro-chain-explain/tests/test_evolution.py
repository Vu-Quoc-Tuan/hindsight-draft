"""Evolution engine tests (§7, ADR-0020).

Pinned invariants:
  - same membership with a new raw chain ID is CONTINUE
  - delta_size=0 with +10/-10 still reports turnover 20
  - the small-chain exception is applied explicitly
  - >=2 parents and >=2 children is RECOMBINATION, not a forced split/merge
"""

from __future__ import annotations

import json
import pathlib

import pytest

from evolution import (
    DEFAULT_M_MIN,
    AlarmLifecycle,
    EvolutionEvent,
    LineageConfig,
    MembershipStability,
    alarm_lifecycle,
    analyze_evolution,
    build_lineage_components,
    build_lineage_edges,
    decompose,
    membership_stability,
)
from libs.contracts import load_package
from tests.conftest import MOCK_ROOT

CONFIG = LineageConfig(config_version="evo-v1")


def _package(snapshot_id: str, chains: dict[str, list[str]]):
    alarms = []
    memberships = []
    seen: set[str] = set()
    for chain_id, members in chains.items():
        for alarm_id in members:
            if alarm_id not in seen:
                alarms.append(
                    {"alarm_id": alarm_id, "snapshot_id": snapshot_id, "raw": {}}
                )
                seen.add(alarm_id)
            memberships.append(
                {
                    "chain_id": chain_id,
                    "alarm_id": alarm_id,
                    "snapshot_id": snapshot_id,
                }
            )
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": snapshot_id,
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "test",
                "source_kind": "REAL_EXPORT_REPLAY",
                "produced_at": "2026-01-01T00:00:00",
                "schema_version": "v1",
            },
            "alarms": alarms,
            "chains": [
                {
                    "chain_id": chain_id,
                    "snapshot_id": snapshot_id,
                    "member_count": len(members),
                }
                for chain_id, members in chains.items()
            ],
            "memberships": memberships,
        }
    )


# --------------------------------------------------------------------------
# Step 1-2: lifecycle
# --------------------------------------------------------------------------


def test_lifecycle_splits_new_cleared_and_active_both():
    previous = _package("s1", {"A": ["a1", "a2", "a3"]})
    current = _package("s2", {"A": ["a2", "a3", "a4"]})
    lifecycle = alarm_lifecycle(previous, current)
    assert lifecycle.new_alarms == {"a4"}
    assert lifecycle.cleared_alarms == {"a1"}
    assert lifecycle.active_both == {"a2", "a3"}
    assert lifecycle.turnover == 2


# --------------------------------------------------------------------------
# Step 3: lineage edges
# --------------------------------------------------------------------------


def test_standard_edge_requires_m_min_shared():
    previous = {"A": frozenset({"a1", "a2", "a3", "a4"})}
    # Only 2 shared, below m_min=3, and both chains are large enough that the
    # small-chain exception does not apply.
    current = {"B": frozenset({"a1", "a2", "x1", "x2"})}
    assert build_lineage_edges(previous, current, CONFIG) == []


def test_standard_edge_forms_with_enough_containment():
    previous = {"A": frozenset({"a1", "a2", "a3", "a4"})}
    current = {"B": frozenset({"a1", "a2", "a3", "x1"})}
    edges = build_lineage_edges(previous, current, CONFIG)
    assert len(edges) == 1
    assert edges[0].shared == 3
    assert edges[0].small_chain_rule is False
    assert edges[0].contain_parent == pytest.approx(0.75)


def test_small_chain_exception_uses_exact_containment():
    """A 2-member chain can never reach n_ij >= 3, so it needs the exception."""
    previous = {"A": frozenset({"a1", "a2"})}
    current = {"B": frozenset({"a1", "a2"})}
    edges = build_lineage_edges(previous, current, CONFIG)
    assert len(edges) == 1
    assert edges[0].small_chain_rule is True
    assert edges[0].jaccard == pytest.approx(1.0)


def test_small_chain_exception_rejects_weak_overlap():
    previous = {"A": frozenset({"a1", "a2"})}
    current = {"B": frozenset({"a1", "x1", "x2", "x3", "x4"})}
    # Jaccard 1/6 is below the floor and containment is not exact.
    assert build_lineage_edges(previous, current, CONFIG) == []


def test_small_chain_threshold_matches_m_min():
    assert DEFAULT_M_MIN == 3


# --------------------------------------------------------------------------
# Step 4: components
# --------------------------------------------------------------------------


def test_split_component_has_one_parent_two_children():
    previous = {"A": frozenset({"a1", "a2", "a3", "a4", "a5", "a6"})}
    current = {
        "B": frozenset({"a1", "a2", "a3"}),
        "C": frozenset({"a4", "a5", "a6"}),
    }
    components = build_lineage_components(
        build_lineage_edges(previous, current, CONFIG)
    )
    assert len(components) == 1
    assert components[0].is_split is True
    assert components[0].is_recombination is False


def test_recombination_is_not_forced_into_split_or_merge():
    """>=2 parents AND >=2 children must stay RECOMBINATION.

    Both parents contribute >= m_min alarms to both children, so all four cross
    edges form and the component genuinely recombines.
    """
    previous = {
        "A": frozenset({"a1", "a2", "a3", "a4", "a5", "a6"}),
        "B": frozenset({"b1", "b2", "b3", "b4", "b5", "b6"}),
    }
    current = {
        "X": frozenset({"a1", "a2", "a3", "b1", "b2", "b3"}),
        "Y": frozenset({"a4", "a5", "a6", "b4", "b5", "b6"}),
    }
    edges = build_lineage_edges(previous, current, CONFIG)
    # Each parent shares exactly 3 alarms with each child.
    assert len(edges) == 4
    components = build_lineage_components(edges)
    assert len(components) == 1
    component = components[0]
    assert component.is_recombination is True
    assert component.is_split is False
    assert component.is_merge is False


def test_weak_cross_links_do_not_create_recombination():
    """A single shared alarm is below m_min, so components stay separate."""
    previous = {
        "A": frozenset({"a1", "a2", "a3", "a4"}),
        "B": frozenset({"b1", "b2", "b3", "b4"}),
    }
    current = {
        "X": frozenset({"a1", "a2", "a3", "b1"}),
        "Y": frozenset({"b2", "b3", "b4", "a4"}),
    }
    components = build_lineage_components(
        build_lineage_edges(previous, current, CONFIG)
    )
    assert len(components) == 2
    assert all(c.is_one_to_one for c in components)


# --------------------------------------------------------------------------
# Step 5-6: events and decomposition
# --------------------------------------------------------------------------


def test_same_membership_new_chain_id_is_continue():
    """ADR-0020: 123 -> 984 with the same membership is CONTINUE."""
    previous = _package("s1", {"123": ["a1", "a2", "a3", "a4"]})
    current = _package("s2", {"984": ["a1", "a2", "a3", "a4"]})
    result = analyze_evolution(previous, current, config=CONFIG)

    assert result.event_of("984") is EvolutionEvent.CONTINUE
    chain = next(c for c in result.chains if c.snapshot_chain_id == "984")
    assert chain.previous_chain_ids == ("123",)
    assert chain.is_identifier_change_only is True
    assert chain.jaccard == pytest.approx(1.0)
    # A raw ID change is not a reassignment.
    assert len(result.retained) == 4
    assert result.reassigned == frozenset()


def test_turnover_is_visible_when_delta_size_is_zero():
    """+10 new and -10 cleared: delta 0 but turnover 20."""
    previous_members = [f"old{i}" for i in range(10)] + [f"keep{i}" for i in range(5)]
    current_members = [f"new{i}" for i in range(10)] + [f"keep{i}" for i in range(5)]
    previous = _package("s1", {"A": previous_members})
    current = _package("s2", {"A": current_members})

    result = analyze_evolution(previous, current, config=CONFIG)
    chain = next(c for c in result.chains if c.snapshot_chain_id == "A")
    decomposition = chain.decomposition
    assert decomposition is not None
    assert decomposition.delta_size == 0
    assert decomposition.turnover == 20
    assert decomposition.joined_new == 10
    assert decomposition.left_cleared == 10
    assert chain.event is EvolutionEvent.CONTINUE


def test_grow_and_shrink_are_distinguished():
    grow = analyze_evolution(
        _package("s1", {"A": ["a1", "a2", "a3", "a4"]}),
        _package("s2", {"A": ["a1", "a2", "a3", "a4", "a5"]}),
        config=CONFIG,
    )
    assert grow.event_of("A") is EvolutionEvent.GROW

    shrink = analyze_evolution(
        _package("s1", {"A": ["a1", "a2", "a3", "a4", "a5"]}),
        _package("s2", {"A": ["a1", "a2", "a3", "a4"]}),
        config=CONFIG,
    )
    assert shrink.event_of("A") is EvolutionEvent.SHRINK


def test_new_chain_has_no_lineage():
    result = analyze_evolution(
        _package("s1", {"A": ["a1", "a2", "a3"]}),
        _package(
            "s2", {"A": ["a1", "a2", "a3"], "B": ["b1", "b2", "b3", "b4"]}
        ),
        config=CONFIG,
    )
    assert result.event_of("B") is EvolutionEvent.NEW
    chain = next(c for c in result.chains if c.snapshot_chain_id == "B")
    assert chain.lineage_component_id is None
    assert chain.previous_chain_ids == ()


def test_dissolved_chain_is_reported():
    result = analyze_evolution(
        _package("s1", {"A": ["a1", "a2", "a3"], "B": ["b1", "b2", "b3"]}),
        _package("s2", {"A": ["a1", "a2", "a3"]}),
        config=CONFIG,
    )
    dissolved = [c for c in result.chains if c.event is EvolutionEvent.DISSOLVE]
    assert [c.snapshot_chain_id for c in dissolved] == ["B"]


def test_reassignment_is_decided_after_lineage():
    """An alarm moving between evolving chains is REASSIGNED, not cleared."""
    previous = _package(
        "s1", {"A": ["a1", "a2", "a3", "a4"], "B": ["b1", "b2", "b3", "b4"]}
    )
    current = _package(
        "s2", {"A": ["a1", "a2", "a3"], "B": ["b1", "b2", "b3", "b4", "a4"]}
    )
    result = analyze_evolution(previous, current, config=CONFIG)
    # a4 stayed active but changed evolving chain.
    assert "a4" in result.reassigned
    assert "a4" not in result.lifecycle.cleared_alarms

    chain_b = next(c for c in result.chains if c.snapshot_chain_id == "B")
    assert chain_b.decomposition.joined_reassigned == 1
    assert chain_b.decomposition.joined_new == 0


def test_decompose_counts_all_four_reasons():
    lifecycle = AlarmLifecycle(
        previous_snapshot_id="s1",
        current_snapshot_id="s2",
        new_alarms=frozenset({"n1"}),
        cleared_alarms=frozenset({"c1"}),
        active_both=frozenset({"keep", "moved_in", "moved_out"}),
    )
    decomposition = decompose(
        frozenset({"keep", "moved_out", "c1"}),
        frozenset({"keep", "moved_in", "n1"}),
        lifecycle,
        previous_owner={"moved_in": "OTHER"},
        current_owner={"moved_out": "OTHER"},
        chain_id="A",
    )
    assert decomposition.joined_new == 1
    assert decomposition.joined_reassigned == 1
    assert decomposition.left_cleared == 1
    assert decomposition.left_reassigned == 1
    assert decomposition.turnover == 4


# --------------------------------------------------------------------------
# Identifier scheme
# --------------------------------------------------------------------------


def test_three_identifiers_are_kept_separate():
    result = analyze_evolution(
        _package("s1", {"123": ["a1", "a2", "a3", "a4", "a5", "a6"]}),
        _package("s2", {"984": ["a1", "a2", "a3"], "985": ["a4", "a5", "a6"]}),
        config=CONFIG,
    )
    assignments = result.assignments
    assert assignments["984"].snapshot_chain_id == "984"
    assert assignments["984"].lineage_component_id is not None
    # Both branches share the lineage component but differ by branch.
    assert (
        assignments["984"].lineage_component_id
        == assignments["985"].lineage_component_id
    )
    assert assignments["984"].branch_id != assignments["985"].branch_id


def test_persistence_labels():
    assert membership_stability(0.95) is MembershipStability.STABLE
    assert membership_stability(0.5) is MembershipStability.BOUNDARY
    assert membership_stability(0.1) is MembershipStability.UNSTABLE


# --------------------------------------------------------------------------
# Against the mock's sequence fixture
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def split_merge_snapshots():
    base = MOCK_ROOT / "docs/examples/synthetic/evolution_split_merge"
    if not (base / "snapshot_000.json").is_file():
        pytest.skip("run 'nocpro-mock build-sequences' first")
    return [
        load_package(json.loads((base / f"snapshot_{i:03d}.json").read_text()))
        for i in range(3)
    ]


def test_mock_sequence_matches_expected_transitions(split_merge_snapshots):
    """The fixture declares SPLIT then MERGE; the engine must agree."""
    import yaml

    base = MOCK_ROOT / "docs/examples/synthetic/evolution_split_merge"
    manifest = yaml.safe_load((base / "sequence.yaml").read_text())
    expected = [t["expected_event"] for t in manifest["expected_transitions"]]

    observed: list[str] = []
    for index in range(len(split_merge_snapshots) - 1):
        result = analyze_evolution(
            split_merge_snapshots[index],
            split_merge_snapshots[index + 1],
            config=CONFIG,
        )
        events = {c.event.value for c in result.chains}
        observed.append("SPLIT" if "SPLIT" in events else "MERGE" if "MERGE" in events else "?")

    assert observed == expected


def test_mock_sequence_lineage_follows_membership(split_merge_snapshots):
    """Chain IDs differ at every step, so lineage must come from membership."""
    result = analyze_evolution(
        split_merge_snapshots[0], split_merge_snapshots[1], config=CONFIG
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.parents == ("SYN-CHAIN-A",)
    assert component.children == ("SYN-CHAIN-B", "SYN-CHAIN-C")
    # No alarm cleared or appeared: this is pure regrouping.
    assert result.lifecycle.new_alarms == frozenset()
    assert result.lifecycle.cleared_alarms == frozenset()

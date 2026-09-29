"""Indexed statistics must match the pairwise correctness oracle."""

from __future__ import annotations

import pytest
import random

from channels import AlarmTaxonomy, EvidenceState, evaluate_chain_channels
from channels.indexed_statistics import build_indexed_statistics
from groups import (
    RoleThresholds,
    SupportIndexSemantics,
    classify_membership,
    membership_support,
)
from groups.fit_from_index import membership_support_from_index
from libs.contracts import load_package


def _package(rows: list[dict]):
    alarms = []
    memberships = []
    for row in rows:
        alarm_id = row.pop("alarm_id")
        raw = {key: str(value) for key, value in row.items() if value is not None}
        alarms.append(
            {
                "alarm_id": alarm_id,
                "snapshot_id": "s1",
                "raw": raw,
                "alarm_name": row.get("alarm_name"),
                "device_code": row.get("device_code"),
                "node_reference": row.get("node_reference"),
                "canonical_start_time": row.get("canonical_start_time"),
            }
        )
        memberships.append(
            {"chain_id": "C1", "alarm_id": alarm_id, "snapshot_id": "s1"}
        )
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "test",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-01-01T00:00:00",
            },
            "alarms": alarms,
            "chains": [
                {"chain_id": "C1", "snapshot_id": "s1", "member_count": len(rows)}
            ],
            "memberships": memberships,
        }
    )


@pytest.fixture()
def mixed_package():
    return _package(
        [
            {
                "alarm_id": "a1",
                "alarm_name": "LINK DOWN",
                "device_code": "D1",
                "node_reference": "R1",
                "location_code": "SITE-A",
                "canonical_start_time": "2026-01-01T00:00:00",
            },
            {
                "alarm_id": "a2",
                "alarm_name": "LINK DOWN",
                "device_code": "D1",
                "node_reference": "R1",
                "location_code": "SITE-A",
                "canonical_start_time": "2026-01-01T00:00:10",
            },
            {
                "alarm_id": "a3",
                "alarm_name": "POWER FAIL",
                "device_code": "D2",
                "node_reference": "R2",
                "location_code": "SITE-A",
                "canonical_start_time": "2026-01-01T00:05:00",
            },
            {
                "alarm_id": "a4",
                "alarm_name": None,
                "device_code": None,
                "node_reference": None,
                "location_code": None,
                "canonical_start_time": None,
            },
        ]
    )


def _assert_equivalent(package, *, taxonomy=AlarmTaxonomy({}, {}), d_max=3):
    oracle = evaluate_chain_channels(package, "C1", taxonomy=taxonomy, d_max=d_max)
    indexed = build_indexed_statistics(package, "C1", taxonomy=taxonomy, d_max=d_max)

    assert (
        indexed.support_index_semantics
        is SupportIndexSemantics.SYMMETRIC_UNORDERED_PAIRS_V1
    )

    assert set(indexed.channel_ids) == set(oracle.statistics.channel_ids())
    oracle_supports = {}
    indexed_supports = {}
    positions = {alarm_id: index for index, alarm_id in enumerate(oracle.members)}
    for alarm_id in oracle.members:
        for channel_id in oracle.statistics.channel_ids():
            expected = oracle.statistics.counts_for(alarm_id, channel_id)
            actual = indexed.fit_of(alarm_id, channel_id)
            assert actual is not None
            assert actual.domain_size == expected.domain_size
            assert actual.supporting == expected.supporting
            if expected.fit is None:
                assert actual.fit is None
            else:
                assert actual.fit == pytest.approx(expected.fit)

            expected_bitmap = 0
            for (left, right), values in oracle.matrix.values.items():
                if alarm_id not in {left, right}:
                    continue
                value = next(item for item in values if item.channel_id == channel_id)
                if value.supports:
                    peer_id = right if left == alarm_id else left
                    expected_bitmap |= 1 << positions[peer_id]
            assert indexed.support_bitmap_of(alarm_id, channel_id) == expected_bitmap

        expected_support = membership_support(alarm_id, oracle.statistics)
        actual_support = membership_support_from_index(alarm_id, indexed)
        oracle_supports[alarm_id] = expected_support
        indexed_supports[alarm_id] = actual_support
        assert actual_support.support == pytest.approx(expected_support.support)
        expected_groups = {group.derivation_tag: group for group in expected_support.group_fits}
        actual_groups = {group.derivation_tag: group for group in actual_support.group_fits}
        assert set(actual_groups) == set(expected_groups)
        for tag, expected_group in expected_groups.items():
            if expected_group.fit is None:
                assert actual_groups[tag].fit is None
            else:
                assert actual_groups[tag].fit == pytest.approx(expected_group.fit)

    def quantiles(supports):
        ranked = sorted(
            supports.items(), key=lambda item: (-(item[1].support or -1.0), item[0])
        )
        return {
            alarm_id: position / (len(ranked) - 1) if len(ranked) > 1 else 0.0
            for position, (alarm_id, _) in enumerate(ranked)
        }

    oracle_quantiles = quantiles(oracle_supports)
    indexed_quantiles = quantiles(indexed_supports)
    thresholds = RoleThresholds(config_version="equivalence-v1")
    for alarm_id in oracle.members:
        expected_role = classify_membership(
            oracle_supports[alarm_id],
            thresholds=thresholds,
            chain_size=len(oracle.members),
            support_rank_quantile=oracle_quantiles[alarm_id],
        )
        actual_role = classify_membership(
            indexed_supports[alarm_id],
            thresholds=thresholds,
            chain_size=len(oracle.members),
            support_rank_quantile=indexed_quantiles[alarm_id],
        )
        assert actual_role.verdict is expected_role.verdict
        assert actual_role.gate == expected_role.gate


def test_indexed_matches_pairwise_with_mixed_availability(mixed_package):
    _assert_equivalent(mixed_package)


def test_placeholder_entity_values_do_not_create_fit_support():
    package = _package(
        [
            {
                "alarm_id": "a1",
                "device_code": "N/A",
                "location_code": "[]",
            },
            {
                "alarm_id": "a2",
                "device_code": "N/A",
                "location_code": "[]",
            },
        ]
    )

    oracle = evaluate_chain_channels(package, "C1")
    pair = next(iter(oracle.matrix.values.values()))
    pair_by_channel = {value.channel_id: value for value in pair}
    assert pair_by_channel["E_site"].state is EvidenceState.UNAVAILABLE
    assert pair_by_channel["E_device"].state is EvidenceState.UNAVAILABLE
    assert pair_by_channel["T_burst"].state is EvidenceState.UNAVAILABLE
    assert membership_support("a1", oracle.statistics).support is None

    indexed = build_indexed_statistics(package, "C1")
    assert indexed.fit_of("a1", "E_site").fit is None
    assert indexed.fit_of("a1", "E_device").fit is None
    assert membership_support_from_index("a1", indexed).support is None


def test_missing_member_does_not_use_total_peer_denominator(mixed_package):
    oracle = evaluate_chain_channels(mixed_package, "C1")
    indexed = build_indexed_statistics(mixed_package, "C1")
    expected = oracle.statistics.counts_for("a1", "E_reference")
    actual = indexed.fit_of("a1", "E_reference")
    assert expected.domain_size == 2
    assert actual is not None and actual.domain_size == 2
    assert actual.supporting == 1


def test_indexed_semantic_family_matches_pairwise_taxonomy():
    package = _package(
        [
            {"alarm_id": "a1", "alarm_name": "LINK DOWN", "device_code": "D1"},
            {"alarm_id": "a2", "alarm_name": "LINK FLAP", "device_code": "D2"},
            {"alarm_id": "a3", "alarm_name": "POWER FAIL", "device_code": "D3"},
        ]
    )
    taxonomy = AlarmTaxonomy(
        families={"LINK DOWN": "LINK", "LINK FLAP": "LINK", "POWER FAIL": "POWER"},
        categories={},
    )
    _assert_equivalent(package, taxonomy=taxonomy)


def test_singleton_indexed_domains_are_unavailable():
    package = _package(
        [{"alarm_id": "only", "alarm_name": "LINK DOWN", "device_code": "D1"}]
    )
    indexed = build_indexed_statistics(package, "C1")
    assert indexed.channel_ids
    for channel_id in indexed.channel_ids:
        fit = indexed.fit_of("only", channel_id)
        assert fit is not None
        assert fit.domain_size == 0
        assert fit.fit is None


def test_deterministic_randomized_indexed_oracle_equivalence():
    rng = random.Random(20260828)
    names = ["LINK DOWN", "LINK FLAP", "POWER FAIL", None]
    rows = []
    for index in range(30):
        rows.append(
            {
                "alarm_id": f"r{index}",
                "alarm_name": rng.choice(names),
                "device_code": rng.choice(["D1", "D2", "D3", None]),
                "node_reference": rng.choice(["R1", "R2", None]),
                "location_code": rng.choice(["S1", "S2", None]),
                "component": rng.choice(["C1", "C2", None]),
                "canonical_start_time": (
                    f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}"
                    if rng.random() > 0.15
                    else None
                ),
            }
        )
    taxonomy = AlarmTaxonomy(
        families={"LINK DOWN": "LINK", "LINK FLAP": "LINK", "POWER FAIL": "POWER"},
        categories={},
    )
    _assert_equivalent(_package(rows), taxonomy=taxonomy)


def test_indexed_dep_hop_matches_pairwise_with_mapping_and_sparse_topology():
    package = _package(
        [
            {"alarm_id": "a1", "alarm_name": "DOWN", "device_code": "D1"},
            {"alarm_id": "a2", "alarm_name": "DOWN", "device_code": "D2"},
            {"alarm_id": "a3", "alarm_name": "POWER", "device_code": "D3"},
            {"alarm_id": "a4", "alarm_name": "POWER", "device_code": "D4"},
        ]
    )
    package.topology = {
        "edges": [
            {
                "edge_id": "e12",
                "source_resource_id": "R1",
                "target_resource_id": "R2",
                    "relation_type": "IP_ADJACENCY",
                    "directed": False,
                    "source_id": "inventory",
                    "source_version": "topology-v1",
                },
            {
                "edge_id": "e34",
                "source_resource_id": "R3",
                "target_resource_id": "R4",
                    "relation_type": "IP_ADJACENCY",
                    "directed": False,
                    "source_id": "inventory",
                    "source_version": "topology-v1",
                },
        ],
        "mappings": [
            {"alarm_id": "a1", "resource_id": "R1", "mapping_status": "EXACT"},
            {"alarm_id": "a2", "resource_id": "R2", "mapping_status": "EXACT"},
            {"alarm_id": "a3", "resource_id": "R3", "mapping_status": "EXACT"},
            {"alarm_id": "a4", "resource_id": None, "mapping_status": "UNMAPPED"},
        ],
    }

    _assert_equivalent(package)

    indexed = build_indexed_statistics(package, "C1")
    a1 = indexed.fit_of("a1", "Dep_hop")
    a3 = indexed.fit_of("a3", "Dep_hop")
    a4 = indexed.fit_of("a4", "Dep_hop")
    assert a1 is not None and (a1.domain_size, a1.supporting, a1.fit) == (1, 1, 1.0)
    assert a3 is not None and a3.fit is None
    assert a4 is not None and a4.fit is None

    _assert_equivalent(package, d_max=0)
    dmax_zero = build_indexed_statistics(package, "C1", d_max=0)
    assert dmax_zero.fit_of("a1", "Dep_hop").fit is None

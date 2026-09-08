from __future__ import annotations

from datetime import datetime, timezone
import pytest

from channels import evaluate_chain_indexed
from groups.indexed_statistics import NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH
from libs.contracts import (
    IngestedAlarm,
    IngestedChain,
    IngestedPackage,
    IngestedSnapshot,
)


def _make_package(alarms_data: list[tuple[str, str]]) -> IngestedPackage:
    snapshot = IngestedSnapshot(
        snapshot_id="S1",
        snapshot_version="snapshot-v1",
        snapshot_time="2026-08-30T00:00:00Z",
        status="COMPLETE",
        source="synthetic-fixture",
        source_kind="SYNTHETIC_TEST",
        produced_at="2026-08-30T00:00:00Z",
        topology_version="topology-v1",
    )
    alarms = {
        alarm_id: IngestedAlarm(
            alarm_id=alarm_id,
            snapshot_id="S1",
            raw={"canonical_start_time": start_time},
            canonical_start_time=start_time,
        )
        for alarm_id, start_time in alarms_data
    }
    member_ids = [alarm_id for alarm_id, _ in alarms_data]
    return IngestedPackage(
        snapshot=snapshot,
        alarms=alarms,
        chains={"C1": IngestedChain("C1", "S1", len(member_ids))},
        memberships={"C1": member_ids},
        topology={"edges": [], "mappings": []},
    )


def test_small_chain_delay_sliding_window():
    """For N <= 200, sliding window / O(N^2) evaluates temporal delay support."""
    alarms_data = [
        ("a0", "2026-08-30T00:00:00Z"),
        ("a1", "2026-08-30T00:02:00Z"),  # 120s from a0
        ("a2", "2026-08-30T00:05:00Z"),  # 300s from a0
        ("a3", "2026-08-30T01:00:00Z"),  # 3600s from a0 (out of window)
    ]
    pkg = _make_package(alarms_data)

    # 10 minutes window = 600s
    evidence = evaluate_chain_indexed(pkg, "C1", delay_window_seconds=600.0)
    stats = evidence.statistics

    # a0 should be supported by a1 and a2 (2 peers out of 3 domain peers)
    fit_a0 = stats.fit_of("a0", "T_delay")
    assert fit_a0.unavailable_reason is None
    assert fit_a0.domain_size == 3
    assert fit_a0.supporting == 2
    assert fit_a0.fit == pytest.approx(2 / 3)

    # a3 should be supported by 0 peers
    fit_a3 = stats.fit_of("a3", "T_delay")
    assert fit_a3.unavailable_reason is None
    assert fit_a3.domain_size == 3
    assert fit_a3.supporting == 0
    assert fit_a3.fit == pytest.approx(0.0)


def test_large_chain_delay_sliding_window():
    """For N > 200, sorted bisect sliding window runs in O(N log N) efficiently."""
    # 250 alarms, 2 seconds apart
    alarms_data = [
        (f"alarm_{i:03d}", f"2026-08-30T00:{i // 60:02d}:{i % 60:02d}Z")
        for i in range(250)
    ]
    pkg = _make_package(alarms_data)

    # 30 seconds window
    evidence = evaluate_chain_indexed(pkg, "C1", delay_window_seconds=30.0)
    stats = evidence.statistics

    fit_mid = stats.fit_of("alarm_100", "T_delay")
    assert fit_mid.unavailable_reason is None
    assert fit_mid.domain_size == 249
    # Within 30s before and after: alarms 85 to 115 (about 30 alarms excluding self)
    assert fit_mid.supporting > 0
    assert fit_mid.fit > 0.0


def test_delay_default_keeps_fail_closed_compatibility():
    """When delay_window_seconds is None, backward compatibility is preserved."""
    alarms_data = [
        ("a0", "2026-08-30T00:00:00Z"),
        ("a1", "2026-08-30T00:02:00Z"),
    ]
    pkg = _make_package(alarms_data)

    evidence = evaluate_chain_indexed(pkg, "C1")
    stats = evidence.statistics

    fit_a0 = stats.fit_of("a0", "T_delay")
    assert fit_a0.fit is None
    assert fit_a0.unavailable_reason == NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH


def test_exact_delay_no_100_peer_cap_for_n_under_200():
    """For N <= 200, all valid peers are checked without an artificial 100-peer cap."""
    # 150 alarms with identical timestamps
    alarms_data = [
        (f"alarm_{i:03d}", "2026-08-30T00:00:00Z")
        for i in range(150)
    ]
    pkg = _make_package(alarms_data)

    evidence = evaluate_chain_indexed(pkg, "C1", delay_window_seconds=10.0)
    stats = evidence.statistics

    fit_0 = stats.fit_of("alarm_000", "T_delay")
    assert fit_0.unavailable_reason is None
    assert fit_0.domain_size == 149
    # Exactly 149 peers must support, NOT capped at 100
    assert fit_0.supporting == 149
    assert fit_0.fit == pytest.approx(1.0)


def test_delay_sliding_window_boundary_200_vs_201():
    """Verify continuity across the N=200 (pairwise) and N=201 (bisect) algorithm boundary."""
    # Test N=200:
    alarms_200 = [
        (f"alarm_{i:03d}", f"2026-08-30T00:{i // 60:02d}:{i % 60:02d}Z")
        for i in range(200)
    ]
    pkg_200 = _make_package(alarms_200)
    ev_200 = evaluate_chain_indexed(pkg_200, "C1", delay_window_seconds=10.0)
    stats_200 = ev_200.statistics
    fit_200_mid = stats_200.fit_of("alarm_100", "T_delay")
    bm_200_mid = stats_200.support_peer_bitmaps.get(("alarm_100", "T_delay"), 0)
    assert fit_200_mid.unavailable_reason is None
    assert fit_200_mid.domain_size == 199
    # Within 10s before and after: alarms 90 to 110 (20 peers, excluding self)
    assert fit_200_mid.supporting == 20
    assert bin(bm_200_mid).count("1") == 20

    # Test N=201:
    alarms_201 = [
        (f"alarm_{i:03d}", f"2026-08-30T00:{i // 60:02d}:{i % 60:02d}Z")
        for i in range(201)
    ]
    pkg_201 = _make_package(alarms_201)
    ev_201 = evaluate_chain_indexed(pkg_201, "C1", delay_window_seconds=10.0)
    stats_201 = ev_201.statistics
    fit_201_mid = stats_201.fit_of("alarm_100", "T_delay")
    bm_201_mid = stats_201.support_peer_bitmaps.get(("alarm_100", "T_delay"), 0)
    assert fit_201_mid.unavailable_reason is None
    assert fit_201_mid.domain_size == 200
    assert fit_201_mid.supporting == 20
    assert bin(bm_201_mid).count("1") == 20


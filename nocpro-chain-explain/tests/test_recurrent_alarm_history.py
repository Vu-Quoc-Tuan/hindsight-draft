from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from libs.contracts import IngestedAlarm, IngestedChain, IngestedPackage, IngestedSnapshot
from nocpro_api.recurrent_alarm_history import chain_recurrence_history
from recurrent_alarms import AlarmOccurrence, count_alarm_recurrences


def test_count_alarm_recurrences_deduplicates_copies_and_excludes_conflicts() -> None:
    as_of = datetime(2026, 9, 25, tzinfo=timezone.utc)
    event_time = as_of - timedelta(hours=2)
    result = count_alarm_recurrences(
        [
            AlarmOccurrence("src", "a1", "D1", "F1", event_time, "s1", "v1"),
            AlarmOccurrence("src", "a1", "D1", "F1", event_time, "s2", "v2"),
            AlarmOccurrence("src", "a-conflict", "D2", "F2", event_time),
            AlarmOccurrence("src", "a-conflict", "D3", "F2", event_time),
            AlarmOccurrence("src", "a-future", "D4", "F4", as_of + timedelta(seconds=1)),
            AlarmOccurrence("src", "a-naive", "D5", "F5", datetime(2026, 9, 25)),
        ],
        as_of=as_of,
    )

    assert [(group.device_code, group.fault_id, group.count) for group in result.groups] == [
        ("D1", "F1", 1),
    ]
    assert result.groups[0].occurrences[0].snapshots == (("s1", "v1"), ("s2", "v2"))
    assert result.duplicate_observations == 2
    assert result.conflicting_event_keys == 1
    assert result.skipped_observations == 1


def test_chain_recurrence_history_is_active_snapshot_scoped_without_repository() -> None:
    snapshot = IngestedSnapshot(
        snapshot_id="demo_ip_network",
        snapshot_version="v1",
        snapshot_time="2026-09-20T00:00:00Z",
        status="COMPLETE",
        source="source-a",
        source_kind="CSV",
        produced_at="2026-09-20T00:00:00Z",
    )
    alarms = {
        "a-chain": IngestedAlarm(
            "a-chain", snapshot.snapshot_id, {"fault_id": "F1"},
            device_code="D1", canonical_start_time="2026-09-20T00:00:00",
        ),
        "a-same-pair": IngestedAlarm(
            "a-same-pair", snapshot.snapshot_id, {"fault_id": "F1"},
            device_code="D1", canonical_start_time="2026-09-21T00:00:00Z",
        ),
        "a-other-pair": IngestedAlarm(
            "a-other-pair", snapshot.snapshot_id, {"fault_id": "F2"},
            device_code="D2", canonical_start_time="2026-09-22T00:00:00Z",
        ),
        "a-outlier": IngestedAlarm(
            "a-outlier", snapshot.snapshot_id, {"fault_id": "F1"},
            device_code="D1", canonical_start_time="2026-09-23T00:00:00",
            quality_flags=("TIMESTAMP_FUTURE_OUTLIER",),
        ),
        "a-unmatched": IngestedAlarm(
            "a-unmatched", snapshot.snapshot_id, {},
            device_code="D1", canonical_start_time="2026-09-24T00:00:00Z",
        ),
    }
    package = IngestedPackage(
        snapshot=snapshot,
        alarms=alarms,
        chains={"C1": IngestedChain("C1", snapshot.snapshot_id, 2)},
        memberships={"C1": ["a-chain", "a-unmatched"]},
    )

    result = asyncio.run(chain_recurrence_history(package, chain_id="C1", repository=None))

    assert result["history_scope"] == "ACTIVE_SNAPSHOT_ONLY"
    assert result["profile_id"] == "IP_NETWORK"
    assert result["snapshot_count"] == 1
    assert result["assumed_utc_count"] == 1
    assert result["unmatched_chain_alarm_count"] == 1
    assert result["skipped_observations"] == 1
    assert [(group["device_code"], group["fault_id"], group["count"]) for group in result["groups"]] == [
        ("D1", "F1", 2),
    ]


def test_chain_recurrence_history_rejects_unknown_chain() -> None:
    package = SimpleNamespace(chains={}, snapshot=None)
    with pytest.raises(KeyError, match="Unknown chain_id"):
        asyncio.run(chain_recurrence_history(package, chain_id="missing", repository=None))

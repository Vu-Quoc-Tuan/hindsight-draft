"""Tier-1A precompute and Tier-1 cache tests (§3, ADR-0005/0014/0020/0025).

Pinned invariants:
  - Tier-1A never runs on an incomplete snapshot
  - the cache key is (fingerprint, snapshot, config version)
  - a changed raw chain ID with identical membership reuses the cache
  - a changed config version does not reuse it
  - Tier-1B does not require a Tier-2 entry
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from descriptor import MiningConfig
from libs.contracts import load_package
from tier1a import (
    CacheTier,
    IncompleteSnapshotError,
    Tier1Cache,
    chain_fingerprint,
    precompute_snapshot,
)
from tests.conftest import MOCK_ROOT

MINING = MiningConfig(config_version="t1a-v1")


def _package(snapshot_id: str, chains: dict[str, list[str]], *, status: str = "COMPLETE"):
    alarms = []
    memberships = []
    seen: set[str] = set()
    for chain_id, members in chains.items():
        for alarm_id in members:
            if alarm_id not in seen:
                alarms.append(
                    {
                        "alarm_id": alarm_id,
                        "snapshot_id": snapshot_id,
                        "raw": {"device_code": chain_id},
                        "device_code": chain_id,
                        "alarm_name": "LINK DOWN",
                    }
                )
                seen.add(alarm_id)
            memberships.append(
                {"chain_id": chain_id, "alarm_id": alarm_id, "snapshot_id": snapshot_id}
            )
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": snapshot_id,
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": status,
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
# Snapshot completeness
# --------------------------------------------------------------------------


def test_tier1a_refuses_an_incomplete_snapshot():
    """ADR-0005: Tier-1A never runs on an incomplete snapshot."""
    package = _package("s1", {"A": ["a1", "a2"]}, status="INCOMPLETE")
    with pytest.raises(IncompleteSnapshotError, match="requires COMPLETE"):
        precompute_snapshot(package, mining_config=MINING)


def test_tier1a_runs_on_a_complete_snapshot():
    package = _package("s1", {"A": ["a1", "a2", "a3"]})
    result = precompute_snapshot(package, mining_config=MINING)
    assert result.chain_count == 1
    assert result.alarm_count == 3


# --------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------


def test_fingerprint_ignores_member_ordering():
    assert chain_fingerprint({"a", "b", "c"}) == chain_fingerprint({"c", "b", "a"})


def test_fingerprint_changes_with_membership():
    assert chain_fingerprint({"a", "b"}) != chain_fingerprint({"a", "b", "c"})


# --------------------------------------------------------------------------
# Cache key composition
# --------------------------------------------------------------------------


def test_same_membership_new_chain_id_reuses_the_cache():
    """ADR-0020: identity churn is not new work."""
    cache = Tier1Cache()
    members = {"a1", "a2", "a3"}
    first = cache.key_for(
        CacheTier.TIER_1A,
        member_ids=members,
        snapshot_id="s1", snapshot_version="1",
        config_version="v1",
    )
    cache.put(first, "computed", snapshot_chain_id="123")

    # Same membership and snapshot, different raw chain ID.
    second = cache.key_for(
        CacheTier.TIER_1A,
        member_ids=members,
        snapshot_id="s1", snapshot_version="1",
        config_version="v1",
    )
    assert cache.get(second) == "computed"
    assert cache.hits == 1


def test_config_version_change_invalidates():
    """ADR-0025: a threshold change must not silently reuse an explanation."""
    cache = Tier1Cache()
    members = {"a1", "a2"}
    cache.put(
        cache.key_for(
            CacheTier.TIER_1A,
            member_ids=members,
            snapshot_id="s1", snapshot_version="1",
            config_version="v17",
        ),
        "old",
    )
    miss = cache.key_for(
        CacheTier.TIER_1A,
        member_ids=members,
        snapshot_id="s1", snapshot_version="1",
        config_version="v18",
    )
    assert cache.get(miss) is None


def test_snapshot_change_invalidates():
    cache = Tier1Cache()
    members = {"a1", "a2"}
    cache.put(
        cache.key_for(
            CacheTier.TIER_1A, member_ids=members, snapshot_id="s1", snapshot_version="1", config_version="v1"
        ),
        "old",
    )
    other = cache.key_for(
        CacheTier.TIER_1A, member_ids=members, snapshot_id="s2", snapshot_version="1", config_version="v1"
    )
    assert cache.get(other) is None


def test_membership_change_invalidates():
    cache = Tier1Cache()
    cache.put(
        cache.key_for(
            CacheTier.TIER_1A,
            member_ids={"a1", "a2"},
            snapshot_id="s1", snapshot_version="1",
            config_version="v1",
        ),
        "old",
    )
    grown = cache.key_for(
        CacheTier.TIER_1A,
        member_ids={"a1", "a2", "a3"},
        snapshot_id="s1", snapshot_version="1",
        config_version="v1",
    )
    assert cache.get(grown) is None


def test_tiers_are_separate_keys():
    """Tier-1B must not require a Tier-2 entry (ADR-0014)."""
    cache = Tier1Cache()
    members = {"a1", "a2"}
    tier1b = cache.key_for(
        CacheTier.TIER_1B, member_ids=members, snapshot_id="s1", snapshot_version="1", config_version="v1"
    )
    tier2 = cache.key_for(
        CacheTier.TIER_2, member_ids=members, snapshot_id="s1", snapshot_version="1", config_version="v1"
    )
    cache.put(tier1b, "local analysis")

    assert cache.get(tier1b) == "local analysis"
    # Tier-2 absent, yet Tier-1B is fully usable.
    assert cache.has(tier2) is False


def test_has_does_not_count_as_a_hit():
    cache = Tier1Cache()
    key = cache.key_for(
        CacheTier.TIER_1A, member_ids={"a1"}, snapshot_id="s1", snapshot_version="1", config_version="v1"
    )
    cache.has(key)
    assert cache.hits == 0
    assert cache.misses == 0


def test_invalidate_by_config_version():
    cache = Tier1Cache()
    for version in ("v1", "v1", "v2"):
        cache.put(
            cache.key_for(
                CacheTier.TIER_1A,
                member_ids={f"a{version}{len(cache)}"},
                snapshot_id="s1", snapshot_version="1",
                config_version=version,
            ),
            version,
        )
    removed = cache.invalidate_config("v1")
    assert removed == 2
    assert len(cache) == 1


# --------------------------------------------------------------------------
# Precompute content
# --------------------------------------------------------------------------


def test_precompute_warms_the_cache():
    package = _package("s1", {"A": ["a1", "a2", "a3"], "B": ["b1"]})
    cache = Tier1Cache()
    precompute_snapshot(package, mining_config=MINING, cache=cache)
    assert len(cache) == 2
    assert len(cache.tier_entries(CacheTier.TIER_1A)) == 2


def test_precompute_counts_singletons():
    """Singletons are the common case and must be summarized, not skipped."""
    package = _package("s1", {"A": ["a1", "a2"], "B": ["b1"], "C": ["c1"]})
    result = precompute_snapshot(package, mining_config=MINING)
    assert result.singleton_count == 2
    assert result.chains["B"].is_singleton is True
    # A singleton still gets a title.
    assert result.chains["B"].auto_title


def test_precompute_produces_identity_only():
    """CONTRASTIVE needs U_local, which is Tier-1B work."""
    package = _package("s1", {"A": ["a1", "a2", "a3"]})
    result = precompute_snapshot(package, mining_config=MINING)
    descriptors = result.descriptors_of("A")
    assert descriptors is not None
    assert descriptors.contrastive == ()


def test_precompute_respects_max_chains():
    package = _package(
        "s1", {"A": ["a1"], "B": ["b1"], "C": ["c1"], "D": ["d1"]}
    )
    result = precompute_snapshot(package, mining_config=MINING, max_chains=2)
    assert result.chain_count == 2


# --------------------------------------------------------------------------
# Real data
# --------------------------------------------------------------------------


@pytest.mark.realdata
def test_precompute_on_real_snapshot():
    if not (MOCK_ROOT / "datasets/raw/alarm/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")
    venv = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv) if venv.is_file() else sys.executable
    result = subprocess.run(
        [
            interpreter, "-m", "nocpro_mock.cli", "replay",
            "--limit", "800", "--snapshot-id", "s_real_1a",
        ],
        cwd=MOCK_ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI failed: {result.stderr[:300]}")

    package = load_package(json.loads(result.stdout))
    cache = Tier1Cache()
    precompute = precompute_snapshot(package, mining_config=MINING, cache=cache)

    assert precompute.chain_count == len(package.chains)
    assert len(cache) == precompute.chain_count
    # The real export is singleton-heavy; that path must be exercised.
    assert precompute.singleton_count > 0

    largest = max(precompute.chains.values(), key=lambda c: c.member_count)
    assert largest.descriptors.identity
    assert largest.auto_title

    # Re-running with the same key hits the cache instead of recomputing.
    members = set(package.members_of(largest.chain_id))
    key = cache.key_for(
        CacheTier.TIER_1A,
        member_ids=members,
        snapshot_id=package.snapshot.snapshot_id,
        snapshot_version=package.snapshot.snapshot_version,
        config_version=MINING.config_version,
    )
    assert cache.get(key) is not None

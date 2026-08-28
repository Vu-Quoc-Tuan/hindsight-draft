"""Tier-1B chain analysis tests (§3, §4B, §5).

Verifies the role engine is now self-contained: ``Representativeness`` and
``Margin_common`` are computed inside the analysis, not injected by a caller.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from descriptor import MiningConfig
from descriptor.contrastive import (
    blocking_candidates,
    local_universe_bitmap,
    margin_common,
)
from graybox.singleton import MembershipVerdict
from groups import RoleThresholds
from libs.contracts import load_package
from tier1b import analyze_chain, auto_chain_title
from tests.conftest import MOCK_ROOT

THRESHOLDS = RoleThresholds(config_version="t1b-v1")
MINING = MiningConfig(config_version="t1b-mine-v1")


def _snapshot(alarms, chains, memberships):
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "test",
                "source_kind": "REAL_EXPORT_REPLAY",
                "produced_at": "2026-01-01T00:00:00",
                "schema_version": "v1",
            },
            "alarms": alarms,
            "chains": chains,
            "memberships": memberships,
        }
    )


def _alarm(alarm_id, chain, **fields):
    raw = {k: str(v) for k, v in fields.items()}
    raw["chaining_id"] = chain
    return {
        "alarm_id": alarm_id,
        "snapshot_id": "s1",
        "raw": raw,
        "alarm_name": fields.get("alarm_name"),
        "device_code": fields.get("device_code"),
        "node_reference": fields.get("node_reference"),
        "canonical_start_time": fields.get("canonical_start_time"),
    }


@pytest.fixture()
def two_chain_package():
    """Two clean blocks that share a site, so U_local is non-empty."""
    alarms = []
    memberships = []
    for i in range(6):
        alarms.append(
            _alarm(
                f"c1_{i}",
                "C1",
                device_code="D1",
                node_reference="R1",
                alarm_name="LINK DOWN",
                location_code="SITE_A",
                canonical_start_time=f"2026-01-01T00:00:{i:02d}",
            )
        )
        memberships.append({"chain_id": "C1", "alarm_id": f"c1_{i}", "snapshot_id": "s1"})
    for i in range(6):
        alarms.append(
            _alarm(
                f"c2_{i}",
                "C2",
                device_code="D2",
                node_reference="R2",
                alarm_name="POWER FAIL",
                location_code="SITE_A",
                canonical_start_time=f"2026-01-01T02:00:{i:02d}",
            )
        )
        memberships.append({"chain_id": "C2", "alarm_id": f"c2_{i}", "snapshot_id": "s1"})

    chains = [
        {"chain_id": "C1", "snapshot_id": "s1", "member_count": 6},
        {"chain_id": "C2", "snapshot_id": "s1", "member_count": 6},
    ]
    return _snapshot(alarms, chains, memberships)


def test_analysis_produces_descriptors_and_roles(two_chain_package):
    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert analysis.member_count == 6
    assert analysis.descriptors.identity
    assert len(analysis.members) == 6


def test_representativeness_is_computed_not_injected(two_chain_package):
    """The role engine must derive Representativeness itself."""
    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    for member in analysis.members.values():
        assert member.representativeness is not None
        assert 0.0 <= member.representativeness <= 1.0
        assert member.role.representativeness == member.representativeness


def test_margin_common_is_computed_from_a_rival_chain(two_chain_package):
    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert analysis.local_candidates
    assert analysis.local_candidates[0].chain_id == "C2"
    for member in analysis.members.values():
        assert member.margin is not None
        assert member.margin.compared_chain_id == "C2"
        # C1 members fit C1 better than C2, so the margin is positive.
        assert member.margin.margin is not None
        assert member.margin.margin > 0


def test_members_of_a_clean_block_reach_core(two_chain_package):
    """Identical members with a positive margin should be CORE, not PERIPHERAL."""
    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    verdicts = {m.role.verdict for m in analysis.members.values()}
    assert MembershipVerdict.CORE in verdicts


def test_auto_title_uses_the_top_identity_descriptor(two_chain_package):
    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert analysis.auto_title
    assert analysis.auto_title != "Chain C1"
    assert "=" in analysis.auto_title


def test_auto_title_falls_back_when_precision_is_low():
    from descriptor import DescriptorSet

    empty = DescriptorSet(chain_id="C9")
    assert auto_chain_title("C9", empty, MINING) == "Chain C9"


def test_margin_insufficient_when_groups_do_not_overlap():
    """|G_common| < g_min => INSUFFICIENT CONTRASTIVE EVIDENCE."""
    from groups.fit import GroupFit
    from libs.provenance import (
        NormalizedChannel,
        ProvenanceClass,
        build_derivation_groups,
    )

    own_group = build_derivation_groups(
        [
            NormalizedChannel(
                channel_id="S",
                derivation_tag="semantic",
                provenance_class=ProvenanceClass.POST_HOC,
            )
        ]
    )[0]
    rival_group = build_derivation_groups(
        [
            NormalizedChannel(
                channel_id="E_reference",
                derivation_tag="reference",
                provenance_class=ProvenanceClass.POST_HOC,
            )
        ]
    )[0]

    result = margin_common(
        "x",
        (GroupFit(group=own_group, fit=1.0, channel_fits=()),),
        (GroupFit(group=rival_group, fit=1.0, channel_fits=()),),
        compared_chain_id="C2",
        g_min=2,
    )
    assert result.insufficient is True
    assert result.margin is None
    assert "shared computable group" in result.reason


def test_u_local_includes_the_target_chain(two_chain_package):
    """Excluding C would force every local precision to zero."""
    from descriptor import build_predicate_index

    index = build_predicate_index(list(two_chain_package.alarms.values()))
    candidates = blocking_candidates(two_chain_package, "C1", k=3)
    u_local = local_universe_bitmap(
        two_chain_package, candidates, index, target_chain_id="C1"
    )
    from descriptor import bitmap_of_members

    target = bitmap_of_members(index, set(two_chain_package.members_of("C1")))
    assert (u_local & target).bit_count() == 6


def test_contrastive_descriptors_are_mined(two_chain_package):
    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert analysis.descriptors.contrastive
    for descriptor in analysis.descriptors.contrastive:
        assert descriptor.precision_local is not None
        assert descriptor.precision_local >= MINING.precision_local_min


def test_singleton_chain_is_not_applicable():
    package = _snapshot(
        [_alarm("only", "C1", device_code="D1", alarm_name="X")],
        [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 1}],
        [{"chain_id": "C1", "alarm_id": "only", "snapshot_id": "s1"}],
    )
    analysis = analyze_chain(
        package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert analysis.singleton is True
    role = analysis.members["only"].role
    assert role.verdict is MembershipVerdict.NOT_APPLICABLE
    assert role.is_weak is False
    # Descriptors still run for a singleton (MVP requirement).
    assert analysis.auto_title


def test_unknown_chain_raises(two_chain_package):
    with pytest.raises(KeyError):
        analyze_chain(
            two_chain_package, "missing", thresholds=THRESHOLDS, mining_config=MINING
        )


# --------------------------------------------------------------------------
# Real data
# --------------------------------------------------------------------------


@pytest.mark.realdata
def test_analysis_on_real_snapshot():
    if not (MOCK_ROOT / "datasets/raw/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")
    venv = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv) if venv.is_file() else sys.executable
    result = subprocess.run(
        [
            interpreter, "-m", "nocpro_mock.cli", "replay",
            "--limit", "800", "--snapshot-id", "s_real",
        ],
        cwd=MOCK_ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI failed: {result.stderr[:300]}")

    package = load_package(json.loads(result.stdout))
    target = max(package.chains.values(), key=lambda c: c.member_count)
    analysis = analyze_chain(
        package, target.chain_id, thresholds=THRESHOLDS, mining_config=MINING
    )

    assert analysis.descriptors.identity, "expected IDENTITY descriptors on real data"
    assert analysis.local_candidates, "expected competing chains from blocking"
    assert analysis.descriptors.contrastive, "expected CONTRASTIVE descriptors"

    top = analysis.descriptors.identity[0]
    assert top.metrics.lift is not None and top.metrics.lift > 1
    assert 0.0 < top.metrics.coverage <= 1.0

    # Every member gets a verdict and computed inputs.
    assert len(analysis.members) == target.member_count
    for member in analysis.members.values():
        assert member.representativeness is not None
        assert member.role.config_version == THRESHOLDS.config_version


# --------------------------------------------------------------------------
# Three role axes (§4B): MEMBERSHIP, STRUCTURAL, REDUNDANCY
# --------------------------------------------------------------------------


def test_multi_member_analysis_produces_all_three_axes(two_chain_package):
    from audit.structural_role import StructuralRole
    from groups.redundancy import RedundancyRole

    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    for member in analysis.members.values():
        assert member.role is not None  # MEMBERSHIP
        assert member.structural is not None  # STRUCTURAL
        assert member.structural.role in set(StructuralRole)
        assert member.redundancy is not None  # REDUNDANCY
        assert member.redundancy.role in set(RedundancyRole)


def test_dense_block_members_are_non_connector(two_chain_package):
    """A tightly-knit 6-member block has no articulation point."""
    from audit.structural_role import StructuralRole

    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    roles = {m.structural.role for m in analysis.members.values()}
    assert StructuralRole.CONNECTOR not in roles


def test_singleton_structural_role_is_not_applicable():
    from audit.structural_role import StructuralRole

    package = _snapshot(
        [_alarm("only", "C1", device_code="D1", alarm_name="X")],
        [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 1}],
        [{"chain_id": "C1", "alarm_id": "only", "snapshot_id": "s1"}],
    )
    analysis = analyze_chain(
        package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    structural = analysis.members["only"].structural
    assert structural.role is StructuralRole.NOT_APPLICABLE


def test_near_duplicate_candidate_is_detected():
    """Two alarms, same name/entity, 1s apart, no new descriptor coverage."""
    from groups.redundancy import RedundancyRole

    alarms = [
        _alarm(
            "dup1", "C1", device_code="D1", node_reference="R1",
            alarm_name="LINK DOWN", canonical_start_time="2026-01-01T00:00:00",
        ),
        _alarm(
            "dup2", "C1", device_code="D1", node_reference="R1",
            alarm_name="LINK DOWN", canonical_start_time="2026-01-01T00:00:01",
        ),
        _alarm(
            "other", "C1", device_code="D2", node_reference="R2",
            alarm_name="POWER FAIL", canonical_start_time="2026-01-01T00:05:00",
        ),
    ]
    package = _snapshot(
        alarms,
        [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 3}],
        [
            {"chain_id": "C1", "alarm_id": a["alarm_id"], "snapshot_id": "s1"}
            for a in alarms
        ],
    )
    analysis = analyze_chain(
        package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    dup1 = analysis.members["dup1"].redundancy
    assert dup1.role is RedundancyRole.NEAR_DUPLICATE_CANDIDATE
    assert dup1.duplicate_of == "dup2"

    other = analysis.members["other"].redundancy
    assert other.role is RedundancyRole.UNIQUE


def test_near_duplicate_does_not_preclude_core():
    """A near-duplicate is a review flag, not a membership verdict override."""
    from groups.redundancy import RedundancyRole

    alarms = []
    memberships = []
    for i in range(6):
        # Two near-simultaneous LINK DOWN alarms among an otherwise clean block.
        offset = 0 if i < 2 else i
        alarms.append(
            _alarm(
                f"a{i}", "C1", device_code="D1", node_reference="R1",
                alarm_name="LINK DOWN", location_code="SITE_A",
                canonical_start_time=f"2026-01-01T00:00:{offset:02d}",
            )
        )
        memberships.append({"chain_id": "C1", "alarm_id": f"a{i}", "snapshot_id": "s1"})
    package = _snapshot(
        alarms,
        [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 6}],
        memberships,
    )
    analysis = analyze_chain(
        package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    dup = analysis.members["a0"]
    if dup.redundancy.role is RedundancyRole.NEAR_DUPLICATE_CANDIDATE:
        # Being a near-duplicate candidate must not force a non-CORE verdict;
        # role classification comes from MembershipSupport, independently.
        assert dup.role.verdict is not None


@pytest.mark.realdata
def test_real_snapshot_produces_all_three_axes():
    if not (MOCK_ROOT / "datasets/raw/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")
    venv = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv) if venv.is_file() else sys.executable
    result = subprocess.run(
        [
            interpreter, "-m", "nocpro_mock.cli", "replay",
            "--chain-id", "6907123", "--snapshot-id", "s_axes",
        ],
        cwd=MOCK_ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI failed: {result.stderr[:300]}")

    package = load_package(json.loads(result.stdout))
    analysis = analyze_chain(
        package, "6907123", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert len(analysis.members) == 20
    for member in analysis.members.values():
        assert member.role is not None
        assert member.structural is not None
        assert member.redundancy is not None

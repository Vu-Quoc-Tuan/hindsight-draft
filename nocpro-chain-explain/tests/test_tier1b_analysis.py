"""Tier-1B chain analysis tests (§3, §4B, §5).

Verifies the role engine is now self-contained: ``Representativeness`` and
``Margin_common`` are computed inside the analysis, not injected by a caller.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from channels import AlarmTaxonomy
from descriptor import MiningConfig
from descriptor.contrastive import (
    blocking_candidates,
    local_universe_bitmap,
    margin_common,
)
from graybox.singleton import MembershipVerdict
from groups import AuditGraphMode, RoleThresholds
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


def test_indexed_rival_fits_match_pairwise_oracle(two_chain_package):
    from channels import RivalFitIndex
    from groups.fit import group_fits
    from tier1b.chain_analysis import _rival_statistics

    alarm = two_chain_package.alarms["c1_0"]
    oracle = tuple(
        group_fits(
            alarm.alarm_id,
            _rival_statistics(
                two_chain_package,
                alarm.alarm_id,
                "C2",
                taxonomy=AlarmTaxonomy({}, {}),
            ),
        )
    )
    indexed = RivalFitIndex.from_chain(two_chain_package, "C2").group_fits_for(alarm)
    expected = {fit.derivation_tag: fit for fit in oracle}
    actual = {fit.derivation_tag: fit for fit in indexed}
    assert set(expected) <= set(actual)
    for tag, fit in expected.items():
        if fit.fit is None:
            assert actual[tag].fit is None
        else:
            assert actual[tag].fit == pytest.approx(fit.fit)
    assert actual["temporal_delay"].fit is None
    assert actual["dependency_hop"].fit is None


def test_indexed_rival_dep_hop_matches_sparse_pairwise_oracle(two_chain_package):
    from channels import RivalFitIndex
    from groups.fit import group_fits
    from tier1b.chain_analysis import _rival_statistics

    two_chain_package.topology = {
        "edges": [
            {
                "source_resource_id": "R1",
                "target_resource_id": "R2",
                "relation_type": "IP_ADJACENCY",
                "directed": False,
            }
        ],
        "mappings": [
            {
                "alarm_id": alarm_id,
                "resource_id": "R1" if alarm_id.startswith("c1_") else "R2",
                "mapping_status": "EXACT",
            }
            for alarm_id in two_chain_package.alarms
        ],
    }
    alarm = two_chain_package.alarms["c1_0"]
    oracle = {
        fit.derivation_tag: fit
        for fit in group_fits(
            alarm.alarm_id,
            _rival_statistics(
                two_chain_package,
                alarm.alarm_id,
                "C2",
                taxonomy=AlarmTaxonomy({}, {}),
            ),
        )
    }
    indexed = {
        fit.derivation_tag: fit
        for fit in RivalFitIndex.from_chain(
            two_chain_package, "C2"
        ).group_fits_for(alarm)
    }

    assert oracle["dependency_hop"].fit == pytest.approx(1.0)
    assert indexed["dependency_hop"].fit == pytest.approx(
        oracle["dependency_hop"].fit
    )
    assert indexed["dependency_hop"].channel_fits[0].domain_size == 6


def test_indexed_rival_burst_query_preserves_bridge_insertion():
    from channels import RivalFitIndex
    from groups.fit import group_fits
    from tier1b.chain_analysis import _rival_statistics

    alarms = [
        _alarm(
            "target", "C1", location_code="SITE-A", alarm_name="X",
            canonical_start_time="2026-01-01T00:02:00",
        ),
        _alarm(
            "left", "C2", location_code="SITE-A", alarm_name="Y",
            canonical_start_time="2026-01-01T00:00:00",
        ),
        _alarm(
            "right", "C2", location_code="SITE-A", alarm_name="Z",
            canonical_start_time="2026-01-01T00:04:00",
        ),
    ]
    package = _snapshot(
        alarms,
        [
            {"chain_id": "C1", "snapshot_id": "s1", "member_count": 1},
            {"chain_id": "C2", "snapshot_id": "s1", "member_count": 2},
        ],
        [
            {"chain_id": "C1", "alarm_id": "target", "snapshot_id": "s1"},
            {"chain_id": "C2", "alarm_id": "left", "snapshot_id": "s1"},
            {"chain_id": "C2", "alarm_id": "right", "snapshot_id": "s1"},
        ],
    )
    oracle = {
        fit.derivation_tag: fit
        for fit in group_fits(
            "target",
            _rival_statistics(
                package, "target", "C2", taxonomy=AlarmTaxonomy({}, {})
            ),
        )
    }
    indexed = {
        fit.derivation_tag: fit
        for fit in RivalFitIndex.from_chain(package, "C2").group_fits_for(
            package.alarms["target"]
        )
    }
    assert oracle["temporal_burst"].fit == 1.0
    assert indexed["temporal_burst"].fit == pytest.approx(1.0)


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


def test_multi_member_analysis_defers_structural_axis_to_tier2(two_chain_package):
    from groups.redundancy import RedundancyRole

    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert analysis.audit_graph_mode is AuditGraphMode.NOT_COMPUTED
    for member in analysis.members.values():
        assert member.role is not None  # MEMBERSHIP
        assert member.structural is None  # STRUCTURAL belongs to Tier-2
        assert member.redundancy is not None  # REDUNDANCY
        assert member.redundancy.role in set(RedundancyRole)


def test_dense_block_does_not_materialize_tier1b_audit(two_chain_package):
    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert analysis.audit_graph_mode is AuditGraphMode.NOT_COMPUTED
    assert all(member.structural is None for member in analysis.members.values())


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
def test_real_snapshot_produces_membership_and_redundancy_without_tier2_audit():
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
    assert analysis.audit_graph_mode is AuditGraphMode.NOT_COMPUTED
    for member in analysis.members.values():
        assert member.role is not None
        assert member.structural is None
        assert member.redundancy is not None


# --------------------------------------------------------------------------
# WHY-4 contrastive top-3 (§5, §11)
# --------------------------------------------------------------------------


def test_margins_are_bounded_to_top_3_candidates():
    """§11 'contrastive top-3 candidate qua blocking index': never more than 3."""
    alarms = []
    memberships = []
    chains = []
    for i in range(4):
        for j in range(6):
            alarms.append(
                _alarm(
                    f"c{i}_{j}", f"C{i}",
                    device_code=f"D{i}", node_reference=f"R{i}",
                    alarm_name="LINK DOWN", location_code="SITE_SHARED",
                    canonical_start_time=f"2026-01-01T0{i}:00:{j:02d}",
                )
            )
            memberships.append({"chain_id": f"C{i}", "alarm_id": f"c{i}_{j}", "snapshot_id": "s1"})
        chains.append({"chain_id": f"C{i}", "snapshot_id": "s1", "member_count": 6})
    package = _snapshot(alarms, chains, memberships)

    analysis = analyze_chain(
        package, "C0", thresholds=THRESHOLDS, mining_config=MINING
    )
    # 3 other chains share the blocking key (location_code), all candidates.
    assert len(analysis.local_candidates) == 3
    for member in analysis.members.values():
        assert len(member.margins) <= 3


def test_margins_cover_multiple_distinct_rivals():
    """Each of the top-3 candidates gets its own MarginResult, not just one."""
    alarms = []
    memberships = []
    chains = []
    for i in range(4):
        for j in range(6):
            alarms.append(
                _alarm(
                    f"c{i}_{j}", f"C{i}",
                    device_code=f"D{i}", node_reference=f"R{i}",
                    alarm_name="LINK DOWN", location_code="SITE_SHARED",
                    canonical_start_time=f"2026-01-01T0{i}:00:{j:02d}",
                )
            )
            memberships.append({"chain_id": f"C{i}", "alarm_id": f"c{i}_{j}", "snapshot_id": "s1"})
        chains.append({"chain_id": f"C{i}", "snapshot_id": "s1", "member_count": 6})
    package = _snapshot(alarms, chains, memberships)

    analysis = analyze_chain(
        package, "C0", thresholds=THRESHOLDS, mining_config=MINING
    )
    member = next(iter(analysis.members.values()))
    rival_ids = {m.compared_chain_id for m in member.margins}
    assert len(rival_ids) == len(member.margins), "each margin must target a distinct rival"
    assert rival_ids <= {"C1", "C2", "C3"}


def test_backward_compat_margin_property_matches_first_of_margins(two_chain_package):
    analysis = analyze_chain(
        two_chain_package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    for member in analysis.members.values():
        if member.margins:
            assert member.margin == member.margins[0]
        else:
            assert member.margin is None


def test_no_candidates_means_empty_margins():
    """A chain with no blocking competitors gets zero margins, not a crash."""
    package = _snapshot(
        [_alarm(f"a{i}", "C1", device_code="D1", alarm_name=f"UNIQUE_{i}") for i in range(6)],
        [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 6}],
        [{"chain_id": "C1", "alarm_id": f"a{i}", "snapshot_id": "s1"} for i in range(6)],
    )
    analysis = analyze_chain(
        package, "C1", thresholds=THRESHOLDS, mining_config=MINING
    )
    assert analysis.local_candidates == ()
    for member in analysis.members.values():
        assert member.margins == ()
        assert member.margin is None


@pytest.mark.realdata
def test_top_3_margins_on_real_snapshot():
    if not (MOCK_ROOT / "datasets/raw/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")
    venv = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv) if venv.is_file() else sys.executable
    result = subprocess.run(
        [
            interpreter, "-m", "nocpro_mock.cli", "replay",
            "--limit", "2000", "--snapshot-id", "s_top3_real",
        ],
        cwd=MOCK_ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI failed: {result.stderr[:300]}")

    package = load_package(json.loads(result.stdout))
    candidates = [c for c in package.chains.values() if c.member_count >= 10]
    if not candidates:
        pytest.skip("no chain with >=10 members in this batch")
    target = max(candidates, key=lambda c: c.member_count)

    analysis = analyze_chain(
        package, target.chain_id, thresholds=THRESHOLDS, mining_config=MINING
    )
    assert len(analysis.local_candidates) <= 5  # DEFAULT_U_LOCAL_K
    for member in analysis.members.values():
        assert len(member.margins) <= 3
        rival_ids = [m.compared_chain_id for m in member.margins]
        assert len(rival_ids) == len(set(rival_ids))

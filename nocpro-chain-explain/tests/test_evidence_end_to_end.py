"""Evidence pipeline against the real export.

Runs channels -> Fit_g -> MembershipSupport -> role on chains that actually
exist in ``alarm_data.csv``, so the numbers come from observed data rather than
constructed fixtures.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from channels import evaluate_chain_channels
from graybox.singleton import MembershipVerdict
from groups import RoleThresholds, classify_membership, membership_support
from libs.contracts import load_package
from tests.conftest import MOCK_ROOT

pytestmark = pytest.mark.realdata

#: Verified in the real export: 20 members.
MID_CHAIN = "6907123"
#: Verified singleton.
SINGLETON_CHAIN = "3263265"
#: Largest observed chain: 1,072 members.
LARGEST_CHAIN = "6907125"

THRESHOLDS = RoleThresholds(config_version="e2e-v1")


def _replay(chain_id: str):
    if not (MOCK_ROOT / "datasets/raw/alarm/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")
    venv_python = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv_python) if venv_python.is_file() else sys.executable
    result = subprocess.run(
        [
            interpreter,
            "-m",
            "nocpro_mock.cli",
            "replay",
            "--chain-id",
            chain_id,
            "--snapshot-id",
            f"s_{chain_id}",
        ],
        cwd=MOCK_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI failed: {result.stderr[:300]}")
    return load_package(json.loads(result.stdout))


@pytest.fixture(scope="module")
def mid_chain_evidence():
    package = _replay(MID_CHAIN)
    return package, evaluate_chain_channels(package, MID_CHAIN)


def test_full_pair_space_is_materialized_for_a_small_chain(mid_chain_evidence):
    _, evidence = mid_chain_evidence
    assert len(evidence.members) == 20
    # C(20,2) = 190
    assert evidence.full_pair_space == 190
    assert evidence.statistics.pairs_counted == 190
    assert evidence.detail_truncated is False
    assert evidence.detail_coverage == pytest.approx(1.0)


def test_all_kpair_channels_are_present(mid_chain_evidence):
    _, evidence = mid_chain_evidence
    channels = set(evidence.matrix.channel_ids())
    assert {
        "E_reference",
        "E_device",
        "E_card",
        "E_site",
        "E_remote",
        "S",
        "T_burst",
        "T_delay",
        "Dep_hop",
    } <= channels


def test_unavailable_channels_are_reported_as_unavailable(mid_chain_evidence):
    """No topology and no fitted delay model => ⊥, not zero."""
    _, evidence = mid_chain_evidence
    member = evidence.members[0]
    support = membership_support(member, evidence.statistics)
    fits = {gf.derivation_tag: gf for gf in support.group_fits}
    assert fits["dependency_hop"].is_unavailable is True
    assert fits["temporal_delay"].is_unavailable is True


def test_computable_channels_produce_real_fits(mid_chain_evidence):
    _, evidence = mid_chain_evidence
    member = evidence.members[0]
    support = membership_support(member, evidence.statistics)
    fits = {gf.derivation_tag: gf for gf in support.group_fits}
    for tag in ("semantic", "temporal_burst", "site", "reference", "device"):
        assert fits[tag].fit is not None, f"{tag} should be computable"
        assert 0.0 <= fits[tag].fit <= 1.0


def test_membership_support_is_bounded_and_gate_passes(mid_chain_evidence):
    _, evidence = mid_chain_evidence
    member = evidence.members[0]
    support = membership_support(member, evidence.statistics)
    assert support.support is not None
    assert 0.0 <= support.support <= 1.0
    assert support.computable_group_count >= 2

    role = classify_membership(
        support, thresholds=THRESHOLDS, chain_size=len(evidence.members)
    )
    assert role.verdict is not MembershipVerdict.INSUFFICIENT_DATA


def test_every_member_gets_a_verdict(mid_chain_evidence):
    _, evidence = mid_chain_evidence
    verdicts = []
    for member in evidence.members:
        support = membership_support(member, evidence.statistics)
        role = classify_membership(
            support, thresholds=THRESHOLDS, chain_size=len(evidence.members)
        )
        verdicts.append(role.verdict)
    assert len(verdicts) == 20
    # No member may silently lack a verdict.
    assert all(v in set(MembershipVerdict) for v in verdicts)


def test_singleton_chain_yields_no_pairs_and_insufficient_data():
    package = _replay(SINGLETON_CHAIN)
    if SINGLETON_CHAIN not in package.chains:
        pytest.skip(f"chain {SINGLETON_CHAIN} absent from this export")
    evidence = evaluate_chain_channels(package, SINGLETON_CHAIN)
    assert evidence.full_pair_space == 0
    assert evidence.statistics.pairs_counted == 0

    support = membership_support(evidence.members[0], evidence.statistics)
    role = classify_membership(support, thresholds=THRESHOLDS, chain_size=1)
    # Never WEAK: there is no pair evidence to be weak about.
    assert role.verdict is MembershipVerdict.INSUFFICIENT_DATA
    assert role.is_weak is False


def test_large_chain_materialization_is_bounded():
    """ADR-0015: C(1072,2)=574,056 must not be materialized unguarded."""
    package = _replay(LARGEST_CHAIN)
    evidence = evaluate_chain_channels(package, LARGEST_CHAIN, pair_detail_limit=5_000)
    assert evidence.full_pair_space == 1072 * 1071 // 2
    assert evidence.detail_pairs == 5_000
    assert evidence.detail_truncated is True
    # Truncation is reported, so downstream reads absence as "not evaluated".
    assert evidence.detail_coverage < 0.02

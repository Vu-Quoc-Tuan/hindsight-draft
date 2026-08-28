"""Does the pair-output cap leak into Fit / MembershipSupport / role?

The cap may bound pair detail, visualization and debug output. It must NOT change
statistical truth: Fit_g, MembershipSupport, role and audit counts.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from channels import evaluate_chain_channels
from groups import RoleThresholds, classify_membership, membership_support
from libs.contracts import load_package
from tests.conftest import MOCK_ROOT

pytestmark = pytest.mark.realdata

CHAIN = "6907123"  # 20 members, C(20,2)=190
THRESHOLDS = RoleThresholds(config_version="cap-v1")


def _replay(chain_id: str):
    if not (MOCK_ROOT / "datasets/raw/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")
    venv = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv) if venv.is_file() else sys.executable
    result = subprocess.run(
        [
            interpreter, "-m", "nocpro_mock.cli", "replay",
            "--chain-id", chain_id, "--snapshot-id", f"s_{chain_id}",
        ],
        cwd=MOCK_ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI failed: {result.stderr[:300]}")
    return load_package(json.loads(result.stdout))


@pytest.fixture(scope="module")
def package():
    return _replay(CHAIN)


def test_pair_materialization_cap_does_not_change_fit(package):
    """Fit_g must be identical whether the cap is 50 or unbounded."""
    capped = evaluate_chain_channels(package, CHAIN, pair_detail_limit=50)
    full = evaluate_chain_channels(package, CHAIN, pair_detail_limit=10_000)

    member = full.members[0]
    capped_fits = {
        gf.derivation_tag: gf.fit
        for gf in membership_support(member, capped.statistics).group_fits
    }
    full_fits = {
        gf.derivation_tag: gf.fit
        for gf in membership_support(member, full.statistics).group_fits
    }
    assert capped_fits == full_fits


def test_pair_materialization_cap_does_not_change_membership_role(package):
    capped = evaluate_chain_channels(package, CHAIN, pair_detail_limit=50)
    full = evaluate_chain_channels(package, CHAIN, pair_detail_limit=10_000)

    for member in full.members:
        capped_role = classify_membership(
            membership_support(member, capped.statistics),
            thresholds=THRESHOLDS,
            chain_size=len(capped.members),
        )
        full_role = classify_membership(
            membership_support(member, full.statistics),
            thresholds=THRESHOLDS,
            chain_size=len(full.members),
        )
        assert capped_role.verdict is full_role.verdict, f"member {member}"
        assert capped_role.support == full_role.support, f"member {member}"


def test_cap_only_changes_reported_output(package):
    """The cap should change reported pair count and truncation, nothing else."""
    capped = evaluate_chain_channels(package, CHAIN, pair_detail_limit=50)
    full = evaluate_chain_channels(package, CHAIN, pair_detail_limit=10_000)
    assert capped.detail_truncated is True
    assert full.detail_truncated is False
    assert capped.detail_pairs < full.detail_pairs
    # Statistics stay exact and complete regardless of the cap.
    assert capped.statistics.pairs_counted == full.statistics.pairs_counted
    assert capped.statistics_exact is True


def test_statistics_never_read_the_capped_matrix():
    """Structural guard: Fit must not accept a pair matrix at all.

    The original bug was Fit_k iterating the capped pair detail, which made the
    verdict a function of a display budget. Keeping ``channel_fit`` /
    ``membership_support`` typed against statistics prevents a silent relapse.
    """
    import inspect

    from groups.fit import channel_fit, group_fits, membership_support

    for function in (channel_fit, group_fits, membership_support):
        parameters = set(inspect.signature(function).parameters)
        assert "matrix" not in parameters, (
            f"{function.__name__} must derive from exact statistics, "
            "not bounded pair detail"
        )
        assert "statistics" in parameters


def test_large_chain_statistics_are_flagged_non_exact(package):
    """Beyond the exact bound the result says so instead of degrading silently."""
    from groups.statistics import EXACT_STATISTICS_MAX_MEMBERS, statistics_are_exact

    assert statistics_are_exact(EXACT_STATISTICS_MAX_MEMBERS) is True
    assert statistics_are_exact(EXACT_STATISTICS_MAX_MEMBERS + 1) is False

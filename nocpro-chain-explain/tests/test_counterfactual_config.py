from __future__ import annotations

from pathlib import Path

import pytest

from configuration import CalibrationStatus, load_analysis_config
from tier2.counterfactual import PartitionDelta


ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG = ROOT / "config/thresholds/v1.yaml"
SYNTHETIC_CONFIG = ROOT / "config/thresholds/e2e-counterfactual.yaml"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "analysis.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_production_config_keeps_counterfactual_fail_closed() -> None:
    config = load_analysis_config(SHIPPED_CONFIG)

    assert config.counterfactual is None
    assert config.counterfactual_reason == "COUNTERFACTUAL_CONFIG_INCOMPLETE"


def test_synthetic_config_loads_every_required_field() -> None:
    config = load_analysis_config(SYNTHETIC_CONFIG)

    review = config.counterfactual
    assert review is not None
    assert review.config_version == "synthetic-counterfactual-v1"
    assert review.calibration_status is CalibrationStatus.SYNTHETIC_ONLY
    assert review.max_chain_members > 0
    assert review.max_remove_candidates > 0
    assert review.max_split_candidates > 0
    assert review.max_move_candidates is not None
    assert review.max_move_candidates > 0
    assert review.max_merge_candidates is not None
    assert review.max_merge_candidates > 0
    assert review.max_recommendations > 0


def test_missing_move_config_only_disables_move(tmp_path: Path) -> None:
    text = SYNTHETIC_CONFIG.read_text(encoding="utf-8")
    config = load_analysis_config(
        _write(tmp_path, text.replace("  move:\n    max_candidates: 10\n", "", 1))
    )

    assert config.counterfactual is not None
    assert config.counterfactual.max_move_candidates is None
    assert config.counterfactual.move_reason == "MOVE_POLICY_NOT_CALIBRATED"


def test_missing_merge_config_only_disables_merge(tmp_path: Path) -> None:
    text = SYNTHETIC_CONFIG.read_text(encoding="utf-8")
    config = load_analysis_config(
        _write(tmp_path, text.replace("  merge:\n    max_candidates: 10\n", "", 1))
    )

    assert config.counterfactual is not None
    assert config.counterfactual.max_merge_candidates is None
    assert config.counterfactual.merge_reason == "MERGE_POLICY_NOT_CALIBRATED"


@pytest.mark.parametrize(
    "line",
    [
        "  pareto_tolerance: 0.0\n",
        "    max_chain_members: 100\n",
        "    membership_support_below: 0.3\n",
        "  config_version: synthetic-counterfactual-v1\n",
    ],
)
def test_counterfactual_config_requires_every_field(
    tmp_path: Path, line: str
) -> None:
    text = SYNTHETIC_CONFIG.read_text(encoding="utf-8")
    config = load_analysis_config(_write(tmp_path, text.replace(line, "", 1)))

    assert config.counterfactual is None
    assert config.counterfactual_reason == "COUNTERFACTUAL_CONFIG_INCOMPLETE"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("    max_chain_members: 100", "    max_chain_members: 0"),
        (
            "    membership_support_below: 0.3",
            "    membership_support_below: 1.1",
        ),
        ("    adverse_margin_below: 0.0", "    adverse_margin_below: .nan"),
        (
            "    minimum_coverage_improvement: 0.05",
            "    minimum_coverage_improvement: -0.1",
        ),
        (
            "  calibration_status: SYNTHETIC_ONLY",
            "  calibration_status: UNKNOWN",
        ),
    ],
)
def test_invalid_counterfactual_config_fails_closed(
    tmp_path: Path, old: str, new: str
) -> None:
    text = SYNTHETIC_CONFIG.read_text(encoding="utf-8")
    config = load_analysis_config(_write(tmp_path, text.replace(old, new, 1)))

    assert config.counterfactual is None
    assert config.counterfactual_reason == "COUNTERFACTUAL_CONFIG_INCOMPLETE"


def test_partition_delta_canonicalizes_chains_and_preserves_universe() -> None:
    delta = PartitionDelta(
        before=(("C", ("B", "A", "X")),),
        after=(("singleton:X", ("X",)), ("C", ("B", "A"))),
    )

    assert delta.before == (("C", ("A", "B", "X")),)
    assert delta.after == (("C", ("A", "B")), ("singleton:X", ("X",)))
    assert delta.alarm_ids == ("A", "B", "X")


def test_partition_delta_rejects_alarm_loss() -> None:
    with pytest.raises(ValueError, match="alarm universe"):
        PartitionDelta(
            before=(("C", ("A", "B")),),
            after=(("C", ("A",)),),
        )


def test_partition_delta_rejects_overlapping_after_chains() -> None:
    with pytest.raises(ValueError, match="more than one chain"):
        PartitionDelta(
            before=(("C", ("A", "B")),),
            after=(("C-left", ("A",)), ("C-right", ("A", "B"))),
        )

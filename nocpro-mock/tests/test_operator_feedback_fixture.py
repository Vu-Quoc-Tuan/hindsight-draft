from __future__ import annotations

import json
from pathlib import Path

import pytest

from nocpro_mock.contract import SourceKind
from nocpro_mock.fixtures import load_synthetic_operator_feedback


def test_synthetic_operator_feedback_is_typed_and_never_production_ground_truth() -> None:
    fixture = load_synthetic_operator_feedback()

    assert fixture.contract_version == "synthetic-operator-feedback-v1"
    assert fixture.source_kind is SourceKind.SYNTHETIC_TEST
    assert fixture.eligible_as_production_ground_truth is False
    assert {(record.operation, record.verdict) for record in fixture.records} == {
        ("REMOVE_MEMBER", "ACCEPTED"),
        ("SPLIT_CHAIN", "ACCEPTED"),
        ("MOVE_MEMBER", "ACCEPTED"),
        ("MERGE_CHAINS", "REJECTED"),
    }


def test_synthetic_operator_feedback_refuses_a_production_eligibility_claim(tmp_path) -> None:
    fixture = json.loads(
        Path("docs/examples/synthetic/operator_feedback/feedback.json").read_text(
            encoding="utf-8"
        )
    )
    fixture["eligible_as_production_ground_truth"] = True
    path = tmp_path / "unsafe-feedback.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot claim production-ground-truth"):
        load_synthetic_operator_feedback(path)

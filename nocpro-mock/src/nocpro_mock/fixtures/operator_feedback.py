"""Typed synthetic operator-feedback fixtures for empirical evaluation tests.

These records model what a later production feedback capture must provide, but
they are deliberately not an operational-validation source.  Their only
purpose is to exercise calibration/evaluation plumbing against known synthetic
counterfactual truth without claiming production evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..contract import SourceKind


FeedbackVerdict = Literal["ACCEPTED", "REJECTED"]
CounterfactualOperation = Literal[
    "REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS"
]

_DEFAULT_FIXTURE = Path("docs/examples/synthetic/operator_feedback/feedback.json")
_OPERATIONS: frozenset[str] = frozenset(
    {"REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS"}
)
_VERDICTS: frozenset[str] = frozenset({"ACCEPTED", "REJECTED"})


@dataclass(frozen=True)
class OperatorFeedbackRecord:
    feedback_id: str
    scenario_id: str
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    operation: CounterfactualOperation
    verdict: FeedbackVerdict
    member_ids: tuple[str, ...] = ()
    source_chain_id: str | None = None
    target_chain_id: str | None = None
    merged_chain_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SyntheticOperatorFeedbackFixture:
    contract_version: str
    fixture_id: str
    source_kind: SourceKind
    eligible_as_production_ground_truth: bool
    records: tuple[OperatorFeedbackRecord, ...]


def _fixture_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    return Path(__file__).resolve().parents[3] / _DEFAULT_FIXTURE


def load_synthetic_operator_feedback(
    path: str | Path | None = None,
) -> SyntheticOperatorFeedbackFixture:
    """Load the explicit mock feedback contract and reject unsafe provenance."""
    raw = json.loads(_fixture_path(path).read_text(encoding="utf-8"))
    if raw.get("contract_version") != "synthetic-operator-feedback-v1":
        raise ValueError("unsupported synthetic operator-feedback contract version")
    if raw.get("source_kind") != SourceKind.SYNTHETIC_TEST.value:
        raise ValueError("mock operator feedback must be SYNTHETIC_TEST")
    if raw.get("eligible_as_production_ground_truth") is not False:
        raise ValueError("synthetic feedback cannot claim production-ground-truth eligibility")

    records: list[OperatorFeedbackRecord] = []
    seen: set[str] = set()
    for entry in raw.get("records") or ():
        feedback_id = str(entry.get("feedback_id") or "")
        operation = str(entry.get("operation") or "")
        verdict = str(entry.get("verdict") or "")
        required = ("scenario_id", "snapshot_id", "snapshot_version", "chain_id")
        if not feedback_id or any(not entry.get(key) for key in required):
            raise ValueError("operator feedback record is missing a stable identity")
        if feedback_id in seen:
            raise ValueError(f"duplicate operator feedback id {feedback_id!r}")
        if operation not in _OPERATIONS or verdict not in _VERDICTS:
            raise ValueError(f"unsupported feedback operation or verdict for {feedback_id!r}")
        seen.add(feedback_id)
        records.append(
            OperatorFeedbackRecord(
                feedback_id=feedback_id,
                scenario_id=str(entry["scenario_id"]),
                snapshot_id=str(entry["snapshot_id"]),
                snapshot_version=str(entry["snapshot_version"]),
                chain_id=str(entry["chain_id"]),
                operation=operation,  # type: ignore[arg-type]
                verdict=verdict,  # type: ignore[arg-type]
                member_ids=tuple(str(item) for item in entry.get("member_ids") or ()),
                source_chain_id=(str(entry["source_chain_id"]) if entry.get("source_chain_id") else None),
                target_chain_id=(str(entry["target_chain_id"]) if entry.get("target_chain_id") else None),
                merged_chain_ids=tuple(str(item) for item in entry.get("merged_chain_ids") or ()),
            )
        )
    if not records:
        raise ValueError("synthetic operator feedback needs at least one record")
    return SyntheticOperatorFeedbackFixture(
        contract_version=raw["contract_version"],
        fixture_id=str(raw.get("fixture_id") or ""),
        source_kind=SourceKind.SYNTHETIC_TEST,
        eligible_as_production_ground_truth=False,
        records=tuple(records),
    )

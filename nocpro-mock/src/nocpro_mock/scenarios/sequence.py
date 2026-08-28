"""Snapshot sequence manifests for history and evolution scenarios.

Decision: the canonical unit stays ``1 MockSnapshotPackage = 1 snapshot``. No
multi-snapshot object is added to contract v1, because the downstream
architecture is snapshot-first (ADR-0005) and sequencing is orchestration, an
mock concern rather than a canonical NocPro input.

A sequence is therefore a directory:

    history_scenario/
    ├── sequence.yaml
    ├── snapshot_000.json
    ├── ...
    └── expected_assertions.yaml

``sequence.yaml`` is a mock/runner artifact and is never handed to Explain as an
input object.

Two roles:

``HISTORY_BOOTSTRAP``
    ``delivery.history_until_exclusive`` marks the target boundary. Snapshots
    before it are delivered as history; the target itself is never inserted into
    history before being emitted/evaluated (ADR-MOCK-0006).

``EVOLUTION``
    ``expected_transitions`` declares the expected event between consecutive
    snapshots (SPLIT, MERGE, ...).

Provenance note: synthetic snapshots keep ``source_kind=SYNTHETIC_TEST``.
``HISTORY_BOOTSTRAP`` is a sequence/delivery role, not a provenance value, so
relabelling them ``BACKFILL`` would erase the fact that they are synthetic.
``BACKFILL`` is reserved for genuinely backfilled real state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from .schema import ScenarioError


class SequenceType(str, Enum):
    HISTORY_BOOTSTRAP = "HISTORY_BOOTSTRAP"
    EVOLUTION = "EVOLUTION"


class EvolutionEvent(str, Enum):
    """Transitions docs 07 §6 requires a scenario to be able to express."""

    CONTINUE = "CONTINUE"
    GROW = "GROW"
    SHRINK = "SHRINK"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    RECOMBINATION = "RECOMBINATION"
    CHAIN_ID_CHANGE = "CHAIN_ID_CHANGE"
    SINGLETON_TO_MULTI = "SINGLETON_TO_MULTI"
    MULTI_TO_SINGLETON = "MULTI_TO_SINGLETON"


@dataclass(frozen=True)
class ExpectedTransition:
    from_snapshot: str
    to_snapshot: str
    expected_event: EvolutionEvent


@dataclass(frozen=True)
class SequenceManifest:
    """Parsed ``sequence.yaml``."""

    scenario_id: str
    sequence_type: SequenceType
    seed: int
    snapshots: tuple[str, ...]
    target_snapshot: str | None = None
    history_until_exclusive: str | None = None
    expected_transitions: tuple[ExpectedTransition, ...] = ()

    @property
    def history_snapshots(self) -> tuple[str, ...]:
        """Snapshots delivered as history, strictly before the target boundary.

        Enforces ``history window < target snapshot``: the boundary file itself is
        excluded, so a scenario cannot use the target to manufacture its own
        prior-history support.
        """
        if self.history_until_exclusive is None:
            return ()
        index = self.snapshots.index(self.history_until_exclusive)
        return self.snapshots[:index]

    def resolve(self, directory: str | Path) -> list[Path]:
        base = Path(directory)
        return [base / name for name in self.snapshots]


def parse_sequence_manifest(data: dict) -> SequenceManifest:
    if not isinstance(data, dict):
        raise ScenarioError("sequence manifest must be a mapping")

    missing = [
        k for k in ("scenario_id", "sequence_type", "seed", "snapshots") if k not in data
    ]
    if missing:
        raise ScenarioError(f"sequence manifest missing required key(s): {missing}")

    raw_type = str(data["sequence_type"])
    try:
        sequence_type = SequenceType(raw_type)
    except ValueError as exc:
        raise ScenarioError(f"unknown sequence_type {raw_type!r}") from exc

    snapshots = tuple(str(s) for s in (data["snapshots"] or ()))
    if len(snapshots) < 2:
        raise ScenarioError("a sequence needs at least two snapshots")
    if len(set(snapshots)) != len(snapshots):
        raise ScenarioError("sequence lists a snapshot more than once")

    seed = data["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ScenarioError(f"sequence seed must be an integer, got {seed!r}")

    target = data.get("target_snapshot")
    target = str(target) if target else None
    if target is not None and target not in snapshots:
        raise ScenarioError(f"target_snapshot {target!r} is not in snapshots")

    delivery = data.get("delivery") or {}
    boundary = delivery.get("history_until_exclusive")
    boundary = str(boundary) if boundary else None
    if boundary is not None and boundary not in snapshots:
        raise ScenarioError(
            f"delivery.history_until_exclusive {boundary!r} is not in snapshots"
        )

    transitions: list[ExpectedTransition] = []
    for entry in data.get("expected_transitions") or ():
        source = str(entry.get("from") or "")
        dest = str(entry.get("to") or "")
        raw_event = str(entry.get("expected_event") or "")
        if source not in snapshots:
            raise ScenarioError(f"transition 'from' {source!r} is not in snapshots")
        if dest not in snapshots:
            raise ScenarioError(f"transition 'to' {dest!r} is not in snapshots")
        if snapshots.index(dest) != snapshots.index(source) + 1:
            raise ScenarioError(
                f"transition {source!r} -> {dest!r} must be between consecutive snapshots"
            )
        try:
            event = EvolutionEvent(raw_event)
        except ValueError as exc:
            raise ScenarioError(f"unknown expected_event {raw_event!r}") from exc
        transitions.append(
            ExpectedTransition(
                from_snapshot=source, to_snapshot=dest, expected_event=event
            )
        )

    if sequence_type is SequenceType.HISTORY_BOOTSTRAP:
        if boundary is None:
            raise ScenarioError(
                "HISTORY_BOOTSTRAP requires delivery.history_until_exclusive so the "
                "target snapshot cannot leak into history (ADR-MOCK-0006)"
            )
        if target is not None and target != boundary:
            raise ScenarioError(
                f"target_snapshot {target!r} must equal "
                f"delivery.history_until_exclusive {boundary!r}"
            )
    if sequence_type is SequenceType.EVOLUTION and not transitions:
        raise ScenarioError("EVOLUTION sequence requires expected_transitions")

    return SequenceManifest(
        scenario_id=str(data["scenario_id"]),
        sequence_type=sequence_type,
        seed=seed,
        snapshots=snapshots,
        target_snapshot=target,
        history_until_exclusive=boundary,
        expected_transitions=tuple(transitions),
    )


def load_sequence_manifest(path: str | Path) -> SequenceManifest:
    target = Path(path)
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioError(f"{target}: invalid YAML: {exc}") from exc
    if data is None:
        raise ScenarioError(f"{target}: empty sequence manifest")
    return parse_sequence_manifest(data)

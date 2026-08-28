"""Step-mode sequence replay (docs 09).

The producer only ever knows ``emit(MockSnapshotPackage)``. This runner walks a
sequence manifest and emits one ordinary package per step, which is what keeps
sequencing an orchestration concern instead of a contract object.

``step`` is implemented here; ``fast`` / ``realtime`` are timing policies over
the same iteration and are not yet implemented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..contract import ContractViolation, validate_package
from ..scenarios.sequence import SequenceManifest, SequenceType, load_sequence_manifest


@dataclass
class StepResult:
    """One emitted step."""

    index: int
    name: str
    path: Path
    payload: dict
    is_history: bool
    is_target: bool


class SequenceRunner:
    """Walks a sequence manifest and yields its snapshots in declared order.

    Snapshots are read as already-serialized packages, so a sequence can be
    replayed without re-running the generators that produced it.
    """

    def __init__(self, directory: str | Path, manifest: SequenceManifest | None = None):
        self.directory = Path(directory)
        self.manifest = manifest or load_sequence_manifest(
            self.directory / "sequence.yaml"
        )
        self._index = 0

    def __len__(self) -> int:
        return len(self.manifest.snapshots)

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self.manifest.snapshots)

    def reset(self) -> None:
        self._index = 0

    def step(self) -> StepResult | None:
        """Emit the next snapshot, or ``None`` when the sequence is finished."""
        if self.exhausted:
            return None

        index = self._index
        name = self.manifest.snapshots[index]
        path = self.directory / name
        if not path.is_file():
            raise FileNotFoundError(f"sequence snapshot not found: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        self._index += 1
        return StepResult(
            index=index,
            name=name,
            path=path,
            payload=payload,
            is_history=name in self.manifest.history_snapshots,
            is_target=name == self.manifest.target_snapshot,
        )

    def run(self) -> list[StepResult]:
        self.reset()
        results: list[StepResult] = []
        while True:
            result = self.step()
            if result is None:
                return results
            results.append(result)

    def history_then_target(self) -> tuple[list[StepResult], StepResult | None]:
        """Split the sequence at the history boundary.

        Only meaningful for ``HISTORY_BOOTSTRAP``: history snapshots are strictly
        before the target, so the target cannot contribute to its own history.
        """
        if self.manifest.sequence_type is not SequenceType.HISTORY_BOOTSTRAP:
            raise ValueError(
                "history_then_target() applies to HISTORY_BOOTSTRAP sequences only"
            )
        steps = self.run()
        history = [s for s in steps if s.is_history]
        target = next((s for s in steps if s.is_target), None)
        return history, target


def validate_sequence_payloads(directory: str | Path) -> list[str]:
    """Report contract errors across every snapshot in a sequence.

    Returns a list of messages; empty means the whole sequence validates. Kept
    separate from :class:`SequenceRunner` so replay does not require rebuilding
    dataclasses from JSON.
    """
    runner = SequenceRunner(directory)
    errors: list[str] = []
    for step in runner.run():
        version = step.payload.get("schema_version")
        if version != "v1":
            errors.append(f"{step.name}: incompatible schema_version {version!r}")
        snapshot = step.payload.get("snapshot") or {}
        if not snapshot.get("snapshot_id"):
            errors.append(f"{step.name}: snapshot.snapshot_id is missing")
        if snapshot.get("status") != "COMPLETE":
            errors.append(
                f"{step.name}: snapshot.status={snapshot.get('status')!r}; "
                "Tier-1A requires COMPLETE"
            )
    return errors


__all__ = [
    "ContractViolation",
    "SequenceRunner",
    "StepResult",
    "validate_package",
    "validate_sequence_payloads",
]

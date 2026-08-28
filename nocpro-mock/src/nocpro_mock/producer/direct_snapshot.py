"""Direct Snapshot producer.

The reference prototype output path (ADR-MOCK-0007, ADR-0030). Contract
validation happens here and cannot be bypassed: an invalid package is never
written. Kafka, if added later, must reuse this same canonical serialization.
"""

from __future__ import annotations

from pathlib import Path

from ..contract import (
    MockSnapshotPackage,
    ValidationResult,
    package_to_json,
    validate_package,
)


class DirectSnapshotProducer:
    """Serializes validated snapshot packages to canonical JSON."""

    def __init__(self, *, validate: bool = True) -> None:
        #: Validation is on by default; disabling it is for negative tests only.
        self.validate = validate

    def render(self, package: MockSnapshotPackage) -> str:
        if self.validate:
            self.check(package).raise_if_failed()
        return package_to_json(package)

    def check(self, package: MockSnapshotPackage) -> ValidationResult:
        return validate_package(package)

    def write(self, package: MockSnapshotPackage, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.render(package) + "\n", encoding="utf-8")
        return target

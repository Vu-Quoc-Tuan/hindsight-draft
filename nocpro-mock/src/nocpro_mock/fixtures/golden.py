"""Golden Gray-box fixture loader (chain 2214039).

The fixture is stored separately from the alarm export: chain ``2214039`` does
not appear in ``alarm_data.csv`` (verified: 0 rows). It is therefore replayed
from its own observed-facts files, not sliced out of the CSV.

Immutability (ADR-MOCK-0004): this loader is read-only. Capability variants must
be built as clones with explicit mutations and ``SYNTHETIC_TEST`` provenance.

Emitted (docs 11): chain/members, ``M_chain_rule``, ``M_chain_characteristic``.
Never emitted: exact ``M_pair`` vectors, ``simiDict``, ``A_ij``, ΔQ, node
movement, or connector semantics beyond the source labels.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..contract import (
    ChainCharacteristic,
    ChainRule,
    CoverageScope,
    ProvenanceClass,
    SourceKind,
    SystemMetadata,
)

GOLDEN_FIXTURE_ID = "golden_2214039"
GOLDEN_CHAIN_ID = "2214039"

_DEFAULT_FIXTURE_DIR = Path("docs/examples/golden_2214039")


@dataclass(frozen=True)
class GoldenFixture:
    """Observed facts for the Golden chain."""

    fixture_id: str
    chain_id: str
    member_count: int
    event_span_seconds: int
    merge_strategy: str
    source_kind: SourceKind
    system_metadata: SystemMetadata
    notes: tuple[str, ...] = ()


def _resolve_dir(fixture_dir: str | Path | None) -> Path:
    if fixture_dir is not None:
        return Path(fixture_dir)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / _DEFAULT_FIXTURE_DIR


def _coverage(raw: str | None) -> CoverageScope:
    """Unknown or absent coverage scope stays UNKNOWN (docs 03)."""
    if not raw:
        return CoverageScope.UNKNOWN
    try:
        return CoverageScope(raw)
    except ValueError:
        return CoverageScope.UNKNOWN


def load_golden_fixture(fixture_dir: str | Path | None = None) -> GoldenFixture:
    """Load the Golden fixture from its observed-facts files."""
    directory = _resolve_dir(fixture_dir)
    meta = json.loads((directory / "system_metadata.json").read_text(encoding="utf-8"))
    characteristics_raw = json.loads(
        (directory / "characteristics.json").read_text(encoding="utf-8")
    )

    chain_id = str(meta["chain_id"])
    rules = tuple(
        ChainRule(
            chain_id=chain_id,
            rule_name=rule["rule_name"],
            member_count=int(rule["member_count"]),
            connector_count=(
                int(rule["connector_count"]) if "connector_count" in rule else None
            ),
            extender_count=(
                int(rule["extender_count"]) if "extender_count" in rule else None
            ),
            merge_strategy=meta.get("merge_strategy"),
            provenance_class=ProvenanceClass.SYSTEM_FACT,
        )
        for rule in meta.get("rules", [])
    )

    characteristics = tuple(
        ChainCharacteristic(
            chain_id=chain_id,
            name=item["name"],
            pair_count=int(item["pair_count"]),
            coverage_scope=_coverage(item.get("coverage_scope")),
            value=item.get("value"),
            threshold_seconds=(
                int(item["threshold_seconds"]) if "threshold_seconds" in item else None
            ),
            provenance_class=ProvenanceClass.SYSTEM_FACT,
        )
        for item in characteristics_raw
    )

    return GoldenFixture(
        fixture_id=str(meta.get("fixture_id", GOLDEN_FIXTURE_ID)),
        chain_id=chain_id,
        member_count=int(meta["member_count"]),
        event_span_seconds=int(meta["event_span_seconds"]),
        merge_strategy=str(meta["merge_strategy"]),
        source_kind=SourceKind(meta.get("source_kind", "REAL_EXPORT_REPLAY")),
        system_metadata=SystemMetadata(
            chain_rules=rules,
            chain_characteristics=characteristics,
            # Exact per-pair metadata is not sourced, so none is emitted.
            attribute_configs=(),
            pair_metadata=(),
        ),
        notes=tuple(meta.get("notes", ())),
    )

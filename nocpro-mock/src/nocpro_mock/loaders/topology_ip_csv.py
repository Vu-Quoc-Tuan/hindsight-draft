"""IP topology (``topoIP``) export loader.

Verified against the real export (docs 02/13):
  - 201,977 relation rows, 16 columns
  - ~90.386% of source-side rows are ``SITE_ROUTER``
  - ``update_time_vipa`` provides freshness

Capability boundary (docs 06, ADR-MOCK-0005). This source supports adjacency,
port endpoints, network class and freshness. It does NOT support routing
direction, upstream/downstream, active path, dominator or fault dependency, so
every emitted edge stays ``IP_ADJACENCY`` with ``directed=False``.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .alarm_csv import ENCODING, _configure_csv_limits, parse_timestamp

COL_ID = "id"
COL_DEVICE = "device_code"
COL_NETWORK_CLASS = "network_class_name"
COL_PORT = "interface_port"
COL_DEVICE_REL = "device_code_relation"
COL_NETWORK_CLASS_REL = "network_class_name_relation"
COL_PORT_REL = "interface_port_relation"
COL_UPDATE_TIME = "update_time_vipa"


@dataclass(frozen=True)
class TopoIPRelation:
    """One adjacency row. Endpoint order is as exported, not a direction claim."""

    relation_id: str
    device_code: str | None
    device_code_relation: str | None
    raw: dict[str, str]
    network_class_name: str | None = None
    network_class_name_relation: str | None = None
    interface_port: str | None = None
    interface_port_relation: str | None = None
    canonical_update_time: datetime | None = None

    @property
    def raw_update_time(self) -> str | None:
        return self.raw.get(COL_UPDATE_TIME)

    def freshness_age_seconds(self, reference: datetime) -> int | None:
        """Age relative to snapshot replay time; ``None`` when unknown."""
        if self.canonical_update_time is None:
            return None
        return int((reference - self.canonical_update_time).total_seconds())


@dataclass
class TopoIPSourceProfile:
    file_path: str
    row_count: int = 0
    column_count: int = 0
    columns: tuple[str, ...] = ()
    unique_devices: int = 0
    source_network_class_counts: dict[str, int] = field(default_factory=dict)
    rows_with_update_time: int = 0

    def source_class_pct(self, class_name: str) -> float:
        if not self.row_count:
            return 0.0
        return 100.0 * self.source_network_class_counts.get(class_name, 0) / self.row_count


class TopoIPLoader:
    """Streaming loader for the IP adjacency export."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        _configure_csv_limits()

    def iter_relations(self) -> Iterator[TopoIPRelation]:
        with self.path.open("r", newline="", encoding=ENCODING, errors="replace") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return
            for row in reader:
                yield self._build(row)

    def load(self) -> list[TopoIPRelation]:
        return list(self.iter_relations())

    def columns(self) -> tuple[str, ...]:
        with self.path.open("r", newline="", encoding=ENCODING, errors="replace") as fh:
            reader = csv.reader(fh)
            try:
                return tuple(next(reader))
            except StopIteration:
                return ()

    def device_codes(self) -> set[str]:
        """Every device identifier present on either endpoint.

        Used for exact-identity mapping. Prefix/fuzzy lookups are intentionally
        not offered here (ADR-MOCK-0005).
        """
        found: set[str] = set()
        for rel in self.iter_relations():
            if rel.device_code:
                found.add(rel.device_code)
            if rel.device_code_relation:
                found.add(rel.device_code_relation)
        return found

    def profile(self) -> TopoIPSourceProfile:
        columns = self.columns()
        prof = TopoIPSourceProfile(
            file_path=str(self.path),
            column_count=len(columns),
            columns=columns,
        )
        classes: Counter[str] = Counter()
        devices: set[str] = set()

        for rel in self.iter_relations():
            prof.row_count += 1
            if rel.network_class_name:
                classes[rel.network_class_name] += 1
            if rel.device_code:
                devices.add(rel.device_code)
            if rel.device_code_relation:
                devices.add(rel.device_code_relation)
            if rel.canonical_update_time is not None:
                prof.rows_with_update_time += 1

        prof.unique_devices = len(devices)
        prof.source_network_class_counts = dict(classes)
        return prof

    def _build(self, row: dict[str, str | None]) -> TopoIPRelation:
        raw = {k: ("" if v is None else v) for k, v in row.items() if k is not None}

        def val(column: str) -> str | None:
            text = (raw.get(column) or "").strip()
            return text or None

        return TopoIPRelation(
            relation_id=(raw.get(COL_ID) or "").strip(),
            device_code=val(COL_DEVICE),
            device_code_relation=val(COL_DEVICE_REL),
            raw=raw,
            network_class_name=val(COL_NETWORK_CLASS),
            network_class_name_relation=val(COL_NETWORK_CLASS_REL),
            interface_port=val(COL_PORT),
            interface_port_relation=val(COL_PORT_REL),
            canonical_update_time=parse_timestamp(raw.get(COL_UPDATE_TIME)),
        )

"""Alarm export CSV loader.

Verified against the real export (docs 02/13):
  - 8,714 logical records across 26,508 physical lines (quoted multiline content)
  - 96 columns, UTF-8 **with BOM**
  - 2,824 unique ``chaining_id``; 2,072 singleton chains
  - dirty timestamps: 2 year-2098 start times, 360 rows with end < start

Policy (ADR-MOCK-0002): raw strings are preserved exactly as exported; canonical
parsed values are additive; dirty rows are flagged, never repaired. A flagged
future or out-of-order endpoint is withheld from canonical time fields so it
cannot silently affect spans or temporal channels.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..contract import QualityFlag

#: The export is UTF-8 with a BOM; ``utf-8-sig`` keeps the first header name clean.
ENCODING = "utf-8-sig"

#: Large ``content``/``addition_info`` values exceed the default field limit.
_FIELD_SIZE_LIMIT = 10**9

_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d",
)

COL_CHAINING_ID = "chaining_id"
COL_ALARM_ID = "cah.id"
COL_START = "cah.start_time"
COL_END = "end_time"


def _configure_csv_limits() -> None:
    try:
        csv.field_size_limit(_FIELD_SIZE_LIMIT)
    except OverflowError:  # pragma: no cover - platform dependent
        csv.field_size_limit(2**31 - 1)


def parse_timestamp(raw: str | None) -> datetime | None:
    """Parse a timestamp without repairing it. Returns ``None`` if unparseable."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class AlarmRecord:
    """One alarm row: raw values retained, canonical values added."""

    alarm_id: str
    chaining_id: str
    raw: dict[str, str]
    canonical_start_time: datetime | None
    canonical_end_time: datetime | None
    quality_flags: tuple[str, ...]

    @property
    def raw_start_time(self) -> str | None:
        return self.raw.get(COL_START)

    @property
    def raw_end_time(self) -> str | None:
        return self.raw.get(COL_END)

    def get(self, column: str) -> str | None:
        value = self.raw.get(column)
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @property
    def alarm_name(self) -> str | None:
        return self.get("alarm_name")

    @property
    def device_code(self) -> str | None:
        return self.get("device_code")

    @property
    def node_reference(self) -> str | None:
        return self.get("node_reference")

    @property
    def severity_name(self) -> str | None:
        return self.get("severity_name")


@dataclass
class AlarmSourceProfile:
    """Observed profile of a loaded export, used for parser/regression tests."""

    file_path: str
    record_count: int = 0
    column_count: int = 0
    columns: tuple[str, ...] = ()
    unique_chaining_ids: int = 0
    singleton_chains: int = 0
    max_chain_size: int = 0
    max_chain_id: str | None = None
    unique_device_codes: int = 0
    node_reference_filled: int = 0
    flag_counts: dict[str, int] = field(default_factory=dict)

    @property
    def singleton_pct(self) -> float:
        if not self.unique_chaining_ids:
            return 0.0
        return 100.0 * self.singleton_chains / self.unique_chaining_ids

    @property
    def node_reference_fill_pct(self) -> float:
        if not self.record_count:
            return 0.0
        return 100.0 * self.node_reference_filled / self.record_count


class AlarmCsvLoader:
    """Streaming loader for the alarm export."""

    def __init__(self, path: str | Path, *, future_year_threshold: int = 2030) -> None:
        self.path = Path(path)
        self.future_year_threshold = future_year_threshold
        _configure_csv_limits()

    def iter_records(self) -> Iterator[AlarmRecord]:
        """Yield records one at a time; the largest export is ~365 MB."""
        with self.path.open("r", newline="", encoding=ENCODING, errors="replace") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return
            for row in reader:
                yield self._build_record(row)

    def load(self) -> list[AlarmRecord]:
        return list(self.iter_records())

    def columns(self) -> tuple[str, ...]:
        with self.path.open("r", newline="", encoding=ENCODING, errors="replace") as fh:
            reader = csv.reader(fh)
            try:
                return tuple(next(reader))
            except StopIteration:
                return ()

    def profile(self) -> AlarmSourceProfile:
        """Compute the observed profile in a single streaming pass."""
        columns = self.columns()
        prof = AlarmSourceProfile(
            file_path=str(self.path),
            column_count=len(columns),
            columns=columns,
        )
        chain_sizes: Counter[str] = Counter()
        devices: set[str] = set()
        flags: Counter[str] = Counter()

        for record in self.iter_records():
            prof.record_count += 1
            chain_sizes[record.chaining_id] += 1
            if record.device_code:
                devices.add(record.device_code)
            if record.node_reference:
                prof.node_reference_filled += 1
            for flag in record.quality_flags:
                flags[flag] += 1

        prof.unique_chaining_ids = len(chain_sizes)
        prof.singleton_chains = sum(1 for size in chain_sizes.values() if size == 1)
        prof.unique_device_codes = len(devices)
        if chain_sizes:
            chain_id, size = chain_sizes.most_common(1)[0]
            prof.max_chain_id = chain_id
            prof.max_chain_size = size
        prof.flag_counts = dict(flags)
        return prof

    def _build_record(self, row: dict[str, str | None]) -> AlarmRecord:
        raw = {k: ("" if v is None else v) for k, v in row.items() if k is not None}
        flags: list[str] = []

        alarm_id = (raw.get(COL_ALARM_ID) or "").strip()
        chaining_id = (raw.get(COL_CHAINING_ID) or "").strip()
        if not alarm_id:
            flags.append(QualityFlag.MISSING_REQUIRED_ID.value)
        if not (raw.get("device_code") or "").strip():
            flags.append(QualityFlag.MISSING_DEVICE_CODE.value)
        if not (raw.get("node_reference") or "").strip():
            flags.append(QualityFlag.MISSING_NODE_REFERENCE.value)

        if any("\n" in value or "\r" in value for value in raw.values()):
            flags.append(QualityFlag.MULTILINE_CONTENT.value)

        raw_start = raw.get(COL_START)
        raw_end = raw.get(COL_END)
        start = parse_timestamp(raw_start)
        end = parse_timestamp(raw_end)

        if (raw_start or "").strip() and start is None:
            flags.append(QualityFlag.UNPARSEABLE_TIMESTAMP.value)
        if (raw_end or "").strip() and end is None:
            flags.append(QualityFlag.UNPARSEABLE_TIMESTAMP.value)

        future_start = start is not None and start.year >= self.future_year_threshold
        future_end = end is not None and end.year >= self.future_year_threshold
        if future_start:
            flags.append(QualityFlag.TIMESTAMP_FUTURE_OUTLIER.value)
        if future_end:
            flags.append(QualityFlag.TIMESTAMP_FUTURE_OUTLIER.value)

        # Both timestamps must parse before an ordering claim is made.
        end_before_start = start is not None and end is not None and end < start
        if end_before_start:
            flags.append(QualityFlag.END_BEFORE_START.value)

        # Keep the exported strings above for audit. Invalid canonical endpoints
        # are unavailable to every downstream time-based consumer.
        if future_start:
            start = None
        if future_end or end_before_start:
            end = None

        return AlarmRecord(
            alarm_id=alarm_id,
            chaining_id=chaining_id,
            raw=raw,
            canonical_start_time=start,
            canonical_end_time=end,
            # De-duplicate while keeping first-seen order for deterministic output.
            quality_flags=tuple(dict.fromkeys(flags)),
        )

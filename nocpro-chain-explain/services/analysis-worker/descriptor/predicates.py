"""Predicate extraction and bitmaps for descriptor mining (§5, P0).

Bitmap-backed bounded subgroup discovery:

    B_p  bitmap per predicate
    B_r  = AND of member bitmaps
    TP/FP by popcount

Python ``int`` is used as the bitset: it is arbitrary-precision, and ``&``/
``bit_count()`` map straight onto the packed-bitset and popcount operations the
spec calls for. A dense/Roaring hybrid is a later optimization, not a semantic
change.

Only whitelisted structured fields become predicates. Free-text is excluded:
mining raw ``content`` would produce descriptors that cannot be traced to a
field, which breaks provenance.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedAlarm

#: Structured fields eligible for predicate mining, with their derivation tag.
#: Ordered for deterministic candidate enumeration.
PREDICATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("node_reference", "reference"),
    ("device_code", "device"),
    ("alarm_name", "semantic"),
    ("location_code", "site"),
    ("component", "card"),
    ("remote_node", "remote"),
    ("severity_name", "severity"),
    ("network_class_name", "network_class"),
    ("alarm_type_name", "alarm_type"),
)

#: Cap on distinct values kept per field, by descending frequency in the universe.
DEFAULT_MAX_VALUES_PER_FIELD = 32


@dataclass(frozen=True)
class Predicate:
    """One equality predicate ``field = value``."""

    field: str
    value: str
    derivation_tag: str

    def __str__(self) -> str:
        return f"{self.field}={self.value}"

    def matches(self, alarm: IngestedAlarm) -> bool:
        return read_field(alarm, self.field) == self.value


def read_field(alarm: IngestedAlarm, field: str) -> str | None:
    """Read a whitelisted field, preferring the canonical attribute."""
    value = getattr(alarm, field, None)
    if value is None:
        value = alarm.raw.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class PredicateIndex:
    """Inverted index: predicate -> bitmap over the universe.

    ``universe`` is the ordered alarm list; bit *i* corresponds to
    ``universe[i]``. Bitmaps are shared by IDENTITY and CONTRASTIVE mining, so
    both objectives run on one engine as the spec requires.
    """

    universe: tuple[str, ...]
    bitmaps: dict[Predicate, int]

    @property
    def size(self) -> int:
        return len(self.universe)

    def bitmap(self, predicate: Predicate) -> int:
        return self.bitmaps.get(predicate, 0)

    def predicates(self) -> list[Predicate]:
        # Sorted so mining is deterministic for a fixed universe.
        return sorted(self.bitmaps, key=lambda p: (p.field, p.value))


def popcount(bitmap: int) -> int:
    """Number of set bits."""
    return bitmap.bit_count()


def build_predicate_index(
    universe: list[IngestedAlarm],
    *,
    fields: tuple[tuple[str, str], ...] = PREDICATE_FIELDS,
    max_values_per_field: int = DEFAULT_MAX_VALUES_PER_FIELD,
) -> PredicateIndex:
    """Build predicate bitmaps over the universe.

    Per-field values are capped by frequency, which is the "top-K attributes"
    bound in the spec: 20k predicates would be ~250MB dense.
    """
    ordered_ids = tuple(a.alarm_id for a in universe)
    raw: dict[Predicate, int] = {}
    counts: dict[tuple[str, str], int] = {}

    for index, alarm in enumerate(universe):
        bit = 1 << index
        for field, derivation_tag in fields:
            value = read_field(alarm, field)
            if value is None:
                # A missing field yields no predicate; it never becomes a
                # "value is empty" descriptor.
                continue
            predicate = Predicate(
                field=field, value=value, derivation_tag=derivation_tag
            )
            raw[predicate] = raw.get(predicate, 0) | bit
            counts[(field, value)] = counts.get((field, value), 0) + 1

    # Keep the most frequent values per field.
    kept: dict[Predicate, int] = {}
    by_field: dict[str, list[Predicate]] = {}
    for predicate in raw:
        by_field.setdefault(predicate.field, []).append(predicate)
    for field, predicates in by_field.items():
        predicates.sort(
            key=lambda p: (-counts[(p.field, p.value)], p.value)
        )
        for predicate in predicates[:max_values_per_field]:
            kept[predicate] = raw[predicate]

    return PredicateIndex(universe=ordered_ids, bitmaps=kept)


def bitmap_of_members(index: PredicateIndex, member_ids: set[str]) -> int:
    """Bitmap for an explicit member set, e.g. the chain being explained."""
    bitmap = 0
    for position, alarm_id in enumerate(index.universe):
        if alarm_id in member_ids:
            bitmap |= 1 << position
    return bitmap

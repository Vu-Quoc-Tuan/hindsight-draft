"""Raw taxonomy-field adapter for NocPro alarms.

Extracts structured taxonomy-like source fields from NocPro export records:
- Type: derived from ``fault_id`` and/or canonical ``alarm_name``.
- Family: derived from ``group_name`` (e.g., 'Cảnh báo power Core', 'Cảnh báo UDCNTT_VCLOUD').
- Category: derived from ``network_class_name`` or ``monitor_type_name``.

This adapter exposes populated raw fields as optional replay/context tokens.
It does not establish an authoritative production taxonomy: that requires a
separately versioned, business-owned taxonomy source. Missing values stay
missing; this module never invents fallback labels or promotes these fields to
production H/T_delay eligibility.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, Mapping

from libs.contracts import IngestedAlarm
from channels.semantic import AlarmTaxonomy
from history.evidence import HistoricalTaxonomy, TaxonomyTokens


def extract_taxonomy_tokens_from_alarm(alarm: IngestedAlarm | Mapping[str, Any]) -> tuple[str, TaxonomyTokens] | None:
    """Extract (alarm_name, TaxonomyTokens) from an alarm object or raw dict."""
    if isinstance(alarm, IngestedAlarm):
        name = (alarm.alarm_name or "").strip()
        raw = alarm.raw or {}
    else:
        name = str(alarm.get("alarm_name") or "").strip()
        raw = alarm

    if not name:
        # HistoricalTaxonomy is keyed by canonical alarm_name.  A fault ID is
        # not a substitute join key, so do not fabricate one.
        return None

    # These are direct source-field values only.  No alarm-name, group-ID, or
    # generic fallback may manufacture a token at a missing level.
    alarm_type = (
        str(raw.get("alarm_type_name") or "").strip()
        or str(raw.get("fault_id") or "").strip()
        or None
    )

    family = str(raw.get("group_name") or "").strip() or None

    # Some exports populate one of these raw fields; neither missing case is
    # a license to manufacture a generic NETWORK category.
    category = (
        str(raw.get("network_class_name") or "").strip()
        or str(raw.get("monitor_type_name") or "").strip()
        or None
    )

    tokens = TaxonomyTokens(type=alarm_type, family=family, category=category)
    return name, tokens


def build_real_alarm_taxonomy(
    alarms: Iterable[IngestedAlarm | Mapping[str, Any]],
) -> AlarmTaxonomy:
    """Build an AlarmTaxonomy instance for semantic channel and Similar Chains."""
    families: dict[str, str] = {}
    categories: dict[str, str] = {}

    for item in alarms:
        extracted = extract_taxonomy_tokens_from_alarm(item)
        if extracted is None:
            continue
        name, tokens = extracted
        if tokens.family and name not in families:
            families[name] = tokens.family
        if tokens.category and name not in categories:
            categories[name] = tokens.category

    return AlarmTaxonomy(families=families, categories=categories)


def build_real_historical_taxonomy(
    alarms: Iterable[IngestedAlarm | Mapping[str, Any]],
    *,
    source_id: str = "real-nocpro-export",
    version: str = "real-taxonomy-v1",
) -> HistoricalTaxonomy:
    """Build a replay/test taxonomy object; it is not production authority."""
    mappings: dict[str, TaxonomyTokens] = {}

    for item in alarms:
        extracted = extract_taxonomy_tokens_from_alarm(item)
        if extracted is None:
            continue
        name, tokens = extracted
        if name not in mappings:
            mappings[name] = tokens

    return HistoricalTaxonomy(
        source_id=source_id,
        source_version=version,
        tokens_by_alarm_name=mappings,
    )


def load_taxonomy_from_csv(
    csv_path: str | Path,
    *,
    version: str = "csv-taxonomy-v1",
) -> tuple[AlarmTaxonomy, HistoricalTaxonomy]:
    """Parse CSV export and return both (AlarmTaxonomy, HistoricalTaxonomy)."""
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"Alarm CSV not found: {p}")

    records = []
    with p.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)

    alarm_tax = build_real_alarm_taxonomy(records)
    hist_tax = build_real_historical_taxonomy(records, version=version)
    return alarm_tax, hist_tax

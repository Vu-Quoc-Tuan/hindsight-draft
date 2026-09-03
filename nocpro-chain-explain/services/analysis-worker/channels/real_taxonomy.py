"""Real Data Taxonomy Adapter for NocPro Alarms.

Extracts structured, ground-truth taxonomy from NocPro production records:
- Type: derived from ``fault_id`` and/or canonical ``alarm_name``.
- Family: derived from ``group_name`` (e.g., 'Cảnh báo power Core', 'Cảnh báo UDCNTT_VCLOUD').
- Category: derived from ``network_class_name`` or ``monitor_type_name``.

This adapter bridges actual Viettel NocPro data exports into canonical
``AlarmTaxonomy`` and ``HistoricalTaxonomy`` without heuristic string guessing.
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
        # Fallback to fault_id or chaining_name if alarm_name is missing
        fault_id = str(raw.get("fault_id") or "").strip()
        if fault_id:
            name = f"FAULT_{fault_id}"
        else:
            return None

    # 1. Type: fault_id or alarm_type_name or the clean alarm_name itself
    alarm_type = (
        str(raw.get("alarm_type_name") or "").strip()
        or (f"FAULT_{raw['fault_id']}" if raw.get("fault_id") else None)
        or name
    )

    # 2. Family: group_name or group_id
    group_name = str(raw.get("group_name") or "").strip()
    if not group_name and raw.get("group_id"):
        group_name = f"GROUP_{raw['group_id']}"
    family = group_name or "GENERAL_ALARM"

    # 3. Category: network_class_name or monitor_type_name
    category = (
        str(raw.get("network_class_name") or "").strip()
        or str(raw.get("monitor_type_name") or "").strip()
        or "NETWORK"
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
    """Build a HistoricalTaxonomy instance for H and T_delay evidence models."""
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

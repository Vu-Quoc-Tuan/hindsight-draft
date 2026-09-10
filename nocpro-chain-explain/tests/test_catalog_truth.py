"""Truth-in-advertising tests for the catalog registry."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from nocpro_api.catalog import _CATALOG, _resolve_preset_path


def test_catalog_file_backed_items_count_truth():
    """Declared alarm_count and chain_count in CATALOG must strictly match payload counts."""
    assert len(_CATALOG) == 12, "Catalog must contain all 12 presets"

    tested_count = 0
    for item in _CATALOG:
        target_path = _resolve_preset_path(item)
        assert target_path.is_file(), f"File for catalog item {item.snapshot_id} must exist at {target_path}"

        payload = json.loads(target_path.read_text(encoding="utf-8"))
        actual_alarms = len(payload.get("alarms", []))
        actual_chains = len(payload.get("chains", []))

        assert item.alarm_count == actual_alarms, (
            f"Catalog mismatch for {item.snapshot_id}: declared alarm_count={item.alarm_count}, "
            f"actual={actual_alarms} in {item.file_path}"
        )
        assert item.chain_count == actual_chains, (
            f"Catalog mismatch for {item.snapshot_id}: declared chain_count={item.chain_count}, "
            f"actual={actual_chains} in {item.file_path}"
        )
        tested_count += 1

    assert tested_count == 12, f"Expected 12 file-backed catalog items tested, got {tested_count}"


def test_catalog_preset_availability_reporting():
    """Verify list_catalog_presets includes truth-telling availability indicators."""
    from nocpro_api.catalog import CatalogItem, check_item_availability, list_catalog_presets

    presets = list_catalog_presets()
    assert len(presets) > 0

    for p in presets:
        assert "available" in p
        assert isinstance(p["available"], bool)
        if not p["available"]:
            assert p["unavailable_reason"] is not None

    # Test unavailable fixture detection
    missing_item = CatalogItem(
        snapshot_id="nonexistent_test",
        name="Missing Item",
        profile="ALARM_ONLY",
        alarm_count=10,
        chain_count=1,
        description="Nonexistent",
        badge="Test",
        file_path="does/not/exist.json",
    )
    avail, reason = check_item_availability(missing_item)
    assert avail is False
    assert "not found" in reason


def test_all_catalog_presets_conform_to_input_contract_v1():
    """All 12 presets in the catalog must strictly pass canonical Input Contract validation."""
    from nocpro_api.workspace import load_validated_package

    assert len(_CATALOG) == 12
    for item in _CATALOG:
        target_path = _resolve_preset_path(item)
        assert target_path.is_file()
        payload = json.loads(target_path.read_text(encoding="utf-8"))
        pkg = load_validated_package(payload)
        assert pkg.snapshot.snapshot_id is not None
        assert len(pkg.alarms) == item.alarm_count


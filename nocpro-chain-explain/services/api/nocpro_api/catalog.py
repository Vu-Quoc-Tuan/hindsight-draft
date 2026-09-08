"""Preset snapshot catalog and loaders categorized by topology profile."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from nocpro_mock.config import MockConfig
from nocpro_mock.contract import package_to_dict
from nocpro_mock.replay.snapshot import build_real_replay_snapshot

ProfileKind = Literal["IP_NETWORK", "IT_SERVICES", "ALARM_ONLY"]


@dataclass(frozen=True)
class CatalogItem:
    snapshot_id: str
    name: str
    profile: ProfileKind
    alarm_count: int
    chain_count: int
    description: str
    badge: str
    file_path: str | None = None
    replay_csv: str | None = None


_REPO_ROOT = Path(__file__).resolve().parents[4]
_MOCK_ROOT = Path(os.environ.get("NOCPRO_MOCK_ROOT", str(_REPO_ROOT / "nocpro-mock")))

_CATALOG: list[CatalogItem] = [
    # 1. IP Network
    CatalogItem(
        snapshot_id="real_alarm_ip_demo",
        name="IP Network Replay (500 Alarms)",
        profile="IP_NETWORK",
        alarm_count=500,
        chain_count=258,
        description="Observed IP alarms mapped to topoIP.csv router/switch adjacency graph.",
        badge="Real Replay",
        replay_csv="datasets/raw/alarm/alarmIP.csv",
    ),
    CatalogItem(
        snapshot_id="real_alarm_evolution_v1_snap_002",
        name="IP Network Evolution - Step 2",
        profile="IP_NETWORK",
        alarm_count=29,
        chain_count=17,
        description="Temporal sliding window step 2 of IP network alarm progression.",
        badge="Evolution",
        file_path="datasets/generated/real_ip_evolution_sample/snapshot_002.json",
    ),
    CatalogItem(
        snapshot_id="real_alarm_evolution_v1_snap_001",
        name="IP Network Evolution - Step 1",
        profile="IP_NETWORK",
        alarm_count=21,
        chain_count=11,
        description="Temporal sliding window step 1 of IP network alarm progression.",
        badge="Evolution",
        file_path="datasets/generated/real_ip_evolution_sample/snapshot_001.json",
    ),
    CatalogItem(
        snapshot_id="real_alarm_evolution_v1_snap_000",
        name="IP Network Evolution - Step 0",
        profile="IP_NETWORK",
        alarm_count=1,
        chain_count=1,
        description="Initial seed single-alarm snapshot for IP network evolution.",
        badge="Evolution",
        file_path="datasets/generated/real_ip_evolution_sample/snapshot_000.json",
    ),
    # 2. IT Services
    CatalogItem(
        snapshot_id="real_alarm_it_demo",
        name="IT Services Replay (500 Alarms)",
        profile="IT_SERVICES",
        alarm_count=500,
        chain_count=226,
        description="Observed IT alarms with directed source relations to microservice topology.",
        badge="Real Replay",
        replay_csv="datasets/raw/alarm/alarmIT.csv",
    ),
    CatalogItem(
        snapshot_id="synthetic_temporal_topology_v1:snapshot_003",
        name="IT Services Temporal - Step 3",
        profile="IT_SERVICES",
        alarm_count=4,
        chain_count=2,
        description="Directed service dependency progression across microservice components.",
        badge="Synthetic",
        file_path="docs/examples/synthetic/temporal_topology/snapshot_003.json",
    ),
    CatalogItem(
        snapshot_id="synthetic_temporal_topology_v1:snapshot_005",
        name="IT Services Temporal - Step 5",
        profile="IT_SERVICES",
        alarm_count=3,
        chain_count=1,
        description="Consolidated cascade scenario in synthetic temporal service topology.",
        badge="Synthetic",
        file_path="docs/examples/synthetic/temporal_topology/snapshot_005.json",
    ),
    CatalogItem(
        snapshot_id="synthetic_temporal_topology_v1:snapshot_000",
        name="IT Services Temporal - Step 0",
        profile="IT_SERVICES",
        alarm_count=2,
        chain_count=1,
        description="Root trigger alarm on IT upstream service node.",
        badge="Synthetic",
        file_path="docs/examples/synthetic/temporal_topology/snapshot_000.json",
    ),
    # 3. Alarm Only
    CatalogItem(
        snapshot_id="real_alarm_20260907_demo",
        name="Alarm Only Replay (500 Alarms)",
        profile="ALARM_ONLY",
        alarm_count=500,
        chain_count=251,
        description="500 observed production alarms from alarm_data.csv (251 distinct chains).",
        badge="Real Replay",
        replay_csv="datasets/raw/alarm/alarm_data.csv",
    ),
    CatalogItem(
        snapshot_id="synthetic_counterfactual_move_v1:snapshot_000",
        name="Counterfactual Move Reference",
        profile="ALARM_ONLY",
        alarm_count=18,
        chain_count=2,
        description="Controlled scenario evaluating cross-chain member reassignment (MOVE_MEMBER).",
        badge="Synthetic",
        file_path="docs/examples/synthetic/counterfactual_move/snapshot_000.json",
    ),
    CatalogItem(
        snapshot_id="synthetic_counterfactual_split_v1:snapshot_000",
        name="Counterfactual Split Reference",
        profile="ALARM_ONLY",
        alarm_count=16,
        chain_count=1,
        description="Controlled synthetic scenario evaluating cut boundary split hypothesis.",
        badge="Synthetic",
        file_path="docs/examples/synthetic/counterfactual_split/snapshot_000.json",
    ),
    CatalogItem(
        snapshot_id="synthetic_counterfactual_merge_v1:snapshot_000",
        name="Counterfactual Merge Reference",
        profile="ALARM_ONLY",
        alarm_count=16,
        chain_count=2,
        description="Controlled synthetic scenario evaluating multi-chain merge hypothesis.",
        badge="Synthetic",
        file_path="docs/examples/synthetic/counterfactual_merge/snapshot_000.json",
    ),
]


def list_catalog_presets() -> list[dict[str, Any]]:
    return [
        {
            "snapshot_id": item.snapshot_id,
            "name": item.name,
            "profile": item.profile,
            "alarm_count": item.alarm_count,
            "chain_count": item.chain_count,
            "description": item.description,
            "badge": item.badge,
        }
        for item in _CATALOG
    ]


def load_preset_payload(snapshot_id: str) -> tuple[dict[str, Any], ProfileKind]:
    item = next((c for c in _CATALOG if c.snapshot_id == snapshot_id), None)
    if item is None:
        raise ValueError(f"Unknown preset snapshot_id: {snapshot_id!r}")

    if item.file_path:
        full_path = _MOCK_ROOT / item.file_path
        if not full_path.exists():
            raise FileNotFoundError(f"Preset file not found: {full_path}")
        return json.loads(full_path.read_text(encoding="utf-8")), item.profile

    if item.replay_csv:
        csv_path = _MOCK_ROOT / item.replay_csv
        if not csv_path.exists():
            raise FileNotFoundError(f"Replay CSV not found: {csv_path}")
        pkg = build_real_replay_snapshot(
            config=MockConfig(),
            alarm_csv_path=str(csv_path),
            snapshot_id=item.snapshot_id,
            limit=500,
        )
        return package_to_dict(pkg), item.profile

    raise ValueError(f"Catalog item {snapshot_id} has neither file_path nor replay_csv")

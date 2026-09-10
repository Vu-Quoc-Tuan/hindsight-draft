from __future__ import annotations

from pathlib import Path
import sys
import pytest

MOCK_ROOT = Path(__file__).resolve().parents[2] / "nocpro-mock"
MOCK_SRC = MOCK_ROOT / "src"
if str(MOCK_SRC) not in sys.path:
    sys.path.insert(0, str(MOCK_SRC))

from nocpro_mock.config import MockConfig
from nocpro_mock.contract import canonical_topology_version
from nocpro_mock.producer.kafka_topology import (
    build_ip_topology_payload,
    build_it_topology_payload,
)
from nocpro_mock.replay.snapshot import build_real_replay_snapshot

ALARM_IP_CSV = MOCK_ROOT / "datasets/raw/alarm/alarmIP.csv"
TOPO_IP_CSV = MOCK_ROOT / "datasets/raw/topo/topoIP.csv"
TOPO_IT_DIR = MOCK_ROOT / "datasets/raw/topo/topoIT"


def test_ip_snapshot_topology_ref_matches_published_topology_version():
    """Verify snapshot replay and topology publisher produce the identical IP version."""
    if not ALARM_IP_CSV.is_file() or not TOPO_IP_CSV.is_file():
        pytest.skip("Real IP data files not present")

    config = MockConfig(topo_ip_enabled=True)
    snapshot = build_real_replay_snapshot(
        alarm_csv_path=ALARM_IP_CSV,
        config=config,
        snapshot_id="test_cross_repo_ip",
        topo_ip_path=TOPO_IP_CSV,
        limit=10,
    )

    ip_payload = build_ip_topology_payload(TOPO_IP_CSV)

    assert snapshot.snapshot.topology_ref is not None
    # Cross-repository version equality invariant
    assert snapshot.snapshot.topology_ref.topology_version == ip_payload["topology_version"]
    assert ip_payload["topology_version"].startswith("ip-")
    assert len(ip_payload["topology_version"]) == 35  # "ip-" + 32 chars

    # Snapshot slimming invariant: snapshot must not carry full nodes/edges
    assert len(snapshot.topology.nodes) == 0
    assert len(snapshot.topology.edges) == 0
    assert len(snapshot.topology.mappings) > 0


def test_it_snapshot_topology_ref_matches_published_topology_version():
    """Verify snapshot replay and topology publisher produce the identical IT version."""
    if not ALARM_IP_CSV.is_file() or not TOPO_IT_DIR.is_dir():
        pytest.skip("Real IT data files not present")

    config = MockConfig(topo_it_enabled=True)
    snapshot = build_real_replay_snapshot(
        alarm_csv_path=ALARM_IP_CSV,
        config=config,
        snapshot_id="test_cross_repo_it",
        topo_it_dir=TOPO_IT_DIR,
        limit=10,
    )

    it_payload = build_it_topology_payload(TOPO_IT_DIR)

    assert snapshot.snapshot.topology_ref is not None
    # Cross-repository version equality invariant
    assert snapshot.snapshot.topology_ref.topology_version == it_payload["topology_version"]
    assert it_payload["topology_version"].startswith("it-")
    assert len(it_payload["topology_version"]) == 35  # "it-" + 32 chars

    # Snapshot slimming invariant: snapshot must not carry full nodes/edges
    assert len(snapshot.topology.nodes) == 0
    assert len(snapshot.topology.edges) == 0


def test_canonical_topology_version_deterministic_contract():
    """Verify canonical_topology_version strips sha256 prefix and limits length to 32 hex chars."""
    raw_hash = "sha256:5caa40c6a9e7ccc1590ae5469fbff66844fab5db5a7b72cf1fa8d8fc27227c05"
    ip_ver = canonical_topology_version("IP_NETWORK", raw_hash)
    it_ver = canonical_topology_version("IT_SERVICES", raw_hash)

    assert ip_ver == "ip-5caa40c6a9e7ccc1590ae5469fbff668"
    assert it_ver == "it-5caa40c6a9e7ccc1590ae5469fbff668"
    assert "sha256" not in ip_ver
    assert "sha256" not in it_ver

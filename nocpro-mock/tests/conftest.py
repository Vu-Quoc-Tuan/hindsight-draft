"""Shared test fixtures.

Tests that need the real 680 MB exports are marked ``realdata`` and skip
automatically when the files are absent, so the suite stays runnable anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def _find_candidate_file(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


ALARM_CSV = _find_candidate_file([
    REPO_ROOT / "datasets/raw/alarm/alarm_data.csv",
    REPO_ROOT / "datasets/raw/alarm_data.csv",
])
TOPO_IP_CSV = _find_candidate_file([
    REPO_ROOT / "datasets/raw/topo/topoIP.csv",
    REPO_ROOT / "datasets/raw/topoIP-8zjkidh613ffzdck7jca5j6bdc.csv",
    REPO_ROOT / "datasets/raw/topoIP.csv",
])
GOLDEN_DIR = REPO_ROOT / "docs/examples/golden_2214039"
CAPABILITY_CONFIG = _find_candidate_file([
    REPO_ROOT / "config/mock_capabilities.example.yaml",
    REPO_ROOT / "docs/config/mock_capabilities.example.yaml",
])


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "realdata: requires the real exports in datasets/raw")


@pytest.fixture(scope="session")
def alarm_csv() -> Path:
    if not ALARM_CSV.is_file():
        pytest.skip(f"missing real export: {ALARM_CSV}")
    return ALARM_CSV


@pytest.fixture(scope="session")
def topo_ip_csv() -> Path:
    if not TOPO_IP_CSV.is_file():
        pytest.skip(f"missing real export: {TOPO_IP_CSV}")
    return TOPO_IP_CSV


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    if not GOLDEN_DIR.is_dir():
        pytest.skip(f"missing golden fixture: {GOLDEN_DIR}")
    return GOLDEN_DIR


@pytest.fixture(scope="session")
def config():
    from nocpro_mock.config import load_config

    if CAPABILITY_CONFIG.is_file():
        return load_config(CAPABILITY_CONFIG)
    return load_config()


@pytest.fixture(scope="session")
def topo_ip_device_codes(topo_ip_csv: Path) -> set[str]:
    from nocpro_mock.loaders import TopoIPLoader

    return TopoIPLoader(topo_ip_csv).device_codes()

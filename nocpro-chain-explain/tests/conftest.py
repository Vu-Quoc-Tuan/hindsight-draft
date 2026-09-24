"""Test configuration for nocpro-chain-explain."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
#: ``services/analysis-worker`` contains a hyphen, so it cannot be imported as a
#: package path. Adding it to sys.path lets its subpackages import normally.
ANALYSIS_WORKER = REPO_ROOT / "services" / "analysis-worker"
API_SERVICE = REPO_ROOT / "services" / "api"

for path in (REPO_ROOT, ANALYSIS_WORKER, API_SERVICE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

MOCK_ROOT = REPO_ROOT.parent / "nocpro-mock"
GOLDEN_FIXTURE_DIR = MOCK_ROOT / "docs/examples/golden_2214039"
SYNTHETIC_DIR = MOCK_ROOT / "docs/examples/synthetic"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "realdata: requires the real exports in nocpro-mock/datasets/raw"
    )


@pytest.fixture(autouse=True)
def disable_automatic_quality_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unrelated unit tests from draining background Counterfactual queues."""
    monkeypatch.setenv("NOCPRO_AUTO_CHAIN_QUALITY", "false")


@pytest.fixture(scope="session")
def mock_root() -> Path:
    if not MOCK_ROOT.is_dir():
        pytest.skip(f"sibling nocpro-mock repo not found at {MOCK_ROOT}")
    return MOCK_ROOT

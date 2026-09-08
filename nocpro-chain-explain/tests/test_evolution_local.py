import json
from pathlib import Path
import pytest
from nocpro_api.workspace import Workspace
from libs.contracts import load_validated_package


@pytest.mark.anyio
async def test_local_evolution_serves_verified_lineage_without_database():
    mock_dir = Path(__file__).resolve().parents[2] / "nocpro-mock" / "datasets" / "generated" / "real_ip_evolution_sample"
    if not (mock_dir / "snapshot_002.json").exists():
        pytest.skip("Evolution sample fixture not present")

    ws = Workspace()
    with open(mock_dir / "snapshot_002.json", encoding="utf-8") as f:
        pkg_data = json.load(f)

    pkg = load_validated_package(pkg_data)
    # Activate snapshot 002
    ws.activate_snapshot(pkg, ws.precompute)

    # In local mode without database, chain 6331493 must resolve to real available lineage
    evolution = await ws.evolution("6331493")
    assert evolution.status == "AVAILABLE"
    assert evolution.sequence_status == "VERIFIED"
    assert len(evolution.nodes) == 3
    assert len(evolution.edges) == 2
    assert evolution.edges[0].event_type == "CONTINUE"
    assert evolution.edges[1].event_type == "CONTINUE"

    # Lineage by chain should be populated in memory
    assert ws.lineage_by_chain.get("6331493") is not None

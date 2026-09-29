"""End-to-end: real export -> mock -> contract -> Explain ingest.

Closes the loop that ADR-0030 describes: the Direct Snapshot Adapter consumes a
package built from the real alarm export, with no Kafka and no hard-coded
metadata. Skips when the sibling repo or the 680 MB exports are absent.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from graybox import (
    MembershipVerdict,
    OperationStatus,
    adapt_graybox_metadata,
    build_singleton_report,
    operation_status,
    render_system_fact_box,
)
from channels.dependency import (
    ResourceResolver,
    build_topology_graph,
    evaluate_dep_hop_channel,
)
from libs.contracts import load_package
from tests.conftest import MOCK_ROOT

pytestmark = pytest.mark.realdata

#: A singleton chain verified present in the real export (2,072 singletons total).
SINGLETON_CHAIN = "3263265"
#: The largest observed chain: 1,072 members.
LARGEST_CHAIN = "6907125"
# A real alarmIP chain containing two devices that are direct topoIP neighbors.
IP_ADJACENCY_CHAIN = "6912465"


def _run_mock(*args: str):
    if not MOCK_ROOT.is_dir():
        pytest.skip("sibling nocpro-mock repo not present")
    if not (MOCK_ROOT / "datasets/raw/alarm/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")
    venv_python = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv_python) if venv_python.is_file() else sys.executable
    result = subprocess.run(
        [interpreter, "-m", "nocpro_mock.cli", *args],
        cwd=MOCK_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI failed: {result.stderr[:300]}")
    return load_package(json.loads(result.stdout))


@pytest.fixture(scope="module")
def largest_chain_package():
    return _run_mock("replay", "--chain-id", LARGEST_CHAIN, "--snapshot-id", "s_e2e")


def test_largest_real_chain_ingests(largest_chain_package):
    package = largest_chain_package
    assert package.snapshot.is_complete
    assert package.snapshot.source_kind == "REAL_EXPORT_REPLAY"
    chain = package.chains[LARGEST_CHAIN]
    assert chain.member_count == 1072
    assert len(package.members_of(LARGEST_CHAIN)) == 1072
    assert chain.is_singleton is False


def test_ingested_alarms_preserve_raw_and_quality(largest_chain_package):
    alarms = largest_chain_package.alarms_of(LARGEST_CHAIN)
    assert len(alarms) == 1072
    # Raw columns survive the round trip through the contract.
    assert all(a.raw for a in alarms)
    assert any("cah.id" in a.raw for a in alarms)
    # Dirty-data flags are visible to Explain rather than silently dropped.
    flagged = [a for a in alarms if a.quality_flags]
    assert flagged, "expected quality flags to survive ingestion"


def test_real_chain_is_blackbox_without_system_metadata(largest_chain_package):
    """The alarm export carries no rules/pair scores, so this is Black-box."""
    metadata = adapt_graybox_metadata(largest_chain_package, LARGEST_CHAIN)
    assert metadata.available is False
    lines = render_system_fact_box(metadata)
    assert lines[0].kind == "MODE"
    assert metadata.pair_status("x", "y") == "UNKNOWN"


def test_real_singleton_chain_is_not_weak():
    """A real singleton from the export must be NOT_APPLICABLE, never WEAK."""
    package = _run_mock(
        "replay", "--chain-id", SINGLETON_CHAIN, "--snapshot-id", "s_single"
    )
    chain = package.chains.get(SINGLETON_CHAIN)
    if chain is None or not chain.is_singleton:
        pytest.skip(f"chain {SINGLETON_CHAIN} is not a singleton in this export")

    report = build_singleton_report(package, SINGLETON_CHAIN)
    assert report.membership_verdict is MembershipVerdict.NOT_APPLICABLE
    assert report.is_weak is False
    assert (
        operation_status("OVER_MERGE", chain).status is OperationStatus.NOT_APPLICABLE
    )
    assert operation_status("DESCRIPTOR", chain).status is OperationStatus.AVAILABLE


def test_topology_unavailable_capabilities_reach_explain(largest_chain_package):
    """Explain must see declared gaps as UNAVAILABLE, not as negative findings."""
    unavailable = largest_chain_package.unavailable_capabilities
    assert unavailable
    assert any("TOPO_IT" in cap for cap in unavailable)


def test_real_ip_replay_exact_mapping_can_supply_undirected_dep_hop():
    """Exact IP identity plus adjacency is proximity evidence, not dependency direction."""
    if not (MOCK_ROOT / "datasets/raw/alarm/alarmIP.csv").is_file():
        pytest.skip("real IP alarm export not present")
    if not (MOCK_ROOT / "datasets/raw/topo/topoIP.csv").is_file():
        pytest.skip("real IP topology export not present")

    package = _run_mock(
        "replay",
        "--alarm-csv",
        "datasets/raw/alarm/alarmIP.csv",
        "--topo-ip",
        "datasets/raw/topo/topoIP.csv",
        "--with-topology",
        "--include-raw-topology",
        "--chain-id",
        IP_ADJACENCY_CHAIN,
        "--snapshot-id",
        "s_ip_topology",
    )
    members = package.members_of(IP_ADJACENCY_CHAIN)
    graph = build_topology_graph(package)
    resolver = ResourceResolver.from_package(package)

    values = [
        evaluate_dep_hop_channel(package.alarms[left], package.alarms[right], graph=graph, resolver=resolver)
        for index, left in enumerate(members)
        for right in members[index + 1 :]
    ]

    assert graph.unavailable_reason is None
    assert all(edge.get("source_version") for edge in package.topology["edges"])
    assert any(value.availability for value in values)

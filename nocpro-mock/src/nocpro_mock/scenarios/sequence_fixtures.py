"""Definitions for the shipped history/evolution sequence fixtures.

Membership per snapshot lives here so the JSON files under
``docs/examples/synthetic/*/`` are reproducible from source rather than
hand-maintained. They mirror the corresponding ``expected_assertions.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass

FAMILY_A = "SYN-FAMILY-A"
FAMILY_B = "SYN-FAMILY-B"


@dataclass(frozen=True)
class SequenceFixture:
    scenario_id: str
    directory: str
    #: One ``chain_id -> [alarm_id]`` mapping per snapshot, in sequence order.
    snapshots: tuple[dict[str, list[str]], ...]
    alarm_families: dict[str, str]
    topology_scenario_file: str | None = None
    generator_version: str | None = None


@dataclass(frozen=True)
class CounterfactualFixture:
    scenario_id: str
    directory: str
    chain_id: str
    members: tuple[str, ...]
    alarm_profiles: dict[str, dict[str, object]]
    truth_partition: tuple[tuple[str, tuple[str, ...]], ...]
    mutation: str


#: History: FAMILY-A and FAMILY-B are grouped together in the three history
#: snapshots, then appear again in the target. Support therefore comes only from
#: history, never from the target itself.
HISTORY_POSITIVE_LIFT = SequenceFixture(
    scenario_id="history_positive_lift_v1",
    directory="history_positive_lift",
    snapshots=(
        {"SYN-CHAIN-H0": ["SYN-ALARM-A1", "SYN-ALARM-B1"]},
        {"SYN-CHAIN-H1": ["SYN-ALARM-A2", "SYN-ALARM-B2"]},
        {"SYN-CHAIN-H2": ["SYN-ALARM-A3", "SYN-ALARM-B3"]},
        # Target snapshot.
        {"SYN-CHAIN-T": ["SYN-ALARM-A4", "SYN-ALARM-B4"]},
    ),
    alarm_families={
        "SYN-ALARM-A1": FAMILY_A,
        "SYN-ALARM-A2": FAMILY_A,
        "SYN-ALARM-A3": FAMILY_A,
        "SYN-ALARM-A4": FAMILY_A,
        "SYN-ALARM-B1": FAMILY_B,
        "SYN-ALARM-B2": FAMILY_B,
        "SYN-ALARM-B3": FAMILY_B,
        "SYN-ALARM-B4": FAMILY_B,
    },
)

#: Evolution: one chain splits into two, then merges back. Chain IDs differ at
#: every step so lineage must be derived from membership (ADR-0020).
EVOLUTION_SPLIT_MERGE = SequenceFixture(
    scenario_id="split_then_merge_v1",
    directory="evolution_split_merge",
    snapshots=(
        {
            "SYN-CHAIN-A": [
                "SYN-ALARM-01",
                "SYN-ALARM-02",
                "SYN-ALARM-03",
                "SYN-ALARM-04",
            ]
        },
        {
            "SYN-CHAIN-B": ["SYN-ALARM-01", "SYN-ALARM-02"],
            "SYN-CHAIN-C": ["SYN-ALARM-03", "SYN-ALARM-04"],
        },
        {
            "SYN-CHAIN-D": [
                "SYN-ALARM-01",
                "SYN-ALARM-02",
                "SYN-ALARM-03",
                "SYN-ALARM-04",
            ]
        },
    ),
    alarm_families={},
)


INTEGRATED_TEMPORAL_TOPOLOGY = SequenceFixture(
    scenario_id="synthetic_temporal_topology_v1",
    directory="temporal_topology",
    snapshots=(
        {"SYN-CHAIN-T0": ["SYN-DEVICE-01", "SYN-DEVICE-02"]},
        {"SYN-CHAIN-T1": ["SYN-DEVICE-01", "SYN-DEVICE-02"]},
        {
            "SYN-CHAIN-T2": [
                "SYN-DEVICE-01",
                "SYN-DEVICE-02",
                "SYN-DEVICE-03",
                "SYN-DEVICE-04",
            ]
        },
        {
            "SYN-CHAIN-T3A": ["SYN-DEVICE-01", "SYN-DEVICE-02"],
            "SYN-CHAIN-T3B": ["SYN-DEVICE-03", "SYN-DEVICE-04"],
        },
        {
            "SYN-CHAIN-T4": [
                "SYN-DEVICE-01",
                "SYN-DEVICE-02",
                "SYN-DEVICE-03",
                "SYN-DEVICE-04",
            ]
        },
        {
            "SYN-CHAIN-T5": [
                "SYN-DEVICE-01",
                "SYN-DEVICE-02",
                "SYN-DEVICE-03",
            ]
        },
    ),
    alarm_families={},
    topology_scenario_file="scenario.yaml",
    generator_version="mockgen-integrated-v1",
)


SEQUENCE_FIXTURES = (
    HISTORY_POSITIVE_LIFT,
    EVOLUTION_SPLIT_MERGE,
    INTEGRATED_TEMPORAL_TOPOLOGY,
)


def _block_profiles(prefix: str, *, start: int, device: str) -> dict[str, dict[str, object]]:
    return {
        f"SYN-{prefix}-{index:02d}": {
            "device_code": device,
            "node_reference": f"SYN-REF-{prefix}-{1 if index <= 4 else 2}",
            "start_offset_seconds": start + index,
        }
        for index in range(1, 9)
    }


_REMOVE_CORE = _block_profiles("REMOVE-CORE", start=0, device="SYN-DEVICE-REMOVE-CORE")
COUNTERFACTUAL_REMOVE = CounterfactualFixture(
    scenario_id="synthetic_counterfactual_remove_v1",
    directory="counterfactual_remove",
    chain_id="SYN-CHAIN-REMOVE-MUTATED",
    members=(*_REMOVE_CORE, "SYN-REMOVE-EXTRA"),
    alarm_profiles={
        **_REMOVE_CORE,
        "SYN-REMOVE-EXTRA": {
            "device_code": "SYN-DEVICE-REMOVE-EXTRA",
            "node_reference": "SYN-REF-REMOVE-EXTRA",
            "start_offset_seconds": 600,
        },
    },
    truth_partition=(
        ("SYN-CHAIN-REMOVE-TRUTH", tuple(_REMOVE_CORE)),
        ("SYN-CHAIN-REMOVE-EXTRA", ("SYN-REMOVE-EXTRA",)),
    ),
    mutation="EXTRA_MEMBER",
)

_SPLIT_A = _block_profiles("SPLIT-A", start=0, device="SYN-DEVICE-SPLIT-A")
_SPLIT_B = _block_profiles("SPLIT-B", start=600, device="SYN-DEVICE-SPLIT-B")
COUNTERFACTUAL_SPLIT = CounterfactualFixture(
    scenario_id="synthetic_counterfactual_split_v1",
    directory="counterfactual_split",
    chain_id="SYN-CHAIN-SPLIT-MUTATED",
    members=(*_SPLIT_A, *_SPLIT_B),
    alarm_profiles={**_SPLIT_A, **_SPLIT_B},
    truth_partition=(
        ("SYN-CHAIN-SPLIT-A", tuple(_SPLIT_A)),
        ("SYN-CHAIN-SPLIT-B", tuple(_SPLIT_B)),
    ),
    mutation="OVER_MERGE",
)

COUNTERFACTUAL_FIXTURES = (COUNTERFACTUAL_REMOVE, COUNTERFACTUAL_SPLIT)

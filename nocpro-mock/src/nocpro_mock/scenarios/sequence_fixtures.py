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
    #: Explicit per-alarm profile is needed only when a temporal scenario must
    #: preserve a known directed delay distribution across snapshots.
    alarm_profiles: dict[str, dict[str, object]] | None = None
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
    additional_chains: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def snapshot_chains(self) -> dict[str, list[str]]:
        """Canonical synthetic partition before the review proposal."""
        return {
            self.chain_id: list(self.members),
            **{
                chain_id: list(chain_members)
                for chain_id, chain_members in self.additional_chains
            },
        }


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


# Synthetic-only source material for Explain T_delay.  Authoritative taxonomy
# is deliberately kept in its expected assertion/test adapter, never inferred
# from these alarm names by the canonical Mock contract.
TEMPORAL_DELAY_PATTERNS = SequenceFixture(
    scenario_id="temporal_delay_patterns_v1",
    directory="temporal_delay_patterns",
    snapshots=(
        {"SYN-TD-AB-0": ["SYN-TD-A0", "SYN-TD-B0"], "SYN-TD-CD-0": ["SYN-TD-C0", "SYN-TD-D0"]},
        {"SYN-TD-AB-1": ["SYN-TD-A1", "SYN-TD-B1"], "SYN-TD-CD-1": ["SYN-TD-C1", "SYN-TD-D1"]},
        {"SYN-TD-AB-2": ["SYN-TD-A2", "SYN-TD-B2"]},
        {"SYN-TD-AB-3": ["SYN-TD-A3", "SYN-TD-B3"]},
        # Target: peak-compatible, midpoint, backoff and simultaneous pairs.
        {
            "SYN-TD-PEAK": ["SYN-TD-PEAK-A", "SYN-TD-PEAK-B"],
            "SYN-TD-MID": ["SYN-TD-MID-A", "SYN-TD-MID-B"],
            "SYN-TD-BACKOFF": ["SYN-TD-BACK-C", "SYN-TD-BACK-D"],
            "SYN-TD-REVERSE": ["SYN-TD-REVERSE-B", "SYN-TD-REVERSE-A"],
            "SYN-TD-EQUAL": ["SYN-TD-EQUAL-A", "SYN-TD-EQUAL-B"],
        },
    ),
    alarm_families={},
    alarm_profiles={
        **{f"SYN-TD-A{i}": {"alarm_name": "TD-A", "start_offset_seconds": 0} for i in range(4)},
        **{f"SYN-TD-B{i}": {"alarm_name": "TD-B", "start_offset_seconds": delay} for i, delay in enumerate((2, 3, 99, 101))},
        **{f"SYN-TD-C{i}": {"alarm_name": "TD-C", "start_offset_seconds": 0} for i in range(2)},
        **{f"SYN-TD-D{i}": {"alarm_name": "TD-D", "start_offset_seconds": delay} for i, delay in enumerate((2, 3))},
        "SYN-TD-PEAK-A": {"alarm_name": "TD-A", "start_offset_seconds": 0},
        "SYN-TD-PEAK-B": {"alarm_name": "TD-B", "start_offset_seconds": 2},
        "SYN-TD-MID-A": {"alarm_name": "TD-A", "start_offset_seconds": 0},
        "SYN-TD-MID-B": {"alarm_name": "TD-B", "start_offset_seconds": 50},
        "SYN-TD-BACK-C": {"alarm_name": "TD-C", "start_offset_seconds": 0},
        "SYN-TD-BACK-D": {"alarm_name": "TD-D", "start_offset_seconds": 2},
        "SYN-TD-REVERSE-B": {"alarm_name": "TD-B", "start_offset_seconds": 0},
        "SYN-TD-REVERSE-A": {"alarm_name": "TD-A", "start_offset_seconds": 2},
        "SYN-TD-EQUAL-A": {"alarm_name": "TD-A", "start_offset_seconds": 0},
        "SYN-TD-EQUAL-B": {"alarm_name": "TD-B", "start_offset_seconds": 0},
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
    TEMPORAL_DELAY_PATTERNS,
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

_MOVE_SOURCE = _block_profiles(
    "MOVE-SOURCE", start=0, device="SYN-DEVICE-MOVE-SOURCE"
)
_MOVE_TARGET = _block_profiles(
    "MOVE-TARGET", start=600, device="SYN-DEVICE-MOVE-TARGET"
)
COUNTERFACTUAL_MOVE = CounterfactualFixture(
    scenario_id="synthetic_counterfactual_move_v1",
    directory="counterfactual_move",
    chain_id="SYN-CHAIN-MOVE-SOURCE",
    members=(*_MOVE_SOURCE, "SYN-MOVE-MISASSIGNED"),
    alarm_profiles={
        **{
            alarm_id: {
                **profile,
                "alarm_name": (
                    "SYN-MOVE-SOURCE-OUTLIER"
                    if alarm_id == "SYN-MOVE-SOURCE-08"
                    else "SYN-MOVE-SOURCE"
                ),
            }
            for alarm_id, profile in _MOVE_SOURCE.items()
        },
        **{
            alarm_id: {**profile, "alarm_name": "SYN-MOVE-TARGET"}
            for alarm_id, profile in _MOVE_TARGET.items()
        },
        "SYN-MOVE-MISASSIGNED": {
            "device_code": "SYN-DEVICE-MOVE-TARGET",
            "node_reference": "SYN-REF-MOVE-TARGET-1",
            "alarm_name": "SYN-MOVE-TARGET",
            "start_offset_seconds": 605,
        },
    },
    truth_partition=(
        ("SYN-CHAIN-MOVE-SOURCE", tuple(_MOVE_SOURCE)),
        ("SYN-CHAIN-MOVE-TARGET", (*_MOVE_TARGET, "SYN-MOVE-MISASSIGNED")),
    ),
    mutation="MISASSIGNED_MEMBER",
    additional_chains=(("SYN-CHAIN-MOVE-TARGET", tuple(_MOVE_TARGET)),),
)


def _merge_profiles(
    prefix: str,
    *,
    devices: tuple[str, str],
    locations: tuple[str, str],
    remote_nodes: tuple[str | None, str | None],
    offsets: range,
) -> dict[str, dict[str, object]]:
    """Two reference blocks, with one semantic term shared globally.

    The left chain remains split because its reference/device blocks only share
    semantic evidence. The right chain bridges those blocks through a common
    remote-node and semantic signal, while matching reference/device/site/burst
    values provide exact multi-view cross-chain support. This creates a
    deterministic under-merge fixture without treating
    a blocking relation itself as merge proof.
    """
    return {
        f"SYN-{prefix}-{index:02d}": {
            "device_code": devices[0] if index <= 4 else devices[1],
            "node_reference": "SYN-REF-MERGE-A" if index <= 4 else "SYN-REF-MERGE-B",
            "location_code": locations[0] if index <= 4 else locations[1],
            "remote_node": remote_nodes[0] if index <= 4 else remote_nodes[1],
            "alarm_name": "SYN-MERGE",
            "start_offset_seconds": offsets[index - 1],
        }
        for index in range(1, 9)
    }


_MERGE_LEFT = _merge_profiles(
    "MERGE-LEFT",
    devices=("SYN-DEVICE-MERGE-LEFT-A", "SYN-DEVICE-MERGE-LEFT-B"),
    locations=("SYN-SITE-MERGE-LEFT-A", "SYN-SITE-MERGE-LEFT-B"),
    remote_nodes=(None, None),
    offsets=range(0, 8),
)
_MERGE_RIGHT = _merge_profiles(
    "MERGE-RIGHT",
    devices=("SYN-DEVICE-MERGE-LEFT-A", "SYN-DEVICE-MERGE-LEFT-B"),
    locations=("SYN-SITE-MERGE-LEFT-A", "SYN-SITE-MERGE-LEFT-B"),
    remote_nodes=("SYN-REMOTE-MERGE-RIGHT", "SYN-REMOTE-MERGE-RIGHT"),
    offsets=range(20, 28),
)
COUNTERFACTUAL_MERGE = CounterfactualFixture(
    scenario_id="synthetic_counterfactual_merge_v1",
    directory="counterfactual_merge",
    chain_id="SYN-CHAIN-MERGE-LEFT",
    members=tuple(_MERGE_LEFT),
    alarm_profiles={**_MERGE_LEFT, **_MERGE_RIGHT},
    truth_partition=(
        ("SYN-CHAIN-MERGE-TRUTH", (*_MERGE_LEFT, *_MERGE_RIGHT)),
    ),
    mutation="UNDER_MERGE",
    additional_chains=(("SYN-CHAIN-MERGE-RIGHT", tuple(_MERGE_RIGHT)),),
)

COUNTERFACTUAL_FIXTURES = (
    COUNTERFACTUAL_REMOVE,
    COUNTERFACTUAL_SPLIT,
    COUNTERFACTUAL_MOVE,
    COUNTERFACTUAL_MERGE,
)

from __future__ import annotations

import pytest

from contracts.v1 import ContractViolation, SourceKind, parse_package


def _payload() -> dict:
    return {
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": "s-contract",
            "snapshot_version": "1",
            "snapshot_time": "2026-08-29T00:00:00Z",
            "status": "COMPLETE",
            "source": "contract-test",
            "source_kind": "SYNTHETIC_TEST",
            "produced_at": "2026-08-29T00:00:01Z",
        },
        "alarms": [
            {
                "alarm_id": "a1",
                "snapshot_id": "s-contract",
                "source_kind": "SYNTHETIC_TEST",
                "provenance_class": "SYSTEM_FACT",
                "raw": {},
            }
        ],
        "chains": [
            {
                "chain_id": "c1",
                "snapshot_id": "s-contract",
                "member_count": 1,
                "source_kind": "SYNTHETIC_TEST",
                "provenance_class": "SYSTEM_FACT",
            }
        ],
        "memberships": [
            {
                "chain_id": "c1",
                "alarm_id": "a1",
                "snapshot_id": "s-contract",
                "source_kind": "SYNTHETIC_TEST",
            }
        ],
    }


def test_parse_package_builds_typed_contract_and_runs_full_validation():
    package = parse_package(_payload())

    assert package.snapshot.source_kind is SourceKind.SYNTHETIC_TEST
    assert package.alarms[0].source_kind is SourceKind.SYNTHETIC_TEST


@pytest.mark.parametrize(
    ("field", "value"),
    [("snapshot_time", ""), ("produced_at", ""), ("source_kind", "NOT_A_KIND")],
)
def test_parse_package_rejects_values_the_analysis_loader_used_to_accept(
    field: str, value: str
):
    payload = _payload()
    payload["snapshot"][field] = value

    with pytest.raises(ContractViolation):
        parse_package(payload)


def test_parse_package_rejects_unknown_fields_fail_closed():
    payload = _payload()
    payload["snapshot"]["unexpected"] = "not-in-v1"

    with pytest.raises(ContractViolation, match="unexpected field"):
        parse_package(payload)


def test_topology_derived_records_keep_source_version_separate_from_generator():
    payload = _payload()
    generation = {
        "scenario_id": "synthetic-topology-v1",
        "seed": 42,
        "generator_version": "mockgen-2",
        "generation_rule": "explicit topology fixture",
    }
    payload["topology"] = {
        "active_paths": [
            {
                "path_id": "SYN-PATH-1",
                "resource_id": "SYN-A",
                "nodes": ["SYN-A", "SYN-B"],
                "source_id": "synthetic-topology",
                "source_version": "syn-topo-v7",
                "source_kind": "SYNTHETIC_TEST",
                "generation": generation,
            }
        ],
        "failure_domains": [
            {
                "failure_domain_id": "SYN-SRLG-1",
                "domain_type": "SRLG",
                "members": ["SYN-A"],
                "source_id": "synthetic-topology",
                "source_version": "syn-topo-v7",
                "source_kind": "SYNTHETIC_TEST",
                "generation": generation,
            }
        ],
    }

    package = parse_package(payload)

    assert package.topology.active_paths[0].source_version == "syn-topo-v7"
    assert package.topology.failure_domains[0].source_version == "syn-topo-v7"
    assert package.topology.active_paths[0].generation.generator_version == "mockgen-2"


def test_all_contract_models_have_resolvable_type_hints():
    import inspect
    import typing
    import contracts.v1.models as models_mod

    for name, cls in inspect.getmembers(models_mod, inspect.isclass):
        if cls.__module__ == models_mod.__name__:
            hints = typing.get_type_hints(cls)
            assert isinstance(hints, dict)

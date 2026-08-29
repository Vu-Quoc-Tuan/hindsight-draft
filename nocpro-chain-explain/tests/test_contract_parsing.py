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

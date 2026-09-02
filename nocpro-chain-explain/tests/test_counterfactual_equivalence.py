from __future__ import annotations

from tier2.counterfactual import PartitionDelta, apply_partition_delta
from tests.test_counterfactual_evaluator import _package


def test_affected_partition_view_matches_manual_full_partition_rebuild() -> None:
    package = _package()
    delta = PartitionDelta(
        before=(("C", ("A", "B", "C", "X")),),
        after=(("C", ("A", "B", "C")), ("C::singleton::X", ("X",))),
    )

    affected = apply_partition_delta(package, delta)

    assert affected.memberships == {
        "U": ["Z"],
        "C": ["A", "B", "C"],
        "C::singleton::X": ["X"],
    }
    assert affected.chains["U"] is package.chains["U"]
    assert affected.alarms is package.alarms
    assert set(affected.alarms) == set(package.alarms)
    assert set(alarm_id for members in affected.memberships.values() for alarm_id in members) == set(package.alarms)


def test_partition_view_does_not_mutate_source_package() -> None:
    package = _package()
    original_memberships = {key: list(value) for key, value in package.memberships.items()}
    apply_partition_delta(
        package,
        PartitionDelta(
            before=(("C", ("A", "B", "C", "X")),),
            after=(("C-left", ("A", "B")), ("C-right", ("C", "X"))),
        ),
    )
    assert package.memberships == original_memberships

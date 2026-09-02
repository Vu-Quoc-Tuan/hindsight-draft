from __future__ import annotations

from dataclasses import replace
import tier2.counterfactual.evaluator as evaluator_module
from audit import StructuralRole, StructuralRoleResult
from configuration import CalibrationStatus, CounterfactualConfig
from libs.contracts import load_package
from tier2.counterfactual import (
    CandidateStatus,
    CounterfactualCandidate,
    EditCost,
    MetricValue,
    MetricVector,
    Operation,
    PartitionDelta,
    evaluate_candidate,
    select_frontier,
)


CONFIG = CounterfactualConfig(
    config_version="synthetic-v1",
    calibration_status=CalibrationStatus.SYNTHETIC_ONLY,
    max_chain_members=100,
    max_remove_candidates=10,
    max_split_candidates=10,
    max_recommendations=10,
    membership_support_below=0.3,
    representativeness_below=0.3,
    adverse_margin_below=0.0,
    minimum_membership_improvement=0.05,
    minimum_coverage_improvement=0.05,
    minimum_conductance_improvement=0.05,
    pareto_tolerance=0.0,
)


def _package():
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "fixture",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-01-01T00:00:00",
            },
            "alarms": [
                {"alarm_id": alarm_id, "snapshot_id": "s1", "raw": {}}
                for alarm_id in ("A", "B", "C", "X", "Z")
            ],
            "chains": [
                {"chain_id": "C", "snapshot_id": "s1", "member_count": 4},
                {"chain_id": "U", "snapshot_id": "s1", "member_count": 1},
            ],
            "memberships": [
                {"chain_id": "C", "alarm_id": alarm_id, "snapshot_id": "s1"}
                for alarm_id in ("A", "B", "C", "X")
            ]
            + [{"chain_id": "U", "alarm_id": "Z", "snapshot_id": "s1"}],
        }
    )


def _candidate(candidate_id="remove-X"):
    return CounterfactualCandidate(
        candidate_id=candidate_id,
        operation=Operation.REMOVE_MEMBER,
        partition_delta=PartitionDelta(
            before=(("C", ("A", "B", "C", "X")),),
            after=(("C", ("A", "B", "C")), ("C::singleton::X", ("X",))),
        ),
        edit_cost=EditCost(1, 1, 4),
        source_ref="test",
        member_ids=("X",),
    )


def _move_candidate(candidate_id="move-X"):
    return CounterfactualCandidate(
        candidate_id=candidate_id,
        operation=Operation.MOVE_MEMBER,
        partition_delta=PartitionDelta(
            before=(
                ("C", ("A", "B", "C", "X")),
                ("U", ("Z",)),
            ),
            after=(
                ("C", ("A", "B", "C")),
                ("U", ("X", "Z")),
            ),
        ),
        edit_cost=EditCost(1, 1, 5),
        source_ref="test",
        member_ids=("X",),
        source_chain_id="C",
        target_chain_id="U",
    )


def _metrics(
    *, weak=2, membership=0.2, coverage=0.4, components=2, conductance=0.1,
    severity=1, contradictions=0,
):
    return MetricVector(
        weak_member_count=MetricValue.available(weak),
        minimum_membership_support=MetricValue.available(membership),
        evidence_union_coverage=MetricValue.available(coverage),
        component_count=MetricValue.available(components),
        audit_conductance=MetricValue.available(conductance),
        audit_verdict_severity=MetricValue.available(severity),
        eligible_external_contradiction_count=MetricValue.available(contradictions),
    )


def _computer(before, after):
    def compute(package, chain_ids):
        return after if any("singleton" in chain_id for chain_id in chain_ids) else before

    return compute


def test_missing_metric_is_not_zero() -> None:
    before = _metrics()
    after = replace(
        _metrics(weak=1, membership=0.4, coverage=0.6, components=1, conductance=0.3),
        audit_conductance=MetricValue.unavailable("AUDIT_SKIPPED"),
    )
    result = evaluate_candidate(
        _package(),
        _candidate(),
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_computer(before, after),
    )

    assert result.status is CandidateStatus.HARD_GATE_REJECTED
    assert result.reason == "REQUIRED_METRIC_UNAVAILABLE"


def test_external_contradiction_hard_rejects() -> None:
    before = _metrics()
    after = _metrics(
        weak=1,
        membership=0.4,
        coverage=0.6,
        components=1,
        conductance=0.3,
    )
    result = evaluate_candidate(
        _package(),
        _candidate(),
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_computer(before, after),
        eligible_external_contradiction_count=1,
    )

    assert result.status is CandidateStatus.EXTERNALLY_CONTRADICTED


def test_material_improvement_returns_better_supported() -> None:
    result = evaluate_candidate(
        _package(),
        _candidate(),
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_computer(
            _metrics(),
            _metrics(
                weak=1,
                membership=0.4,
                coverage=0.6,
                components=1,
                conductance=0.3,
                severity=0,
            ),
        ),
    )

    assert result.status is CandidateStatus.BETTER_SUPPORTED
    assert "minimum_membership_support" in result.materially_improved_metrics


def test_one_worsened_metric_rejects_even_when_others_improve() -> None:
    result = evaluate_candidate(
        _package(),
        _candidate(),
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_computer(
            _metrics(),
            _metrics(
                weak=1,
                membership=0.4,
                coverage=0.3,
                components=1,
                conductance=0.3,
            ),
        ),
    )
    assert result.status is CandidateStatus.HARD_GATE_REJECTED
    assert result.reason == "PARETO_METRIC_WORSENED"


def test_move_recomputes_both_affected_chains_before_and_after() -> None:
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def compute(package, chain_ids):
        calls.append((chain_ids, tuple(package.members_of("U"))))
        if tuple(package.members_of("U")) == ("Z",):
            return _metrics()
        return _metrics(
            weak=1,
            membership=0.4,
            coverage=0.6,
            components=1,
            conductance=0.3,
            severity=0,
        )

    result = evaluate_candidate(
        _package(),
        _move_candidate(),
        analysis_config=object(),
        config=CONFIG,
        metric_computer=compute,
    )

    assert result.status is CandidateStatus.BETTER_SUPPORTED
    assert calls == [
        (("C", "U"), ("Z",)),
        (("C", "U"), ("X", "Z")),
    ]


def test_exact_move_records_connector_fact_and_effect_after_hard_gate_passes(
    monkeypatch,
) -> None:
    before = _metrics()
    after = _metrics(
        weak=1,
        membership=0.4,
        coverage=0.6,
        components=1,
        conductance=0.3,
        severity=0,
    )

    def exact(package, chain_ids, *, structural_roles_by_chain=None, **_kwargs):
        assert structural_roles_by_chain is not None
        if package.members_of("U") == ["Z"]:
            structural_roles_by_chain["C"] = {
                "X": StructuralRoleResult(
                    alarm_id="X",
                    role=StructuralRole.NON_CONNECTOR,
                    is_articulation_point=False,
                    blocks_supported=1,
                    reason="not a bridge",
                )
            }
            return before
        structural_roles_by_chain["U"] = {
            "X": StructuralRoleResult(
                alarm_id="X",
                role=StructuralRole.CONNECTOR,
                is_articulation_point=True,
                blocks_supported=2,
                reason="exact bridge",
            )
        }
        return after

    monkeypatch.setattr(evaluator_module, "compute_exact_partition_metrics", exact)
    result = evaluate_candidate(
        _package(), _move_candidate(), analysis_config=object(), config=CONFIG
    )

    assert result.status is CandidateStatus.BETTER_SUPPORTED
    assert result.move_structural_facts is not None
    assert result.move_structural_facts.before_structural_role == "NON_CONNECTOR"
    assert result.move_structural_facts.after_structural_role == "CONNECTOR"
    assert result.move_structural_facts.after_is_articulation_point is True
    assert result.move_structural_facts.after_blocks_supported == 2
    assert [effect.value for effect in result.semantic_effects] == ["BECOMES_CONNECTOR"]


def test_exact_move_keeps_connector_fact_but_not_effect_after_hard_gate_rejection(
    monkeypatch,
) -> None:
    before = _metrics()
    rejected_after = _metrics(
        weak=1,
        membership=0.4,
        coverage=0.3,
        components=1,
        conductance=0.3,
        severity=0,
    )

    def exact(package, chain_ids, *, structural_roles_by_chain=None, **_kwargs):
        assert structural_roles_by_chain is not None
        roles = structural_roles_by_chain.setdefault(
            "C" if package.members_of("U") == ["Z"] else "U", {}
        )
        roles["X"] = StructuralRoleResult(
            alarm_id="X",
            role=StructuralRole.CONNECTOR,
            is_articulation_point=True,
            blocks_supported=2,
            reason="exact bridge",
        )
        return before if package.members_of("U") == ["Z"] else rejected_after

    monkeypatch.setattr(evaluator_module, "compute_exact_partition_metrics", exact)
    result = evaluate_candidate(
        _package(), _move_candidate(), analysis_config=object(), config=CONFIG
    )

    assert result.status is CandidateStatus.HARD_GATE_REJECTED
    assert result.move_structural_facts is not None
    assert result.move_structural_facts.after_structural_role == "CONNECTOR"
    assert result.semantic_effects == ()


def test_singleton_source_move_can_become_connector(monkeypatch) -> None:
    candidate = CounterfactualCandidate(
        candidate_id="move-Z",
        operation=Operation.MOVE_MEMBER,
        partition_delta=PartitionDelta(
            before=(("C", ("A", "B", "C", "X")), ("U", ("Z",))),
            after=(("C", ("A", "B", "C", "X", "Z")),),
        ),
        edit_cost=EditCost(1, 1, 5),
        source_ref="test",
        member_ids=("Z",),
        source_chain_id="U",
        target_chain_id="C",
    )
    before = _metrics()
    after = _metrics(
        weak=1,
        membership=0.4,
        coverage=0.6,
        components=1,
        conductance=0.3,
        severity=0,
    )

    def exact(package, chain_ids, *, structural_roles_by_chain=None, **_kwargs):
        assert structural_roles_by_chain is not None
        if package.members_of("U") == ["Z"]:
            return before
        structural_roles_by_chain["C"] = {
            "Z": StructuralRoleResult(
                alarm_id="Z",
                role=StructuralRole.CONNECTOR,
                is_articulation_point=True,
                blocks_supported=2,
                reason="exact bridge",
            )
        }
        return after

    monkeypatch.setattr(evaluator_module, "compute_exact_partition_metrics", exact)
    result = evaluate_candidate(
        _package(), candidate, analysis_config=object(), config=CONFIG
    )

    assert result.move_structural_facts is not None
    assert result.move_structural_facts.before_structural_role == "NOT_APPLICABLE"
    assert [effect.value for effect in result.semantic_effects] == ["BECOMES_CONNECTOR"]


def test_incomparable_candidates_both_remain_on_frontier() -> None:
    current = _metrics(weak=2, membership=0.2, coverage=0.4, components=2, conductance=0.1)
    membership = evaluate_candidate(
        _package(),
        _candidate("membership"),
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_computer(
            current,
            _metrics(weak=1, membership=0.8, coverage=0.5, components=2, conductance=0.1),
        ),
    )
    structure = evaluate_candidate(
        _package(),
        _candidate("structure"),
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_computer(
            current,
            _metrics(weak=2, membership=0.3, coverage=0.5, components=1, conductance=0.8),
        ),
    )

    frontier = select_frontier((membership, structure), CONFIG)
    assert {item.candidate.candidate_id for item in frontier.items} == {
        "membership",
        "structure",
    }


def test_frontier_prefers_external_then_improvements_then_stable_id() -> None:
    current = _metrics()
    after = _metrics(weak=1, membership=0.4, coverage=0.6, components=1, conductance=0.3, severity=0)
    internal = evaluate_candidate(
        _package(), _candidate("a"), analysis_config=object(), config=CONFIG,
        metric_computer=_computer(current, after),
    )
    external = evaluate_candidate(
        _package(), _candidate("z"), analysis_config=object(), config=CONFIG,
        metric_computer=_computer(current, after), externally_supported=True,
    )
    frontier = select_frontier((internal, external), replace(CONFIG, max_recommendations=1))
    assert frontier.items[0].candidate.candidate_id == "z"
    assert frontier.truncated is True

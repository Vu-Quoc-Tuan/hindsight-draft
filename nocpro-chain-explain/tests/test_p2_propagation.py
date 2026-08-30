"""Configured fail-closed P2 propagation hypotheses (ADR-0033)."""

from __future__ import annotations

from dataclasses import replace
from math import exp

import pytest

from configuration import ConfiguredValue, ParameterSource, PropagationConfig
from libs.contracts import (
    IngestedAlarm,
    IngestedChain,
    IngestedPackage,
    IngestedSnapshot,
)
from tier2.topology_hypotheses import (
    HypothesisStatus,
    PropagationEdgeHypothesis,
    PropagationNodeScore,
    TopologyHypothesisReason,
    analyze_propagation,
)
from tier2.topology_hypotheses.propagation import _run_configured_rwr


def _cv(path: str, value: int | float, source=ParameterSource.FROZEN_SPEC):
    return ConfiguredValue(path=f"propagation.{path}", value=value, source=source)


@pytest.fixture()
def config() -> PropagationConfig:
    return PropagationConfig(
        config_version="propagation-test-v1",
        restart_probability=_cv("rwr.restart_probability", 0.2),
        convergence_tolerance=_cv("rwr.convergence_tolerance", 1e-12),
        max_iterations=_cv("rwr.max_iterations", 1000),
        decay_type="exponential",
        decay_parameter=_cv("temporal.decay_parameter", 10.0),
        score_threshold=_cv("acceptance.score_threshold", 0.0),
        max_candidate_edges=_cv("limits.max_candidate_edges", 20),
    )


def _edge(
    source: str,
    target: str,
    *,
    source_id: str = "synthetic-topology",
    source_version: str = "v1",
    relation_type: str = "LOGICAL_DEPENDENCY",
    directed: bool = True,
) -> dict:
    return {
        "edge_id": f"{source_id}:{source}:{target}",
        "source_resource_id": source,
        "target_resource_id": target,
        "relation_type": relation_type,
        "directed": directed,
        "source_id": source_id,
        "source_version": source_version,
        "source_kind": "SYNTHETIC_TEST",
        "provenance_class": "EXTERNAL_OPERATIONAL",
        "provenance_subtype": "TOPOLOGY_EXTERNAL",
    }


def _mapping(alarm_id: str, resource_id: str | None, status: str = "EXACT") -> dict:
    return {
        "alarm_id": alarm_id,
        "resource_id": resource_id,
        "mapping_status": status,
        "mapping_method": "EXACT_IDENTITY" if status == "EXACT" else "NONE",
    }


def _package(
    times: dict[str, str | None],
    edges: list[dict],
    *,
    mappings: list[dict] | None = None,
) -> IngestedPackage:
    members = tuple(times)
    return IngestedPackage(
        snapshot=IngestedSnapshot(
            snapshot_id="S1",
            snapshot_version="snapshot-v1",
            snapshot_time="2026-08-30T00:00:00Z",
            status="COMPLETE",
            source="synthetic-fixture",
            source_kind="SYNTHETIC_TEST",
            produced_at="2026-08-30T00:00:00Z",
            topology_version="topology-v1",
        ),
        alarms={
            alarm_id: IngestedAlarm(
                alarm_id=alarm_id,
                snapshot_id="S1",
                raw={},
                canonical_start_time=start_time,
            )
            for alarm_id, start_time in times.items()
        },
        chains={"C1": IngestedChain("C1", "S1", len(members))},
        memberships={"C1": list(members)},
        topology={
            "edges": edges,
            "mappings": mappings
            if mappings is not None
            else [_mapping(alarm_id, f"R_{alarm_id}") for alarm_id in members],
        },
    )


def _scores(result) -> dict[str, float]:
    return {node.alarm_id: node.score for node in result.node_scores}


def test_candidate_edge_requires_direction_and_strict_time(config: PropagationConfig):
    package = _package(
        {
            "A": "2026-08-30T00:00:00Z",
            "B": "2026-08-30T00:00:10+00:00",
            "C": "2026-08-30T07:00:00+07:00",
            "D": "2026-08-29T23:59:59Z",
        },
        [
            _edge("R_A", "R_B"),
            _edge("R_B", "R_A"),
            _edge("R_A", "R_C"),
            _edge("R_A", "R_D"),
        ],
    )

    result = analyze_propagation(package, "C1", config)

    assert result.status is HypothesisStatus.AVAILABLE
    assert [(e.source_alarm_id, e.target_alarm_id) for e in result.hypotheses] == [
        ("A", "B")
    ]
    assert result.candidate_node_count == 4
    assert result.candidate_edge_count == 1


def test_timezone_normalization_treats_naive_timestamp_as_utc(
    config: PropagationConfig,
):
    package = _package(
        {"A": "2026-08-30T00:00:00", "B": "2026-08-30T07:00:01+07:00"},
        [_edge("R_A", "R_B")],
    )

    result = analyze_propagation(package, "C1", config)

    assert result.status is HypothesisStatus.AVAILABLE
    assert result.hypotheses[0].temporal_delta_seconds == pytest.approx(1.0)


@pytest.mark.parametrize("missing_time", [None, "not-a-time"])
def test_every_member_requires_parseable_canonical_time(
    config: PropagationConfig, missing_time: str | None
):
    package = _package(
        {"A": "2026-08-30T00:00:00Z", "B": missing_time},
        [_edge("R_A", "R_B")],
    )

    result = analyze_propagation(package, "C1", config)

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.TEMPORAL_ORDERING_UNAVAILABLE
    assert result.node_scores == ()
    assert result.hypotheses == ()


@pytest.mark.parametrize("status", ["UNMAPPED", "AMBIGUOUS"])
def test_every_member_requires_exact_or_verified_mapping(
    config: PropagationConfig, status: str
):
    package = _package(
        {"A": "2026-08-30T00:00:00Z", "B": "2026-08-30T00:00:01Z"},
        [_edge("R_A", "R_B")],
        mappings=[_mapping("A", "R_A"), _mapping("B", None, status)],
    )

    result = analyze_propagation(package, "C1", config)

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.RESOURCE_MAPPING_UNAVAILABLE


def test_candidate_limit_never_truncates(config: PropagationConfig):
    package = _package(
        {
            "A": "2026-08-30T00:00:00Z",
            "B": "2026-08-30T00:00:01Z",
            "C": "2026-08-30T00:00:02Z",
        },
        [_edge("R_A", "R_B"), _edge("R_A", "R_C")],
    )

    result = analyze_propagation(
        package, "C1", replace(config, max_candidate_edges=_cv("limits.max_candidate_edges", 1))
    )

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.CANDIDATE_LIMIT_EXCEEDED
    assert result.candidate_edge_count == 2
    assert result.hypotheses == ()
    assert result.node_scores == ()


def test_candidate_edges_never_mix_source_version_relation_universes(
    config: PropagationConfig,
):
    package = _package(
        {
            "A": "2026-08-30T00:00:00Z",
            "B": "2026-08-30T00:00:01Z",
            "C": "2026-08-30T00:00:02Z",
        },
        [
            _edge("R_A", "R_B", source_id="source-one"),
            _edge("R_B", "R_C", source_id="source-two"),
        ],
    )

    result = analyze_propagation(package, "C1", config)

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.DIRECTED_TOPOLOGY_UNAVAILABLE
    assert result.hypotheses == ()


def test_low_level_rwr_rejects_a_cycle_before_iteration(config: PropagationConfig):
    outcome = _run_configured_rwr(
        ("A", "B"),
        (("A", "B", 1.0), ("B", "A", 1.0)),
        config,
    )

    assert outcome.reason is TopologyHypothesisReason.INVALID_DAG
    assert outcome.iterations == 0
    assert outcome.scores is None


def test_pi_zero_uniform_restart_and_dangling_redistribution_are_exact(
    config: PropagationConfig,
):
    package = _package(
        {
            "A": "2026-08-30T00:00:00Z",
            "B": "2026-08-30T00:00:01Z",
            "C": "2026-08-29T23:59:59Z",
        },
        [
            _edge("R_A", "R_B"),
            # Keeps C in the same universe while strict time rejects B -> C.
            _edge("R_B", "R_C"),
        ],
    )
    one_step = replace(
        config,
        convergence_tolerance=_cv("rwr.convergence_tolerance", 2.0),
        max_iterations=_cv("rwr.max_iterations", 1),
    )

    result = analyze_propagation(package, "C1", one_step)

    assert result.status is HypothesisStatus.AVAILABLE
    assert result.iterations == 1
    assert _scores(result) == pytest.approx({"A": 0.3, "B": 0.4, "C": 0.3})
    assert result.seed_policy == "ALL_SOURCE_NODES_UNIFORM"
    assert result.dangling_policy == "REDISTRIBUTE_TO_RESTART"


def test_exponential_weights_are_outgoing_normalized_and_edge_score_is_flow(
    config: PropagationConfig,
):
    package = _package(
        {
            "A": "2026-08-30T00:00:00Z",
            "B": "2026-08-30T00:00:10Z",
            "C": "2026-08-30T00:00:20Z",
        },
        [_edge("R_A", "R_B"), _edge("R_A", "R_C")],
    )
    one_step = replace(
        config,
        convergence_tolerance=_cv("rwr.convergence_tolerance", 2.0),
        max_iterations=_cv("rwr.max_iterations", 1),
    )

    result = analyze_propagation(package, "C1", one_step)

    transition_ab = exp(-1.0) / (exp(-1.0) + exp(-2.0))
    transition_ac = 1.0 - transition_ab
    assert _scores(result) == pytest.approx(
        {"A": 0.2, "B": 0.8 * transition_ab, "C": 0.8 * transition_ac}
    )
    edges = {(edge.source_alarm_id, edge.target_alarm_id): edge for edge in result.hypotheses}
    assert edges[("A", "B")].transition_probability == pytest.approx(transition_ab)
    assert edges[("A", "C")].transition_probability == pytest.approx(transition_ac)
    assert edges[("A", "B")].score == pytest.approx(0.8 * 0.2 * transition_ab)
    assert edges[("A", "C")].score == pytest.approx(0.8 * 0.2 * transition_ac)


def test_l1_convergence_succeeds_on_final_allowed_iteration(config: PropagationConfig):
    package = _package(
        {"A": "2026-08-30T00:00:00Z", "B": "2026-08-30T00:00:01Z"},
        [_edge("R_A", "R_B")],
    )
    final_iteration = replace(
        config,
        convergence_tolerance=_cv("rwr.convergence_tolerance", 1.6),
        max_iterations=_cv("rwr.max_iterations", 1),
    )

    result = analyze_propagation(package, "C1", final_iteration)

    assert result.status is HypothesisStatus.AVAILABLE
    assert result.iterations == 1
    assert result.final_l1_distance == pytest.approx(1.6)


def test_nonconvergence_emits_diagnostics_but_no_approximation(
    config: PropagationConfig,
):
    package = _package(
        {"A": "2026-08-30T00:00:00Z", "B": "2026-08-30T00:00:01Z"},
        [_edge("R_A", "R_B")],
    )
    too_short = replace(
        config,
        convergence_tolerance=_cv("rwr.convergence_tolerance", 1e-18),
        max_iterations=_cv("rwr.max_iterations", 1),
    )

    result = analyze_propagation(package, "C1", too_short)

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.RWR_NOT_CONVERGED
    assert result.iterations == 1
    assert result.final_l1_distance == pytest.approx(1.6)
    assert result.node_scores == ()
    assert result.hypotheses == ()


def test_converged_stationary_mass_and_edge_flow_match_closed_form(
    config: PropagationConfig,
):
    package = _package(
        {"A": "2026-08-30T00:00:00Z", "B": "2026-08-30T00:00:01Z"},
        [_edge("R_A", "R_B")],
    )

    result = analyze_propagation(package, "C1", config)

    # alpha=.2, A->B and dangling B give A=.2+.8B, B=.8A.
    assert result.status is HypothesisStatus.AVAILABLE
    assert _scores(result) == pytest.approx({"A": 5.0 / 9.0, "B": 4.0 / 9.0})
    assert result.hypotheses[0].score == pytest.approx(4.0 / 9.0)


def test_converged_scores_sum_to_one_and_respect_acceptance_threshold(
    config: PropagationConfig,
):
    package = _package(
        {"A": "2026-08-30T00:00:00Z", "B": "2026-08-30T00:00:01Z"},
        [_edge("R_A", "R_B")],
    )
    reject_all_edges = replace(
        config,
        score_threshold=_cv("acceptance.score_threshold", 1.0),
    )

    result = analyze_propagation(package, "C1", reject_all_edges)

    assert result.status is HypothesisStatus.AVAILABLE
    assert sum(_scores(result).values()) == pytest.approx(1.0)
    assert result.final_l1_distance <= result.convergence_tolerance
    assert result.hypotheses == ()


def test_output_is_deterministic_immutable_and_preserves_config_provenance(
    config: PropagationConfig,
):
    package = _package(
        {"B": "2026-08-30T00:00:01Z", "A": "2026-08-30T00:00:00Z"},
        [_edge("R_A", "R_B")],
    )

    first = analyze_propagation(package, "C1", config)
    second = analyze_propagation(package, "C1", config)
    changed_config = replace(
        config,
        config_version="propagation-test-v2",
        score_threshold=_cv(
            "acceptance.score_threshold", 0.0, ParameterSource.DATA_DRIVEN
        ),
    )
    changed = analyze_propagation(package, "C1", changed_config)

    assert first == second
    assert first.node_scores == tuple(sorted(first.node_scores, key=lambda node: node.alarm_id))
    assert first.hypotheses == tuple(
        sorted(first.hypotheses, key=lambda edge: (edge.source_alarm_id, edge.target_alarm_id))
    )
    assert all(isinstance(node, PropagationNodeScore) for node in first.node_scores)
    assert all(isinstance(edge, PropagationEdgeHypothesis) for edge in first.hypotheses)
    assert changed.config_version == "propagation-test-v2"
    assert (
        changed.parameter_provenance["propagation.acceptance.score_threshold"]
        == "DATA_DRIVEN"
    )
    with pytest.raises(TypeError):
        changed.parameter_provenance["new"] = "FROZEN_SPEC"


def test_missing_propagation_config_fails_closed_before_numeric_work():
    package = _package(
        {"A": "2026-08-30T00:00:00Z", "B": "2026-08-30T00:00:01Z"},
        [_edge("R_A", "R_B")],
    )

    result = analyze_propagation(package, "C1", None)

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.PROPAGATION_CONFIG_INCOMPLETE
    assert result.iterations == 0
    assert result.node_scores == ()
    assert result.hypotheses == ()

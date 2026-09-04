"""Structural audit tests (§6, ADR-0018/0019).

Pinned invariants:
  - the audit graph is built only from >=2 distinct audit-eligible groups
  - SYSTEM_FACT/BEHAVIORAL channels never contribute audit weight
  - |C| < 10 is SKIPPED, not scored as "no cut = stable"
  - a genuinely separated two-block chain produces CANDIDATE_SPLIT
  - a tightly-knit chain produces NO_LOW_CONDUCTANCE_CUT
  - H_domain proposes blocks but is never clique-projected into edges
"""

from __future__ import annotations

import pytest

from audit import (
    Candidate,
    CandidateSource,
    StructuralRole,
    build_audit_graph,
    calibrate_epsilon,
    classify_structural_role,
    classify_structural_roles,
    conductance,
    connected_components,
    dependency_candidates,
    derived_candidates,
    descriptor_candidates,
    entity_candidates,
    failure_domain_candidates,
    find_articulation_points,
    generate_candidates,
    is_chain_too_small_for_audit,
    min_side_requirement,
    run_structural_audit,
    score_candidates,
)
from audit.graph import AuditEdge, AuditGraph
from audit.conductance import AuditVerdict
from channels.base import ChannelValue
from descriptor import build_predicate_index
from libs.contracts import IngestedAlarm
from libs.provenance import ProvenanceClass


def cv(channel_id, tag, *, available=True, score=1.0, threshold=1.0, provenance=ProvenanceClass.POST_HOC):
    return ChannelValue(
        channel_id=channel_id,
        derivation_tag=tag,
        provenance_class=provenance,
        availability=available,
        positive_score=score if available else 0.0,
        threshold=threshold,
    )


def alarm(alarm_id, **fields):
    return IngestedAlarm(
        alarm_id=alarm_id,
        snapshot_id="s1",
        raw={k: str(v) for k, v in fields.items()},
        alarm_name=fields.get("alarm_name"),
        device_code=fields.get("device_code"),
        node_reference=fields.get("node_reference"),
    )


# --------------------------------------------------------------------------
# Audit graph: >= 2 distinct audit-eligible groups
# --------------------------------------------------------------------------


def test_single_supporting_group_is_not_enough_for_an_edge():
    """Anti single-view-edge rule: 1 group must not create an edge."""
    pairs = {("a", "b"): [cv("S", "semantic", score=1.0, threshold=0.5)]}
    graph = build_audit_graph(["a", "b"], pairs)
    assert graph.edges == ()


def test_two_distinct_groups_create_an_edge():
    pairs = {
        ("a", "b"): [
            cv("S", "semantic", score=1.0, threshold=0.5),
            cv("E_site", "site", score=1.0, threshold=0.5),
        ]
    }
    graph = build_audit_graph(["a", "b"], pairs)
    assert len(graph.edges) == 1
    assert set(graph.edges[0].supporting_groups) == {"semantic", "site"}


def test_three_channels_one_derivation_group_do_not_satisfy_the_rule():
    """Same field, three channels: still ONE group, so it cannot alone form an edge."""
    pairs = {
        ("a", "b"): [
            cv("E_reference_1", "reference", score=1.0, threshold=0.5),
            cv("E_reference_2", "reference", score=1.0, threshold=0.5),
            cv("E_reference_3", "reference", score=1.0, threshold=0.5),
        ]
    }
    graph = build_audit_graph(["a", "b"], pairs)
    assert graph.edges == ()


def test_system_fact_never_contributes_audit_weight():
    """ADR-0010: SYSTEM_FACT must not strengthen G*_audit."""
    pairs = {
        ("a", "b"): [
            cv("S", "semantic", score=1.0, threshold=0.5),
            cv(
                "M_pair",
                "system_pair",
                score=1.0,
                threshold=0.5,
                provenance=ProvenanceClass.SYSTEM_FACT,
            ),
        ]
    }
    graph = build_audit_graph(["a", "b"], pairs)
    # Only one audit-eligible group (semantic); SYSTEM_FACT is excluded, not
    # just weighted down, so the edge cannot form from these two alone.
    assert graph.edges == ()


def test_behavioral_never_contributes_audit_weight():
    pairs = {
        ("a", "b"): [
            cv("S", "semantic", score=1.0, threshold=0.5),
            cv(
                "H",
                "grouping_history",
                score=1.0,
                threshold=0.5,
                provenance=ProvenanceClass.BEHAVIORAL,
            ),
        ]
    }
    graph = build_audit_graph(["a", "b"], pairs)
    assert graph.edges == ()


def test_unavailable_channel_does_not_count_toward_the_rule():
    pairs = {
        ("a", "b"): [
            cv("S", "semantic", score=1.0, threshold=0.5),
            cv("E_site", "site", available=False),
        ]
    }
    graph = build_audit_graph(["a", "b"], pairs)
    assert graph.edges == ()


# --------------------------------------------------------------------------
# Conductance
# --------------------------------------------------------------------------


def test_conductance_of_a_clean_two_block_cut_is_low():
    pairs = {}
    block_a = ["a1", "a2", "a3", "a4", "a5"]
    block_b = ["b1", "b2", "b3", "b4", "b5"]
    for i in range(len(block_a)):
        for j in range(i + 1, len(block_a)):
            pairs[(block_a[i], block_a[j])] = [
                cv("S", "semantic", score=1.0, threshold=0.5),
                cv("E_site", "site", score=1.0, threshold=0.5),
            ]
    for i in range(len(block_b)):
        for j in range(i + 1, len(block_b)):
            pairs[(block_b[i], block_b[j])] = [
                cv("S", "semantic", score=1.0, threshold=0.5),
                cv("E_site", "site", score=1.0, threshold=0.5),
            ]
    graph = build_audit_graph(block_a + block_b, pairs)
    result = conductance(graph, frozenset(block_a), label="block A")
    assert result.phi == pytest.approx(0.0)


def test_conductance_is_undefined_not_zero_with_no_volume():
    graph = build_audit_graph(["a", "b", "c"], {})
    result = conductance(graph, frozenset({"a"}), label="isolated")
    assert result.phi is None
    assert result.feasible is True
    assert "no audit-eligible edge volume" in result.reason


def test_min_side_requirement_uses_rho_and_floor():
    assert min_side_requirement(100) == 20  # rho=0.2 * 100
    assert min_side_requirement(10) == 5  # floor wins
    assert min_side_requirement(11, rho=0.2, min_side_size=1) == 3


# --------------------------------------------------------------------------
# Small-chain policy
# --------------------------------------------------------------------------


def test_small_chain_is_skipped_not_scored_stable():
    """|C| < 10: SKIPPED is a different claim from NO_LOW_CONDUCTANCE_CUT."""
    assert is_chain_too_small_for_audit(9) is True
    assert is_chain_too_small_for_audit(10) is False

    members = [f"a{i}" for i in range(6)]
    graph = build_audit_graph(members, {})
    result = run_structural_audit("C1", graph, [], epsilon=0.3)
    assert result.verdict is AuditVerdict.SKIPPED_SMALL_CHAIN
    assert result.verdict is not AuditVerdict.NO_LOW_CONDUCTANCE_CUT
    assert "too small" not in result.reason or ">=" in result.reason


# --------------------------------------------------------------------------
# End-to-end audit run
# --------------------------------------------------------------------------


def _two_block_chain(n_per_block=8):
    """Two tightly-knit blocks with almost no cross-block evidence."""
    block_a = [f"a{i}" for i in range(n_per_block)]
    block_b = [f"b{i}" for i in range(n_per_block)]
    pairs = {}
    for group, block in (("A", block_a), ("B", block_b)):
        for i in range(len(block)):
            for j in range(i + 1, len(block)):
                pairs[(block[i], block[j])] = [
                    cv("S", "semantic", score=1.0, threshold=0.5),
                    cv("E_site", "site", score=1.0, threshold=0.5),
                ]
    # A single weak cross-block link, not enough to raise conductance much.
    pairs[(block_a[0], block_b[0])] = [
        cv("S", "semantic", score=0.1, threshold=0.5),
        cv("E_site", "site", score=0.1, threshold=0.5),
    ]
    return block_a, block_b, pairs


def test_two_block_chain_produces_candidate_split():
    block_a, block_b, pairs = _two_block_chain()
    all_members = block_a + block_b
    graph = build_audit_graph(all_members, pairs)

    candidate = Candidate(
        source=CandidateSource.ENTITY, members=frozenset(block_a), label="block A"
    )
    result = run_structural_audit("C1", graph, [candidate], epsilon=0.3)
    assert result.verdict is AuditVerdict.CANDIDATE_SPLIT
    assert result.best_cut.conductance.phi < 0.3


def test_tightly_knit_chain_produces_no_low_conductance_cut():
    members = [f"a{i}" for i in range(10)]
    pairs = {}
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            pairs[(members[i], members[j])] = [
                cv("S", "semantic", score=1.0, threshold=0.5),
                cv("E_site", "site", score=1.0, threshold=0.5),
            ]
    graph = build_audit_graph(members, pairs)
    candidate = Candidate(
        source=CandidateSource.ENTITY,
        members=frozenset(members[:5]),
        label="half",
    )
    result = run_structural_audit("C1", graph, [candidate], epsilon=0.1)
    assert result.verdict is AuditVerdict.NO_LOW_CONDUCTANCE_CUT


def test_balance_constraint_rejects_lopsided_candidates():
    members = [f"a{i}" for i in range(20)]
    graph = build_audit_graph(members, {})
    tiny_candidate = Candidate(
        source=CandidateSource.ENTITY, members=frozenset(members[:2]), label="tiny"
    )
    scored = score_candidates(graph, [tiny_candidate], chain_size=20)
    assert scored[0].conductance.feasible is False


# --------------------------------------------------------------------------
# Candidate generation (deterministic table)
# --------------------------------------------------------------------------


def test_entity_candidates_partition_by_dominant_value():
    alarms = [
        alarm("a1", device_code="D1"),
        alarm("a2", device_code="D1"),
        alarm("a3", device_code="D2"),
        alarm("a4", device_code="D2"),
    ]
    candidates = entity_candidates(alarms, fields=("device_code",))
    labels = {c.label: c.members for c in candidates}
    assert labels["device_code=D1"] == frozenset({"a1", "a2"})
    assert labels["device_code=D2"] == frozenset({"a3", "a4"})


def test_dependency_candidates_use_union_find_above_threshold():
    members = ["a", "b", "c", "d"]
    edges = [("a", "b", 0.9), ("b", "c", 0.1), ("c", "d", 0.9)]
    candidates = dependency_candidates(members, edges, theta_dep=0.5)
    member_sets = {c.members for c in candidates}
    assert frozenset({"a", "b"}) in member_sets
    assert frozenset({"c", "d"}) in member_sets


def test_failure_domain_candidates_are_whole_hyperedges():
    """H_domain proposes a block; it must not be split into pair edges here."""
    candidates = failure_domain_candidates(
        [("SRLG-1", frozenset({"a", "b", "c"}))]
    )
    assert len(candidates) == 1
    assert candidates[0].members == frozenset({"a", "b", "c"})
    assert candidates[0].source is CandidateSource.FAILURE_DOMAIN


def test_descriptor_candidates_use_the_mined_extent():
    from descriptor import DescriptorKind, DescriptorMetrics, Descriptor, Predicate

    universe = [alarm(f"a{i}", device_code="D1") for i in range(3)] + [
        alarm(f"b{i}", device_code="D2") for i in range(3)
    ]
    index = build_predicate_index(universe)
    descriptor = Descriptor(
        kind=DescriptorKind.IDENTITY,
        predicates=(Predicate(field="device_code", value="D1", derivation_tag="device"),),
        extent=index.bitmap(
            next(p for p in index.predicates() if p.value == "D1")
        ),
        metrics=DescriptorMetrics(true_positives=3, false_positives=0, target_size=3, universe_size=6),
    )
    candidates = descriptor_candidates((descriptor,), index)
    assert len(candidates) == 1
    assert candidates[0].members == frozenset({"a0", "a1", "a2"})


def test_derived_candidates_are_union_and_difference():
    a = Candidate(source=CandidateSource.ENTITY, members=frozenset({"1", "2", "3"}), label="A")
    b = Candidate(source=CandidateSource.ENTITY, members=frozenset({"3", "4", "5"}), label="B")
    derived = derived_candidates([a, b], all_members=frozenset({"1", "2", "3", "4", "5", "6"}))
    labels = {d.label: d.members for d in derived}
    assert frozenset({"1", "2", "3", "4", "5"}) in labels.values()
    assert frozenset({"1", "2"}) in labels.values()
    assert frozenset({"4", "5"}) in labels.values()


def test_no_second_community_detection_is_run():
    """Structural guard: candidate generation must not import a clustering algorithm."""
    import audit.candidates as module

    forbidden = {"louvain", "spectral_cluster", "kmeans"}
    assert forbidden.isdisjoint(dir(module))


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------


def test_full_bin_used_when_enough_samples():
    result = calibrate_epsilon(list(range(30)), None, n_min=20)
    assert result.level == "FULL"
    assert result.low_confidence is False


def test_falls_back_to_coarse_bin():
    result = calibrate_epsilon([1, 2, 3], list(range(25)), n_min=20)
    assert result.level == "COARSE"
    assert result.low_confidence is False


def test_falls_back_to_global_weak_baseline():
    """A handful of samples must not produce false precision."""
    result = calibrate_epsilon([1, 2], [3, 4], n_min=20, global_weak_baseline=0.3)
    assert result.level == "GLOBAL"
    assert result.low_confidence is True
    assert result.epsilon == 0.3


# --------------------------------------------------------------------------
# STRUCTURAL role: CONNECTOR / NON_CONNECTOR
# --------------------------------------------------------------------------


def test_bridge_node_is_a_connector():
    """A-B-C path: B is an articulation point supporting 2 blocks."""
    pairs = {
        ("A", "B"): [cv("S", "semantic", score=1.0, threshold=0.5), cv("E_site", "site", score=1.0, threshold=0.5)],
        ("B", "C"): [cv("S", "semantic", score=1.0, threshold=0.5), cv("E_site", "site", score=1.0, threshold=0.5)],
    }
    graph = build_audit_graph(["A", "B", "C"], pairs)
    result = classify_structural_role("B", graph)
    assert result.role is StructuralRole.CONNECTOR
    assert result.is_articulation_point is True
    assert result.blocks_supported == 2


def test_articulation_detection_handles_a_path_beyond_python_recursion_limit():
    """Exact Audit permits chains up to 2,000 members, including sparse paths."""
    members = tuple(f"N{index:04d}" for index in range(1_101))
    adjacency = {member: {} for member in members}
    edges = []
    for left, right in zip(members, members[1:]):
        adjacency[left][right] = 1.0
        adjacency[right][left] = 1.0
        edges.append(
            AuditEdge(
                node_a=left,
                node_b=right,
                weight=1.0,
                supporting_groups=("semantic", "entity"),
            )
        )
    graph = AuditGraph(members=members, edges=tuple(edges), adjacency=adjacency)

    articulation = find_articulation_points(graph)

    assert len(articulation) == len(members) - 2
    assert members[0] not in articulation
    assert members[-1] not in articulation
    assert members[1] in articulation
    assert members[-2] in articulation
    roles = classify_structural_roles(graph)
    assert roles[members[1]].role is StructuralRole.CONNECTOR
    assert roles[members[1]].blocks_supported == 2
    assert roles[members[0]].role is StructuralRole.NON_CONNECTOR


def test_leaf_of_a_dense_graph_is_non_connector():
    members = ["A", "B", "C", "D"]
    pairs = {}
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            pairs[(members[i], members[j])] = [
                cv("S", "semantic", score=1.0, threshold=0.5),
                cv("E_site", "site", score=1.0, threshold=0.5),
            ]
    graph = build_audit_graph(members, pairs)
    result = classify_structural_role("A", graph)
    assert result.role is StructuralRole.NON_CONNECTOR


def test_role_uses_the_audit_graph_not_visualization_graph():
    """Structural guard: no top-K/visualization parameter exists to misuse."""
    import inspect

    signature = inspect.signature(classify_structural_role)
    assert "top_k" not in signature.parameters
    assert "visualization" not in signature.parameters


def test_no_edges_is_not_applicable_not_non_connector():
    graph = build_audit_graph(["A", "B"], {})
    result = classify_structural_role("A", graph)
    assert result.role is StructuralRole.NOT_APPLICABLE


def test_member_not_in_graph_is_not_applicable():
    graph = build_audit_graph(["A", "B"], {})
    result = classify_structural_role("ghost", graph)
    assert result.role is StructuralRole.NOT_APPLICABLE

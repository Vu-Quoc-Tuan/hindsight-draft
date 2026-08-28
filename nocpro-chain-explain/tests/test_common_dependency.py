"""CommonDependency capability engine tests (§4A, ADR-0032, D1-6).

Pinned invariants:
  - Specificity is always in [0,1] for both scope semantics
  - SHARED_ANCESTOR needs a valid directed hierarchy, else UNAVAILABLE
  - SHARED_ACTIVE_PATH needs verified ordered paths, else UNAVAILABLE
  - a broad ancestor/hub scores lower than a narrow one (anti-hub)
  - active-path specificity counts distinct resources, not ECMP paths
  - active-path distance never falls back to graph shortest path
  - the semantic tier ordering does not force a numeric CD ordering
  - unmapped alarms force Dep_* = UNAVAILABLE
  - undirected adjacency cannot produce SHARED_ANCESTOR/SHARED_ACTIVE_PATH
"""

from __future__ import annotations

import pytest

from channels import (
    ActivePathIndex,
    ChannelFamily,
    DepUpstreamActivePath,
    DepUpstreamAncestor,
    DependencySemantic,
    DirectedHierarchy,
    VerifiedPath,
    build_active_path_index,
    build_directed_hierarchy,
    evaluate_shared_active_path,
    evaluate_shared_ancestor,
    specificity,
)
from channels.base import EvidenceState
from channels.dependency import ResourceResolver
from libs.contracts import IngestedAlarm
from libs.provenance import NormalizedChannel, build_derivation_groups


def alarm(alarm_id: str) -> IngestedAlarm:
    return IngestedAlarm(alarm_id=alarm_id, snapshot_id="s1", raw={})


# --------------------------------------------------------------------------
# Specificity primitive
# --------------------------------------------------------------------------


def test_specificity_is_bounded_in_unit_interval():
    for scope, universe in [(1, 1), (1, 1000), (500, 1000), (999, 1000)]:
        value = specificity(scope, universe)
        assert 0.0 <= value <= 1.0


def test_specificity_of_scope_one_does_not_exceed_one():
    """The old 1/log(1+|Desc|) form broke the [0,1] contract at |Desc|=1."""
    assert specificity(1, 1) <= 1.0
    assert specificity(1, 10_000) <= 1.0


def test_narrow_scope_has_higher_specificity_than_broad_scope():
    narrow = specificity(2, 1000)
    broad = specificity(500, 1000)
    assert narrow > broad


# --------------------------------------------------------------------------
# SHARED_ANCESTOR
# --------------------------------------------------------------------------


HIERARCHY_EDGES = [
    {"source_resource_id": "SYN-CORE-01", "target_resource_id": "SYN-AGG-HN-01", "relation_type": "LOGICAL_DEPENDENCY", "directed": True},
    {"source_resource_id": "SYN-CORE-01", "target_resource_id": "SYN-AGG-HCM-01", "relation_type": "LOGICAL_DEPENDENCY", "directed": True},
    {"source_resource_id": "SYN-AGG-HN-01", "target_resource_id": "SYN-DEA-HN-01", "relation_type": "LOGICAL_DEPENDENCY", "directed": True},
    {"source_resource_id": "SYN-AGG-HN-01", "target_resource_id": "SYN-DEA-HN-02", "relation_type": "LOGICAL_DEPENDENCY", "directed": True},
    {"source_resource_id": "SYN-AGG-HCM-01", "target_resource_id": "SYN-DEA-HCM-01", "relation_type": "LOGICAL_DEPENDENCY", "directed": True},
    {"source_resource_id": "SYN-AGG-HCM-01", "target_resource_id": "SYN-DEA-HCM-02", "relation_type": "LOGICAL_DEPENDENCY", "directed": True},
]


@pytest.fixture()
def hierarchy() -> DirectedHierarchy:
    return build_directed_hierarchy(HIERARCHY_EDGES)


def test_hierarchy_ignores_undirected_edges():
    """ADR-MOCK-0005: undirected adjacency must not seed a hierarchy."""
    edges = [
        {"source_resource_id": "A", "target_resource_id": "B", "relation_type": "IP_ADJACENCY", "directed": False}
    ]
    result = build_directed_hierarchy(edges)
    assert result.is_valid is False


def test_shared_ancestor_gated_on_valid_hierarchy():
    resolver = ResourceResolver(resolved={"a1": "X", "a2": "Y"})
    result = evaluate_shared_ancestor(
        alarm("a1"), alarm("a2"), hierarchy=DirectedHierarchy(), resolver=resolver
    )
    assert result.state is EvidenceState.UNAVAILABLE
    assert "capability gate closed" in result.detail


def test_shared_ancestor_unmapped_alarm_is_unavailable(hierarchy):
    resolver = ResourceResolver(resolved={"a1": "SYN-DEA-HN-01"})
    result = evaluate_shared_ancestor(
        alarm("a1"), alarm("a2"), hierarchy=hierarchy, resolver=resolver
    )
    assert result.state is EvidenceState.UNAVAILABLE
    assert "mapping unresolved" in result.detail


def test_shared_ancestor_no_common_ancestor_is_unavailable(hierarchy):
    resolver = ResourceResolver(
        resolved={"a1": "SYN-DEA-HN-01", "a2": "SYN-CORE-01"}
    )
    # SYN-CORE-01 is the root; it has no ancestors of its own to share.
    result = evaluate_shared_ancestor(
        alarm("a1"), alarm("a2"), hierarchy=hierarchy, resolver=resolver
    )
    assert result.state is EvidenceState.UNAVAILABLE


def test_narrow_ancestor_scores_higher_than_broad_root(hierarchy):
    """Anti-hub: siblings under a narrow parent beat a shared broad root."""
    resolver = ResourceResolver(
        resolved={
            "siblings_a": "SYN-DEA-HN-01",
            "siblings_b": "SYN-DEA-HN-02",
            "cross_a": "SYN-DEA-HN-01",
            "cross_b": "SYN-DEA-HCM-01",
        }
    )
    siblings = evaluate_shared_ancestor(
        alarm("siblings_a"), alarm("siblings_b"), hierarchy=hierarchy, resolver=resolver
    )
    cross_region = evaluate_shared_ancestor(
        alarm("cross_a"), alarm("cross_b"), hierarchy=hierarchy, resolver=resolver
    )
    assert siblings.positive_score > cross_region.positive_score
    assert "SYN-AGG-HN-01" in siblings.detail
    assert "SYN-CORE-01" in cross_region.detail


def test_shared_ancestor_score_within_unit_interval(hierarchy):
    resolver = ResourceResolver(
        resolved={"a1": "SYN-DEA-HN-01", "a2": "SYN-DEA-HN-02"}
    )
    result = evaluate_shared_ancestor(
        alarm("a1"), alarm("a2"), hierarchy=hierarchy, resolver=resolver
    )
    assert 0.0 <= result.positive_score <= 1.0


def test_shared_ancestor_provenance_is_carried():
    hierarchy_local = build_directed_hierarchy(HIERARCHY_EDGES)
    resolver = ResourceResolver(
        resolved={"a1": "SYN-DEA-HN-01", "a2": "SYN-DEA-HN-02"}
    )
    result = evaluate_shared_ancestor(
        alarm("a1"), alarm("a2"), hierarchy=hierarchy_local, resolver=resolver
    )
    assert result.derivation_tag == "dependency:unversioned"
    assert result.dependency_semantic is DependencySemantic.SHARED_ANCESTOR


def test_dep_upstream_contract_separates_provider_but_deduplicates_same_source():
    hierarchy = build_directed_hierarchy(
        [
            {
                "source_resource_id": "ROOT",
                "target_resource_id": "R1",
                "relation_type": "LOGICAL_DEPENDENCY",
                "directed": True,
            },
            {
                "source_resource_id": "ROOT",
                "target_resource_id": "R2",
                "relation_type": "LOGICAL_DEPENDENCY",
                "directed": True,
            },
        ]
    )
    paths = build_active_path_index(
        [
            {"path_id": "p1", "resource_id": "R1", "nodes": ["R1", "ROOT"]},
            {"path_id": "p2", "resource_id": "R2", "nodes": ["R2", "ROOT"]},
        ]
    )
    resolver = ResourceResolver(resolved={"a1": "R1", "a2": "R2"})
    ancestor = DepUpstreamAncestor(
        hierarchy=hierarchy,
        resolver=resolver,
        source_ref="topology-v17",
    ).evaluate(alarm("a1"), alarm("a2"))
    active_path = DepUpstreamActivePath(
        path_index=paths,
        resolver=resolver,
        source_ref="topology-v17",
    ).evaluate(alarm("a1"), alarm("a2"))

    assert ancestor.channel_id == "DepUpstreamAncestor@topology-v17"
    assert active_path.channel_id == "DepUpstreamActivePath@topology-v17"
    assert ancestor.channel_family is ChannelFamily.DEP_UPSTREAM
    assert active_path.channel_family is ChannelFamily.DEP_UPSTREAM
    assert ancestor.dependency_semantic is DependencySemantic.SHARED_ANCESTOR
    assert active_path.dependency_semantic is DependencySemantic.SHARED_ACTIVE_PATH
    assert ancestor.source_ref == active_path.source_ref == "topology-v17"
    assert ancestor.derivation_tag == active_path.derivation_tag == (
        "dependency:topology-v17"
    )

    groups = build_derivation_groups(
        [
            NormalizedChannel(
                channel_id=value.channel_id,
                derivation_tag=value.derivation_tag,
                provenance_class=value.provenance_class,
                provenance_subtype=value.provenance_subtype,
                availability=value.availability,
                supports=value.supports,
                positive_score=value.positive_score,
            )
            for value in (ancestor, active_path)
        ]
    )
    assert len(groups) == 1
    assert {item.channel_id for item in groups[0].channels} == {
        "DepUpstreamAncestor@topology-v17",
        "DepUpstreamActivePath@topology-v17",
    }


# --------------------------------------------------------------------------
# SHARED_ACTIVE_PATH
# --------------------------------------------------------------------------


ACTIVE_PATH_RECORDS = [
    {"path_id": "SYN-PATH-A", "resource_id": "SYN-DEA-A", "nodes": ["SYN-DEA-A", "SYN-R1", "SYN-R2", "SYN-CORE-X"]},
    {"path_id": "SYN-PATH-B", "resource_id": "SYN-DEA-B", "nodes": ["SYN-DEA-B", "SYN-R3", "SYN-R2", "SYN-CORE-X"]},
]


@pytest.fixture()
def path_index() -> ActivePathIndex:
    return build_active_path_index(ACTIVE_PATH_RECORDS)


def test_shared_active_path_gated_on_verified_paths():
    resolver = ResourceResolver(resolved={"a1": "X", "a2": "Y"})
    result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=ActivePathIndex(), resolver=resolver
    )
    assert result.state is EvidenceState.UNAVAILABLE
    assert "capability gate closed" in result.detail


def test_shared_active_path_unmapped_alarm_is_unavailable(path_index):
    resolver = ResourceResolver(resolved={"a1": "SYN-DEA-A"})
    result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=path_index, resolver=resolver
    )
    assert result.state is EvidenceState.UNAVAILABLE


def test_shared_active_path_finds_the_common_node(path_index):
    resolver = ResourceResolver(resolved={"a1": "SYN-DEA-A", "a2": "SYN-DEA-B"})
    result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=path_index, resolver=resolver
    )
    assert result.state is EvidenceState.SUPPORT or result.availability is True
    assert "SYN-R2" in result.detail


def test_shared_active_path_score_is_not_one():
    """Deliberately not CD=1.0 for 'any shared active path' (anti-hub)."""
    resolver = ResourceResolver(resolved={"a1": "SYN-DEA-A", "a2": "SYN-DEA-B"})
    result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=build_active_path_index(ACTIVE_PATH_RECORDS), resolver=resolver
    )
    assert result.positive_score < 1.0
    assert result.positive_score > 0.0


def test_active_path_broad_hub_has_lower_specificity():
    """A node traversed by many distinct resources gets lower specificity."""
    narrow_records = [
        {"path_id": "p1", "resource_id": "r1", "nodes": ["r1", "HUB", "CORE"]},
        {"path_id": "p2", "resource_id": "r2", "nodes": ["r2", "HUB", "CORE"]},
    ]
    broad_records = narrow_records + [
        {"path_id": f"p{i}", "resource_id": f"r{i}", "nodes": [f"r{i}", "HUB", "CORE"]}
        for i in range(3, 103)
    ]
    narrow_index = build_active_path_index(narrow_records)
    broad_index = build_active_path_index(broad_records)

    resolver = ResourceResolver(resolved={"a1": "r1", "a2": "r2"})
    narrow_result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=narrow_index, resolver=resolver
    )
    broad_result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=broad_index, resolver=resolver
    )
    # Both paths share HUB and CORE; HUB/CORE traversed by more resources in
    # the broad index, so the broad witness should score lower or equal.
    assert broad_result.positive_score <= narrow_result.positive_score


def test_active_path_counts_distinct_resources_not_ecmp_paths():
    """A resource with 8 ECMP paths through a node counts once, not 8 times."""
    single_path_records = [
        {"path_id": "p1", "resource_id": "r1", "nodes": ["r1", "HUB"]},
        {"path_id": "p2", "resource_id": "r2", "nodes": ["r2", "HUB"]},
    ]
    ecmp_records = [
        {"path_id": f"p1_{i}", "resource_id": "r1", "nodes": ["r1", "HUB"]}
        for i in range(8)
    ] + [
        {"path_id": "p2", "resource_id": "r2", "nodes": ["r2", "HUB"]}
    ]

    single_index = build_active_path_index(single_path_records)
    ecmp_index = build_active_path_index(ecmp_records)

    # Scope(HUB) must be 2 distinct resources in both cases, not 9 in the ECMP one.
    assert len(single_index.traversing_resources("HUB")) == 2
    assert len(ecmp_index.traversing_resources("HUB")) == 2

    resolver = ResourceResolver(resolved={"a1": "r1", "a2": "r2"})
    single_result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=single_index, resolver=resolver
    )
    ecmp_result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=ecmp_index, resolver=resolver
    )
    assert single_result.positive_score == pytest.approx(ecmp_result.positive_score)


def test_active_path_uses_path_distance_not_graph_shortest_path():
    """A longer verified path must not be shortcut by a shorter graph path."""
    records = [
        {"path_id": "p1", "resource_id": "r1", "nodes": ["r1", "X", "Y", "Z", "HUB"]},
        {"path_id": "p2", "resource_id": "r2", "nodes": ["r2", "HUB"]},
    ]
    index = build_active_path_index(records)
    # The verified hop distance from r1 to HUB is 4, along the ordered path.
    assert index.min_hop_distance("r1", "HUB") == 4
    # Even if some hypothetical graph shortest path were 1, the channel must
    # use the verified path length, not a graph-adjacency shortcut.
    assert index.min_hop_distance("r1", "HUB") != 1


def test_active_path_missing_ordered_path_is_unavailable():
    """Membership without hop/order data yields CD=⊥, not a graph substitute."""
    records = [{"path_id": "p1", "resource_id": "r1"}]  # no 'nodes' key
    index = build_active_path_index(records)
    assert index.is_valid is False

    resolver = ResourceResolver(resolved={"a1": "r1", "a2": "r2"})
    result = evaluate_shared_active_path(
        alarm("a1"), alarm("a2"), path_index=index, resolver=resolver
    )
    assert result.state is EvidenceState.UNAVAILABLE


def test_active_path_n_is_scoped_to_path_universe_not_whole_inventory():
    """N_path,t must be resources with path observations, not total inventory."""
    records = [
        {"path_id": "p1", "resource_id": "r1", "nodes": ["r1", "HUB"]},
        {"path_id": "p2", "resource_id": "r2", "nodes": ["r2", "HUB"]},
    ]
    index = build_active_path_index(records)
    # Only 2 resources have path observations, regardless of how large the
    # full topology inventory might be.
    assert index.observed_resource_count == 2


# --------------------------------------------------------------------------
# Semantic tier vs numeric ordering (does not force CD ordering)
# --------------------------------------------------------------------------


def test_semantic_tier_does_not_force_numeric_score_order():
    """A narrow ancestor may score higher than a shared active-core-path."""
    resolver = ResourceResolver(
        resolved={"a1": "SYN-DEA-HN-01", "a2": "SYN-DEA-HN-02", "b1": "SYN-DEA-A", "b2": "SYN-DEA-B"}
    )
    hierarchy_local = build_directed_hierarchy(HIERARCHY_EDGES)
    ancestor_result = evaluate_shared_ancestor(
        alarm("a1"), alarm("a2"), hierarchy=hierarchy_local, resolver=resolver
    )

    # A broad active-path hub shared by many resources.
    broad_records = [
        {"path_id": "SYN-PATH-A", "resource_id": "SYN-DEA-A", "nodes": ["SYN-DEA-A", "SYN-CORE-X"]},
        {"path_id": "SYN-PATH-B", "resource_id": "SYN-DEA-B", "nodes": ["SYN-DEA-B", "SYN-CORE-X"]},
    ] + [
        {"path_id": f"p{i}", "resource_id": f"r{i}", "nodes": [f"r{i}", "SYN-CORE-X"]}
        for i in range(50)
    ]
    broad_index = build_active_path_index(broad_records)
    active_path_result = evaluate_shared_active_path(
        alarm("b1"), alarm("b2"), path_index=broad_index, resolver=resolver
    )

    # SHARED_ACTIVE_PATH is semantically stronger than SHARED_ANCESTOR, but
    # here the narrow ancestor scores higher because the active-path witness
    # is a broad hub. Both orderings must be structurally possible; the
    # engine must not force active_path_result > ancestor_result.
    assert ancestor_result.positive_score > active_path_result.positive_score
    # The semantic tier itself is still recorded and distinguishable.
    assert ancestor_result.derivation_tag == active_path_result.derivation_tag
    assert ancestor_result.dependency_semantic is DependencySemantic.SHARED_ANCESTOR
    assert (
        active_path_result.dependency_semantic
        is DependencySemantic.SHARED_ACTIVE_PATH
    )

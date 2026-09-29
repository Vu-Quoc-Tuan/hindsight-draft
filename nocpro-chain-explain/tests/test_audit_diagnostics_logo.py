from __future__ import annotations

import pytest

from audit import build_audit_graph
from audit_diagnostics.contracts import EdgeTransitionKind, GroupKey, RemovedGroupState
from audit_diagnostics.comparison import freeze_candidates
from audit_diagnostics.contracts import PopulationRegion
from audit_diagnostics.variants import LogoInvariantError, apply_logo, summarize_candidate_regions
from audit import Candidate, CandidateSource
from channels.base import ChannelValue
from libs.provenance import (
    ProvenanceClass,
    ProvenanceSubtype,
    baseline_eligibility,
)


def _key(tag: str, provenance=ProvenanceClass.POST_HOC, subtype=None) -> GroupKey:
    eligibility = baseline_eligibility(provenance, subtype)
    return GroupKey(
        derivation_tag=tag,
        provenance_class=provenance,
        explain_eligible=eligibility.explain_eligible,
        role_eligible=eligibility.role_eligible,
        audit_eligible=eligibility.audit_eligible,
    )


def _value(channel_id, tag, score, threshold=0.5, *, available=True, provenance=ProvenanceClass.POST_HOC, subtype=None):
    return ChannelValue(
        channel_id=channel_id,
        derivation_tag=tag,
        provenance_class=provenance,
        provenance_subtype=subtype,
        availability=available,
        positive_score=score if available else 0.0,
        threshold=threshold,
    )


def test_logo_separates_weight_increase_from_edge_deletion_at_two_group_boundary():
    pair = ("a", "b")
    values = {
        pair: [
            _value("c1", "g1", 1.0),
            _value("c2", "g2", 0.6),
            _value("c3", "g3", 0.0, threshold=0.5),
        ]
    }
    baseline = build_audit_graph(["a", "b", "c"], values)

    drop_neutral = apply_logo(["a", "b", "c"], values, baseline, _key("g3"))
    drop_first_support = apply_logo(["a", "b", "c"], values, baseline, _key("g1"))
    drop_second_support = apply_logo(["a", "b", "c"], values, baseline, _key("g2"))

    assert baseline.weight(*pair) == pytest.approx(1.6 / 3)
    assert drop_neutral.graph.weight(*pair) == pytest.approx(0.8)
    assert drop_neutral.transitions[0].transition is EdgeTransitionKind.RETAINED_WEIGHT_INCREASED
    assert drop_neutral.transitions[0].variant_support_group_count == 2
    assert drop_neutral.transitions[0].removed_group_state is RemovedGroupState.NEUTRAL
    for result in (drop_first_support, drop_second_support):
        assert result.graph.weight(*pair) == 0
        transition = result.transitions[0]
        assert transition.transition is EdgeTransitionKind.REMOVED_MIN_SUPPORT_GROUPS
        assert transition.baseline_support_group_count == 2
        assert transition.variant_support_group_count == 1
        assert transition.removed_group_state is RemovedGroupState.SUPPORT
    assert all(item.passed for item in drop_neutral.invariants)


def test_logo_of_unavailable_group_is_noop_and_preserves_isolates():
    pair = ("a", "b")
    values = {
        pair: [
            _value("c1", "g1", 1.0),
            _value("c2", "g2", 0.6),
            _value("c3", "g3", 0.9, available=False),
        ]
    }
    baseline = build_audit_graph(["a", "b", "isolate"], values)
    result = apply_logo(["a", "b", "isolate"], values, baseline, _key("g3"))

    assert result.graph.weight(*pair) == baseline.weight(*pair)
    assert result.graph.members == ("a", "b", "isolate")
    assert result.transitions[0].transition is EdgeTransitionKind.RETAINED_UNCHANGED
    assert result.transitions[0].removed_group_state is RemovedGroupState.UNAVAILABLE


def test_logo_uses_full_group_key_when_tags_match_but_provenance_differs():
    pair = ("a", "b")
    values = {
        pair: [
            _value("post", "same-tag", 1.0),
            _value(
                "external",
                "same-tag",
                0.7,
                provenance=ProvenanceClass.EXTERNAL_OPERATIONAL,
                subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
            ),
        ]
    }
    baseline = build_audit_graph(["a", "b"], values)

    result = apply_logo(
        ["a", "b"], values, baseline,
        _key("same-tag", ProvenanceClass.EXTERNAL_OPERATIONAL, ProvenanceSubtype.TOPOLOGY_EXTERNAL),
    )

    assert result.graph.edges == ()
    assert result.transitions[0].transition is EdgeTransitionKind.REMOVED_MIN_SUPPORT_GROUPS
    assert result.transitions[0].variant_support_group_count == 1


def test_logo_rejects_non_audit_eligible_group():
    with pytest.raises(ValueError, match="audit-eligible"):
        apply_logo([], {}, build_audit_graph([], {}), _key("behavior", ProvenanceClass.BEHAVIORAL))


def test_logo_boundary_summary_is_per_candidate_region_with_declared_denominator():
    members = ("a", "b", "c")
    values = {("a", "b"): [
        _value("c1", "g1", 0.9),
        _value("c2", "g2", 0.8),
        _value("c3", "g3", 0.0),
    ]}
    baseline = build_audit_graph(list(members), values)
    logo = apply_logo(list(members), values, baseline, _key("g3"))
    candidates = freeze_candidates(
        (Candidate(source=CandidateSource.ENTITY, members=frozenset({"a", "b"}), label="a-b"),),
        members,
        max_candidates=2,
    )
    summaries = summarize_candidate_regions(logo, baseline, candidates)
    all_pairs = next(item for item in summaries if item.region is PopulationRegion.ALL)
    cross = next(item for item in summaries if item.region is PopulationRegion.CROSS)
    assert all_pairs.population_pair_count == 3
    assert all_pairs.edge_transitions.boundary_pair_count == 1
    assert all_pairs.edge_transitions.boundary_population_count == 3
    assert all_pairs.edge_transitions.counts[EdgeTransitionKind.RETAINED_WEIGHT_INCREASED] == 1
    assert cross.population_pair_count == 2
    assert cross.edge_transitions.boundary_pair_count == 0
    assert cross.edge_transitions.boundary_population_count == 2

"""Normalized channel tests (§4/4A).

Central invariant: NEUTRAL (computed, below threshold) must stay distinct from
UNAVAILABLE (⊥). Collapsing them is what makes WEAK indistinguishable from
INSUFFICIENT DATA.
"""

from __future__ import annotations

import pytest

from channels import (
    SCORE_SAME_FAMILY,
    SCORE_SAME_NAME,
    AlarmTaxonomy,
    DelayDistribution,
    EvidenceState,
    ResourceResolver,
    TopologyGraph,
    evaluate_burst_channel,
    evaluate_delay_channel,
    evaluate_dep_hop_channel,
    evaluate_entity_channels,
    evaluate_semantic_channel,
    segment_bursts,
)
from channels.base import ChannelValue
from libs.contracts import IngestedAlarm
from libs.provenance import ProvenanceClass


def alarm(alarm_id: str, **fields) -> IngestedAlarm:
    raw = {k: str(v) for k, v in fields.items() if v is not None}
    return IngestedAlarm(
        alarm_id=alarm_id,
        snapshot_id="s1",
        raw=raw,
        alarm_name=fields.get("alarm_name"),
        device_code=fields.get("device_code"),
        node_reference=fields.get("node_reference"),
        canonical_start_time=fields.get("canonical_start_time"),
    )


# --------------------------------------------------------------------------
# Base contract
# --------------------------------------------------------------------------


def test_normalized_score_must_stay_in_range():
    """Raw system values such as 2.0 belong in M_pair, not a channel."""
    with pytest.raises(ValueError, match=r"outside \[0,1\]"):
        ChannelValue(
            channel_id="X",
            derivation_tag="x",
            provenance_class=ProvenanceClass.POST_HOC,
            availability=True,
            positive_score=2.0,
            threshold=0.5,
        )


def test_three_states_are_distinct():
    common = dict(
        channel_id="X",
        derivation_tag="x",
        provenance_class=ProvenanceClass.POST_HOC,
        threshold=0.5,
    )
    support = ChannelValue(availability=True, positive_score=0.9, **common)
    neutral = ChannelValue(availability=True, positive_score=0.1, **common)
    missing = ChannelValue(availability=False, positive_score=0.0, **common)

    assert support.state is EvidenceState.SUPPORT
    assert neutral.state is EvidenceState.NEUTRAL
    assert missing.state is EvidenceState.UNAVAILABLE
    # A neutral channel was computed; an unavailable one was not.
    assert neutral.supports is False
    assert missing.supports is False
    assert neutral.state is not missing.state


# --------------------------------------------------------------------------
# Entity channels
# --------------------------------------------------------------------------


def test_entity_channels_share_derivation_tag_per_field():
    """Channels from one field must share a derivation group (ADR-0009)."""
    a = alarm("a1", node_reference="R1", device_code="D1")
    b = alarm("a2", node_reference="R1", device_code="D2")
    values = {v.channel_id: v for v in evaluate_entity_channels(a, b)}
    assert values["E_reference"].derivation_tag == "reference"
    assert values["E_device"].derivation_tag == "device"
    # Different source fields => different groups.
    assert values["E_reference"].derivation_tag != values["E_device"].derivation_tag


def test_equal_entity_supports_and_different_is_neutral():
    a = alarm("a1", node_reference="R1")
    b = alarm("a2", node_reference="R1")
    c = alarm("a3", node_reference="R2")
    same = {v.channel_id: v for v in evaluate_entity_channels(a, b)}["E_reference"]
    diff = {v.channel_id: v for v in evaluate_entity_channels(a, c)}["E_reference"]
    assert same.state is EvidenceState.SUPPORT
    assert diff.state is EvidenceState.NEUTRAL


def test_missing_entity_field_is_unavailable_not_neutral():
    """A missing value cannot prove the entities differ."""
    a = alarm("a1", node_reference="R1")
    b = alarm("a2")
    value = {v.channel_id: v for v in evaluate_entity_channels(a, b)}["E_reference"]
    assert value.state is EvidenceState.UNAVAILABLE
    assert "missing" in value.detail


def test_remote_channel_is_separate_from_containment():
    a = alarm("a1", remote_node="X")
    b = alarm("a2", remote_node="X")
    values = {v.channel_id: v for v in evaluate_entity_channels(a, b)}
    assert values["E_remote"].derivation_tag == "remote"
    assert values["E_remote"].state is EvidenceState.SUPPORT


# --------------------------------------------------------------------------
# Semantic channel
# --------------------------------------------------------------------------


def test_semantic_ordinal_scale():
    a = alarm("a1", alarm_name="LINK DOWN")
    b = alarm("a2", alarm_name="LINK DOWN")
    assert evaluate_semantic_channel(a, b).positive_score == SCORE_SAME_NAME
    assert evaluate_semantic_channel(a, b).state is EvidenceState.SUPPORT


def test_semantic_family_meets_the_edge_threshold():
    """"edge <=> same family or above"."""
    taxonomy = AlarmTaxonomy(
        families={"LINK DOWN": "LINK", "PORT DOWN": "LINK"}, categories={}
    )
    a = alarm("a1", alarm_name="LINK DOWN")
    b = alarm("a2", alarm_name="PORT DOWN")
    value = evaluate_semantic_channel(a, b, taxonomy)
    assert value.positive_score == SCORE_SAME_FAMILY
    assert value.state is EvidenceState.SUPPORT


def test_semantic_category_is_below_the_edge_threshold():
    taxonomy = AlarmTaxonomy(
        families={"A": "F1", "B": "F2"}, categories={"A": "C1", "B": "C1"}
    )
    value = evaluate_semantic_channel(
        alarm("a1", alarm_name="A"), alarm("a2", alarm_name="B"), taxonomy
    )
    assert value.positive_score == pytest.approx(0.3)
    assert value.state is EvidenceState.NEUTRAL


def test_semantic_without_taxonomy_does_not_guess_family():
    """Family is not inferred from string similarity."""
    value = evaluate_semantic_channel(
        alarm("a1", alarm_name="LINK DOWN A"), alarm("a2", alarm_name="LINK DOWN B")
    )
    assert value.state is EvidenceState.NEUTRAL
    assert value.positive_score == 0.0


def test_missing_alarm_name_is_unavailable():
    value = evaluate_semantic_channel(alarm("a1", alarm_name="X"), alarm("a2"))
    assert value.state is EvidenceState.UNAVAILABLE


# --------------------------------------------------------------------------
# Temporal channels
# --------------------------------------------------------------------------


def test_burst_segmentation_is_contextual_not_global():
    """Two sites at the same instant must not share a burst."""
    alarms = [
        alarm("a1", location_code="SITE_A", canonical_start_time="2026-01-01T00:00:00"),
        alarm("a2", location_code="SITE_A", canonical_start_time="2026-01-01T00:00:10"),
        alarm("a3", location_code="SITE_B", canonical_start_time="2026-01-01T00:00:05"),
    ]
    segmentation = segment_bursts(alarms)
    assert segmentation.same_burst("a1", "a2") is True
    assert segmentation.same_burst("a1", "a3") is False


def test_silent_gap_splits_bursts():
    alarms = [
        alarm("a1", location_code="S", canonical_start_time="2026-01-01T00:00:00"),
        alarm("a2", location_code="S", canonical_start_time="2026-01-01T01:00:00"),
    ]
    segmentation = segment_bursts(alarms, silent_gap_seconds=60)
    assert segmentation.same_burst("a1", "a2") is False


def test_burst_without_context_is_unavailable():
    """No blocking context means the burst question is unanswerable."""
    alarms = [
        alarm("a1", canonical_start_time="2026-01-01T00:00:00"),
        alarm("a2", canonical_start_time="2026-01-01T00:00:01"),
    ]
    segmentation = segment_bursts(alarms)
    value = evaluate_burst_channel(alarms[0], alarms[1], segmentation)
    assert value.state is EvidenceState.UNAVAILABLE


def test_delay_uses_local_mass_not_cdf():
    """The bimodal case the spec calls out: dt=50s must not score high."""
    samples = tuple([2.0] * 50 + [100.0] * 50)
    distribution = DelayDistribution(
        relation="A->B", samples=samples, bandwidth_seconds=5.0
    )
    assert distribution.typicality(2.0) == pytest.approx(1.0)
    assert distribution.typicality(100.0) == pytest.approx(1.0)
    # A CDF-based score would return ~1.0 here; local mass returns 0.
    assert distribution.typicality(50.0) == pytest.approx(0.0)


def test_delay_is_directional():
    samples = (10.0, 11.0, 12.0)
    distribution = DelayDistribution(
        relation="A->B", samples=samples, bandwidth_seconds=1.0
    )
    a = alarm("a1", canonical_start_time="2026-01-01T00:00:00")
    b = alarm("a2", canonical_start_time="2026-01-01T00:00:11")
    forward = evaluate_delay_channel(
        a, b, distribution=distribution, threshold=0.5
    )
    backward = evaluate_delay_channel(
        b, a, distribution=distribution, threshold=0.5
    )
    assert forward.state is EvidenceState.SUPPORT
    # -11s is not in the learned forward distribution.
    assert backward.state is EvidenceState.NEUTRAL


def test_delay_without_distribution_is_unavailable():
    """Typicality cannot be invented from one observation."""
    a = alarm("a1", canonical_start_time="2026-01-01T00:00:00")
    b = alarm("a2", canonical_start_time="2026-01-01T00:00:05")
    value = evaluate_delay_channel(a, b, distribution=None, threshold=0.5)
    assert value.state is EvidenceState.UNAVAILABLE
    assert "no fitted delay distribution" in value.detail


# --------------------------------------------------------------------------
# Dep_hop
# --------------------------------------------------------------------------


def _graph() -> TopologyGraph:
    graph = TopologyGraph(relation_types=frozenset({"IP_ADJACENCY"}))
    graph.adjacency = {"R1": {"R2"}, "R2": {"R1", "R3"}, "R3": {"R2"}}
    return graph


def test_dep_hop_score_decays_with_distance():
    resolver = ResourceResolver(resolved={"a1": "R1", "a2": "R2", "a3": "R3"})
    one_hop = evaluate_dep_hop_channel(
        alarm("a1"), alarm("a2"), graph=_graph(), resolver=resolver
    )
    two_hop = evaluate_dep_hop_channel(
        alarm("a1"), alarm("a3"), graph=_graph(), resolver=resolver
    )
    assert one_hop.positive_score == pytest.approx(0.5)
    assert two_hop.positive_score == pytest.approx(1 / 3)
    assert one_hop.positive_score > two_hop.positive_score


def test_unmapped_alarm_forces_dep_hop_unavailable():
    """The DEHL01/DEHT01 case: unmapped => ⊥, never 0.0 (ADR-0032)."""
    resolver = ResourceResolver(resolved={"a1": "R1"})
    value = evaluate_dep_hop_channel(
        alarm("a1"), alarm("a2"), graph=_graph(), resolver=resolver
    )
    assert value.state is EvidenceState.UNAVAILABLE
    assert "mapping unresolved" in value.detail


def test_resolver_ignores_unmapped_and_ambiguous_status():
    from libs.contracts import load_package

    package = load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "m",
                "source_kind": "REAL_EXPORT_REPLAY",
                "produced_at": "2026-01-01T00:00:00",
                "schema_version": "v1",
            },
            "topology": {
                "mappings": [
                    {"alarm_id": "a1", "resource_id": "R1", "mapping_status": "EXACT"},
                    {"alarm_id": "a2", "resource_id": "R2", "mapping_status": "AMBIGUOUS"},
                    {"alarm_id": "a3", "mapping_status": "UNMAPPED"},
                ]
            },
        }
    )
    resolver = ResourceResolver.from_package(package)
    assert resolver.resource_of("a1") == "R1"
    assert resolver.resource_of("a2") is None
    assert resolver.resource_of("a3") is None


def test_dep_hop_beyond_d_max_is_unavailable():
    resolver = ResourceResolver(resolved={"a1": "R1", "a3": "R3"})
    value = evaluate_dep_hop_channel(
        alarm("a1"), alarm("a3"), graph=_graph(), resolver=resolver, d_max=1
    )
    assert value.state is EvidenceState.UNAVAILABLE


def test_relation_families_are_not_mixed():
    """PHYSICAL / LOGICAL / SERVICE must stay separate graphs."""
    from libs.contracts import load_package

    from channels import LOGICAL_RELATIONS, PHYSICAL_RELATIONS, build_topology_graph

    package = load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "m",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-01-01T00:00:00",
                "schema_version": "v1",
            },
            "topology": {
                "edges": [
                    {
                        "edge_id": "e1",
                        "source_resource_id": "P1",
                        "target_resource_id": "P2",
                        "relation_type": "IP_ADJACENCY",
                        "directed": False,
                    },
                    {
                        "edge_id": "e2",
                        "source_resource_id": "L1",
                        "target_resource_id": "L2",
                        "relation_type": "LOGICAL_DEPENDENCY",
                        "directed": True,
                    },
                ]
            },
        }
    )
    physical = build_topology_graph(package, relation_types=PHYSICAL_RELATIONS)
    logical = build_topology_graph(package, relation_types=LOGICAL_RELATIONS)
    assert set(physical.adjacency) == {"P1", "P2"}
    assert set(logical.adjacency) == {"L1", "L2"}
    # Undirected adjacency stays undirected; the logical graph is directed.
    assert physical.directed is False
    assert logical.directed is True


def test_mixed_topology_provenance_fails_closed_instead_of_one_group():
    from libs.contracts import load_package
    from channels import PHYSICAL_RELATIONS, build_topology_graph

    package = load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "m",
                "source_kind": "REAL_EXPORT_REPLAY",
                "produced_at": "2026-01-01T00:00:00",
            },
            "topology": {
                "edges": [
                    {
                        "source_resource_id": "R1",
                        "target_resource_id": "R2",
                        "relation_type": "IP_ADJACENCY",
                        "directed": False,
                        "provenance_class": "EXTERNAL_OPERATIONAL",
                        "provenance_subtype": "TOPOLOGY_EXTERNAL",
                    },
                    {
                        "source_resource_id": "R2",
                        "target_resource_id": "R3",
                        "relation_type": "IP_ADJACENCY",
                        "directed": False,
                        "provenance_class": "POST_HOC",
                    },
                ]
            },
        }
    )

    graph = build_topology_graph(package, relation_types=PHYSICAL_RELATIONS)

    assert graph.adjacency == {}
    assert "mixed provenance" in graph.unavailable_reason

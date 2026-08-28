"""spec_sanity — derivation-group homogeneity invariant (cases 32-34).

A failure here means the implementation contradicts frozen methodology
(ADR-0009, ADR-0010, ADR-0027), not merely that a unit test broke.
"""

from __future__ import annotations

import pytest

from libs.provenance import (
    DerivationGroup,
    EffectiveGroupKey,
    NormalizedChannel,
    ProvenanceClass,
    ProvenanceSubtype,
    audit_groups,
    build_derivation_groups,
    role_groups,
)

DEP_HOP = "dependency_hop"
REFERENCE = "reference"


def _dep_hop_from_inventory(**overrides) -> NormalizedChannel:
    """Dep_hop over topology from external inventory/NMS."""
    defaults = dict(
        channel_id="dep_hop_inventory",
        derivation_tag=DEP_HOP,
        provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
        provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
        availability=True,
        supports=True,
        positive_score=0.9,
    )
    defaults.update(overrides)
    return NormalizedChannel(**defaults)


def _dep_hop_from_alarm_data(**overrides) -> NormalizedChannel:
    """Dep_hop inferred from the alarm data itself, hence POST_HOC."""
    defaults = dict(
        channel_id="dep_hop_alarm_derived",
        derivation_tag=DEP_HOP,
        provenance_class=ProvenanceClass.POST_HOC,
        provenance_subtype=None,
        availability=True,
        supports=True,
        positive_score=0.8,
    )
    defaults.update(overrides)
    return NormalizedChannel(**defaults)


# --------------------------------------------------------------------------
# Case 32
# --------------------------------------------------------------------------


def test_same_derivation_tag_different_provenance_split_groups():
    """Same 'dependency-hop' concept, different provenance => different groups."""
    channels = [_dep_hop_from_inventory(), _dep_hop_from_alarm_data()]
    groups = build_derivation_groups(channels)

    assert len(groups) == 2, (
        "channels sharing derivation_tag but differing in provenance class must "
        "form different effective derivation groups"
    )
    assert {g.provenance_class for g in groups} == {
        ProvenanceClass.EXTERNAL_OPERATIONAL,
        ProvenanceClass.POST_HOC,
    }
    # The raw derivation tag is still shared; only the effective key differs.
    assert {g.key.derivation_tag for g in groups} == {DEP_HOP}


def test_same_tag_same_provenance_stays_one_group():
    """Dedup must still work: one derivation = at most one vote (ADR-0009)."""
    channels = [
        NormalizedChannel(
            channel_id=f"reference_view_{i}",
            derivation_tag=REFERENCE,
            provenance_class=ProvenanceClass.POST_HOC,
            supports=True,
            positive_score=0.5 + i / 10,
        )
        for i in range(3)
    ]
    groups = build_derivation_groups(channels)
    assert len(groups) == 1
    assert len(groups[0].channels) == 3
    # Three channels, one vote.
    assert groups[0].supports is True
    assert groups[0].positive_score == pytest.approx(0.7)


def test_external_subtypes_with_different_eligibility_split():
    """Both EXTERNAL_OPERATIONAL, but TICKET is not audit-eligible."""
    topology = NormalizedChannel(
        channel_id="topology",
        derivation_tag="shared_context",
        provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
        provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
    )
    ticket = NormalizedChannel(
        channel_id="ticket",
        derivation_tag="shared_context",
        provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
        provenance_subtype=ProvenanceSubtype.TICKET,
    )
    groups = build_derivation_groups([topology, ticket])
    assert len(groups) == 2, (
        "same class and tag but different eligibility signature must still split; "
        "provenance class alone is not a sufficient homogeneity key"
    )
    assert {g.audit_eligible for g in groups} == {True, False}


# --------------------------------------------------------------------------
# Case 33
# --------------------------------------------------------------------------


def test_group_has_single_eligibility_signature():
    """Every group must expose exactly one eligibility signature."""
    channels = [
        _dep_hop_from_inventory(),
        _dep_hop_from_alarm_data(),
        NormalizedChannel(
            channel_id="history",
            derivation_tag="grouping_history",
            provenance_class=ProvenanceClass.BEHAVIORAL,
        ),
        NormalizedChannel(
            channel_id="reference",
            derivation_tag=REFERENCE,
            provenance_class=ProvenanceClass.POST_HOC,
        ),
    ]
    for group in build_derivation_groups(channels):
        signatures = group.eligibility_signatures()
        assert len(signatures) == 1, (
            f"group {group.key.derivation_tag!r} mixes eligibility signatures "
            f"{signatures}; audit_eligible(g) would be ambiguous"
        )
        assert signatures == {group.eligibility.as_tuple()}


def test_unavailable_non_eligible_channel_cannot_make_group_audit_available():
    """The concrete risk availability_g = max availability_k could create."""
    audit_ready = _dep_hop_from_inventory(availability=False, supports=False)
    behavioral = NormalizedChannel(
        channel_id="history",
        derivation_tag=DEP_HOP,
        provenance_class=ProvenanceClass.BEHAVIORAL,
        availability=True,
        supports=True,
    )
    groups = build_derivation_groups([audit_ready, behavioral])

    # They are separate groups, so the available BEHAVIORAL channel cannot lend
    # its availability to the audit-eligible group.
    assert len(groups) == 2
    assert audit_groups(groups) == [], (
        "an available but non-audit-eligible channel must not put a group into "
        "G_audit"
    )


def test_g_audit_requires_both_eligibility_and_availability():
    """G_audit(i,j) = {g : audit_eligible(g)=1 AND availability_g(i,j)=1}."""
    eligible_available = _dep_hop_from_inventory()
    eligible_unavailable = NormalizedChannel(
        channel_id="reference",
        derivation_tag=REFERENCE,
        provenance_class=ProvenanceClass.POST_HOC,
        availability=False,
    )
    ineligible_available = NormalizedChannel(
        channel_id="system_pair",
        derivation_tag="system_pair",
        provenance_class=ProvenanceClass.SYSTEM_FACT,
        availability=True,
        supports=True,
    )
    groups = build_derivation_groups(
        [eligible_available, eligible_unavailable, ineligible_available]
    )
    selected = audit_groups(groups)
    assert len(selected) == 1
    assert selected[0].provenance_class is ProvenanceClass.EXTERNAL_OPERATIONAL


def test_available_but_unsupporting_group_stays_in_the_denominator():
    """UNAVAILABLE != NEUTRAL: a neutral group still counts in the denominator."""
    supporting = _dep_hop_from_inventory()
    neutral = NormalizedChannel(
        channel_id="reference",
        derivation_tag=REFERENCE,
        provenance_class=ProvenanceClass.POST_HOC,
        availability=True,
        supports=False,
    )
    groups = build_derivation_groups([supporting, neutral])
    denominator = audit_groups(groups)
    assert len(denominator) == 2
    assert sum(1 for g in denominator if g.supports) == 1


def test_system_fact_is_never_audit_or_role_eligible():
    """SYSTEM_FACT must not strengthen G*_audit (ADR-0010)."""
    groups = build_derivation_groups(
        [
            NormalizedChannel(
                channel_id="m_pair",
                derivation_tag="system_pair",
                provenance_class=ProvenanceClass.SYSTEM_FACT,
                availability=True,
                supports=True,
                positive_score=2.0,
            )
        ]
    )
    assert audit_groups(groups) == []
    assert role_groups(groups) == []


def test_behavioral_explains_but_does_not_audit_or_role():
    groups = build_derivation_groups(
        [
            NormalizedChannel(
                channel_id="history",
                derivation_tag="grouping_history",
                provenance_class=ProvenanceClass.BEHAVIORAL,
                availability=True,
                supports=True,
            )
        ]
    )
    assert groups[0].explain_eligible is True
    assert audit_groups(groups) == []
    assert role_groups(groups) == []


# --------------------------------------------------------------------------
# Case 34
# --------------------------------------------------------------------------


def test_chaining_usage_does_not_change_explain_role_audit_grouping():
    """chaining_usage constrains Validate only (ADR-0010)."""
    unknown = _dep_hop_from_inventory(
        channel_id="topology_unknown_usage", chaining_usage="UNKNOWN"
    )
    not_used = _dep_hop_from_inventory(
        channel_id="topology_not_used", chaining_usage="CONFIRMED_NOT_USED"
    )
    groups = build_derivation_groups([unknown, not_used])

    assert len(groups) == 1, (
        "chaining_usage must not be part of the homogeneity key; differing usage "
        "cannot split an effective derivation group"
    )
    assert len(groups[0].channels) == 2
    assert groups[0].audit_eligible is True


def test_source_kind_does_not_change_grouping():
    """source_kind is also Validate-only, so it must not split groups."""
    real = _dep_hop_from_inventory(
        channel_id="topology_real", source_kind="REAL_EXPORT_REPLAY"
    )
    synthetic = _dep_hop_from_inventory(
        channel_id="topology_synthetic", source_kind="SYNTHETIC_TEST"
    )
    groups = build_derivation_groups([real, synthetic])
    assert len(groups) == 1
    assert len(groups[0].channels) == 2


def test_grouping_key_excludes_validate_only_dimensions():
    """Structural guard: the key must not gain Validate-only fields."""
    fields = set(EffectiveGroupKey.__dataclass_fields__)
    assert fields == {
        "derivation_tag",
        "provenance_class",
        "explain_eligible",
        "role_eligible",
        "audit_eligible",
    }
    assert "source_kind" not in fields
    assert "chaining_usage" not in fields
    assert "quality_status" not in fields


def test_changing_usage_leaves_audit_membership_identical():
    """Same evidence, different usage => identical Audit outcome."""

    def build(usage: str) -> list[DerivationGroup]:
        return build_derivation_groups(
            [
                _dep_hop_from_inventory(chaining_usage=usage),
                NormalizedChannel(
                    channel_id="reference",
                    derivation_tag=REFERENCE,
                    provenance_class=ProvenanceClass.POST_HOC,
                    availability=True,
                    supports=True,
                    positive_score=0.6,
                    chaining_usage=usage,
                ),
            ]
        )

    unknown_keys = [g.key for g in audit_groups(build("UNKNOWN"))]
    not_used_keys = [g.key for g in audit_groups(build("CONFIRMED_NOT_USED"))]
    used_keys = [g.key for g in audit_groups(build("CONFIRMED_USED"))]
    assert unknown_keys == not_used_keys == used_keys
    assert len(unknown_keys) == 2


def test_grouping_is_deterministic():
    channels = [
        _dep_hop_from_alarm_data(),
        _dep_hop_from_inventory(),
        NormalizedChannel(
            channel_id="reference",
            derivation_tag=REFERENCE,
            provenance_class=ProvenanceClass.POST_HOC,
        ),
    ]
    first = [g.key for g in build_derivation_groups(channels)]
    second = [g.key for g in build_derivation_groups(list(reversed(channels)))]
    assert first == second


# --------------------------------------------------------------------------
# Audit edge existence (spec_sanity extension): the >=2 group rule is enforced
# at the audit-graph level, not just at the group-selection level.
# --------------------------------------------------------------------------


def test_audit_edge_requires_two_distinct_audit_eligible_groups():
    """The anti single-view-edge rule, enforced where edges are actually built."""
    import sys
    from pathlib import Path

    analysis_worker = Path(__file__).resolve().parents[2] / "services" / "analysis-worker"
    if str(analysis_worker) not in sys.path:
        sys.path.insert(0, str(analysis_worker))

    from audit import build_audit_graph
    from channels.base import ChannelValue

    def cv(channel_id, tag, score=1.0):
        return ChannelValue(
            channel_id=channel_id,
            derivation_tag=tag,
            provenance_class=ProvenanceClass.POST_HOC,
            availability=True,
            positive_score=score,
            threshold=0.5,
        )

    one_group = {("a", "b"): [cv("S", "semantic")]}
    assert build_audit_graph(["a", "b"], one_group).edges == ()

    two_groups = {("a", "b"): [cv("S", "semantic"), cv("E_site", "site")]}
    assert len(build_audit_graph(["a", "b"], two_groups).edges) == 1

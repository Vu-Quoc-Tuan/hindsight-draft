"""Contract validation only; no channel evaluation or diagnostic execution."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from audit_diagnostics.contracts import (
    ApplicabilityCounts, CandidateComparison, CandidateOrigin, CandidateScore,
    CandidateScoreStatus, ComputationStatus, CoverageRatios, CoverageRow,
    DiagnosticReason, DiagnosticReport, EdgeTransition, EdgeTransitionKind, EdgeTransitionSummary,
    FrozenCandidate, FrozenManifest, GroupKey, InputBinding, InvocationStatus,
    MaterialityPolicy, MaterialityStatus, PairKey, PairUniverse, PopulationRegion,
    Ratio, RatioStatus, ReasonOrigin, ResourceLimits, RunStatus, ScopeDecision,
    ScopeEvidenceStateCount, ScopeState, SourceBinding, VariantKind, VariantResult, VariantSpec, WinnerStatus,
)
from channels.base import EvidenceState
from libs.provenance import EffectiveGroupKey, ProvenanceClass, ProvenanceSubtype
from libs.provenance.eligibility import baseline_eligibility


DIGEST = "a" * 64


def _counts(**changes) -> ApplicabilityCounts:
    data = dict(total=10, applicable=6, not_applicable=2, unknown_applicability=2,
                available=4, unavailable=2, support=3, neutral=1)
    return ApplicabilityCounts(**(data | changes))


def _key(**changes) -> GroupKey:
    data = dict(derivation_tag="fixture", provenance_class=ProvenanceClass.POST_HOC,
                explain_eligible=True, role_eligible=True, audit_eligible=True)
    return GroupKey(**(data | changes))


def _binding() -> InputBinding:
    return InputBinding(snapshot_id="s1", snapshot_version="v1", chain_id="c1",
                        snapshot_ref="/tmp/snapshot.json", input_bytes_digest=DIGEST,
                        canonical_package_digest=DIGEST, member_fingerprint=DIGEST)


def _manifest(**changes) -> FrozenManifest:
    data = dict(
        run_id="r1", prepared_at="2026-09-27T00:00:00Z", analysis_version="a1",
        baseline_policy_version="b1", input_binding=_binding(),
        source_binding=SourceBinding(git_commit="b" * 40, dirty=True,
                                     file_digests={"audit/graph.py": DIGEST}, source_bundle_digest=DIGEST),
        analysis_config_ref="thresholds.yaml", analysis_config_digest=DIGEST,
        scope_policy_ref="scope.yaml", scope_policy_id="s1", scope_policy_version="1",
        scope_policy_digest=DIGEST, group_registry_digest=DIGEST,
        execution_profile_digest=DIGEST, candidate_generation_config_digest=DIGEST,
        experiment_ref="/tmp/experiment.json", experiment_digest=DIGEST,
        audit_epsilon_phi=0.3,
        audit_epsilon_phi_source="config/thresholds/v1.yaml:audit.global_weak_baseline",
        variants=(VariantSpec(variant_id="baseline", kind=VariantKind.BASELINE),),
    )
    return FrozenManifest(**(data | changes))


def test_unordered_pair_identity_and_distinct_endpoints():
    assert PairKey(left="b", right="a") == PairKey(left="a", right="b")
    with pytest.raises(ValidationError, match="distinct"):
        PairKey(left="a", right="a")
    with pytest.raises(ValidationError):
        PairKey(left="", right="a")


@pytest.mark.parametrize("members,pairs,message", [
    (("a", "a"), (), "duplicate member"),
    (("a", "b"), (("a", "b"), ("b", "a")), "duplicate unordered"),
    (("a", "b"), (("a", "c"),), "outside member"),
    (("a", "b", "c"), (("a", "b"),), "complete unordered"),
])
def test_pair_universe_rejects_invalid_or_incomplete_exact_population(members, pairs, message):
    with pytest.raises(ValidationError, match=message):
        PairUniverse(members=members, pairs=tuple(PairKey(left=a, right=b) for a, b in pairs),
                     computation_status=ComputationStatus.EXACT)


def test_exact_population_counts_non_edges_and_partial_is_explicit():
    universe = PairUniverse(members=("a", "b", "c"),
                            pairs=(PairKey(left="a", right="b"), PairKey(left="b", right="c"),
                                   PairKey(left="a", right="c")),
                            computation_status=ComputationStatus.EXACT)
    assert len(universe.pairs) == 3
    assert PairUniverse(members=("a", "b"), pairs=(),
                        computation_status=ComputationStatus.PARTIAL).pairs == ()


@pytest.mark.parametrize("changes,message", [
    ({"total": 11}, "partition total"),
    ({"available": 7}, "exceed applicable"),
    ({"support": 2}, r"support \+ neutral"),
    ({"unavailable": 1}, "applicable - available"),
    ({"neutral": -1}, "greater than or equal"),
    ({"total": True}, "valid integer"),
    ({"total": "10"}, "valid integer"),
])
def test_scope_and_availability_count_invariants(changes, message):
    with pytest.raises(ValidationError, match=message):
        _counts(**changes)


def test_coverage_uses_conditional_applicable_denominator():
    ratios = CoverageRatios.from_counts(_counts())
    assert ratios.coverage.value == 4 / 6
    assert ratios.coverage.denominator == 6
    assert ratios.applicability_share.value == 6 / 10
    assert ratios.unknown_scope_share.value == 2 / 10
    assert ratios.not_applicable_share.value == 2 / 10


def test_zero_denominators_are_null_and_keep_specific_status():
    counts = _counts(total=0, applicable=0, not_applicable=0, unknown_applicability=0,
                     available=0, unavailable=0, support=0, neutral=0)
    ratios = CoverageRatios.from_counts(counts)
    assert ratios.coverage.value is None
    assert ratios.coverage.status is RatioStatus.NO_APPLICABLE_PAIRS
    assert ratios.applicability_share.status is RatioStatus.EMPTY_POPULATION
    with pytest.raises(ValidationError, match="zero denominator"):
        Ratio(numerator=0, denominator=0, value=0.0, status=RatioStatus.AVAILABLE)
    with pytest.raises(ValidationError, match="match numerator"):
        Ratio(numerator=1, denominator=2, value=0.25, status=RatioStatus.AVAILABLE)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
def test_all_numeric_metric_inputs_must_be_finite_and_non_boolean(value):
    with pytest.raises(ValidationError):
        MaterialityPolicy(delta_phi=value)
    with pytest.raises(ValidationError):
        Ratio(numerator=1, denominator=2, value=value, status=RatioStatus.AVAILABLE)


def test_nested_json_metadata_rejects_nonfinite_values():
    with pytest.raises(ValidationError):
        VariantSpec(variant_id="config", kind=VariantKind.CHANNEL_CONFIG,
                    parameters={"threshold": {"nested": [float("nan")]}})


def test_canonical_evidence_state_is_reused_and_invocation_is_separate():
    evaluated = ScopeDecision(scope=ScopeState.APPLICABLE, rule_ids=("all",),
                              invocation=InvocationStatus.EVALUATED, evidence_state=EvidenceState.UNAVAILABLE)
    assert evaluated.evidence_state is EvidenceState.UNAVAILABLE
    for scope in ScopeState:
        if scope is ScopeState.UNKNOWN_APPLICABILITY:
            continue
        with pytest.raises(ValidationError, match="EVALUATED"):
            ScopeDecision(scope=scope, rule_ids=(), invocation=InvocationStatus.NOT_EVALUATED,
                          evidence_state=EvidenceState.UNAVAILABLE)
    with pytest.raises(ValidationError, match="APPLICABLE"):
        ScopeDecision(scope=ScopeState.NOT_APPLICABLE, rule_ids=("outside",),
                      invocation=InvocationStatus.EVALUATED, evidence_state=EvidenceState.NEUTRAL)


@pytest.mark.parametrize("code", ["SCOPE_METADATA_MISSING", "SCOPE_METADATA_CONFLICT", "SCOPE_RULE_UNDEFINED"])
def test_unknown_scope_retains_primary_scope_reason(code):
    decision = ScopeDecision(scope=ScopeState.UNKNOWN_APPLICABILITY, rule_ids=(),
                             invocation=InvocationStatus.NOT_EVALUATED, evidence_state=None,
                             primary_reason=DiagnosticReason(code=code, origin=ReasonOrigin.SCOPE))
    assert decision.primary_reason.code == code


def test_unknown_scope_does_not_accept_availability_reason():
    with pytest.raises(ValidationError, match="primary scope reason"):
        ScopeDecision(scope=ScopeState.UNKNOWN_APPLICABILITY, rule_ids=(),
                      invocation=InvocationStatus.NOT_EVALUATED, evidence_state=None,
                      primary_reason=DiagnosticReason(code="TOPOLOGY_MISSING", origin=ReasonOrigin.DATA))


@pytest.mark.parametrize("evidence_state", [EvidenceState.SUPPORT, EvidenceState.NEUTRAL])
def test_unknown_scope_preserves_available_evaluated_evidence(evidence_state):
    decision = ScopeDecision(
        scope=ScopeState.UNKNOWN_APPLICABILITY, rule_ids=(),
        invocation=InvocationStatus.EVALUATED, evidence_state=evidence_state,
        primary_reason=DiagnosticReason(code="SCOPE_RULE_UNDEFINED", origin=ReasonOrigin.SCOPE),
    )
    assert decision.scope is ScopeState.UNKNOWN_APPLICABILITY
    assert decision.evidence_state is evidence_state
    assert decision.invocation is InvocationStatus.EVALUATED
    with pytest.raises(ValidationError, match="cannot be NOT_APPLICABLE"):
        ScopeDecision(
            scope=ScopeState.NOT_APPLICABLE, rule_ids=("outside",),
            invocation=InvocationStatus.EVALUATED, evidence_state=evidence_state,
        )


def test_group_identity_preserves_all_canonical_key_fields():
    native = EffectiveGroupKey(derivation_tag="fixture", provenance_class=ProvenanceClass.POST_HOC,
                               explain_eligible=True, role_eligible=True, audit_eligible=True)
    assert GroupKey.from_effective_key(native).to_effective_key() == native
    assert _key() != _key(derivation_tag="another-source")
    assert _key() != _key(provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL)
    assert set(_key().model_dump()) == {
        "derivation_tag", "provenance_class", "explain_eligible", "role_eligible", "audit_eligible",
    }
    # The booleans are part of identity but cannot vary independently of the
    # canonical signature. Reject inconsistent edits rather than ignoring them.
    for field in ("explain_eligible", "role_eligible", "audit_eligible"):
        with pytest.raises(ValidationError, match="canonical baseline signature"):
            _key(**{field: False})


@pytest.mark.parametrize("provenance_class", list(ProvenanceClass))
@pytest.mark.parametrize("subtype", [None, *ProvenanceSubtype])
def test_group_key_accepts_each_canonical_provenance_signature(provenance_class, subtype):
    signature = baseline_eligibility(provenance_class, subtype)
    native = EffectiveGroupKey(derivation_tag="fixture", provenance_class=provenance_class,
                               explain_eligible=signature.explain_eligible,
                               role_eligible=signature.role_eligible,
                               audit_eligible=signature.audit_eligible)
    assert GroupKey.from_effective_key(native).to_effective_key() == native


@pytest.mark.parametrize("provenance_class", [ProvenanceClass.BEHAVIORAL, ProvenanceClass.SYSTEM_FACT])
def test_group_key_rejects_fabricated_positive_audit_eligibility(provenance_class):
    with pytest.raises(ValidationError, match="canonical baseline signature"):
        _key(provenance_class=provenance_class)


def test_coverage_row_checks_identity_ratios_and_disjoint_invocation():
    def cell(scope, state, count):
        return ScopeEvidenceStateCount(scope=scope, evidence_state=state, count=count,
                                       invocation=InvocationStatus.EVALUATED if state is not None else InvocationStatus.NOT_EVALUATED)

    row = dict(population_id="all", region=PopulationRegion.ALL, channel_id="S",
               scope_policy_id="scope1", rule_ids=("all",), counts=_counts(),
               ratios=CoverageRatios.from_counts(_counts()), computation_status=ComputationStatus.EXACT,
               scope_evidence_state_counts=(cell(ScopeState.APPLICABLE, EvidenceState.SUPPORT, 3),
                                            cell(ScopeState.APPLICABLE, EvidenceState.NEUTRAL, 1),
                                            cell(ScopeState.APPLICABLE, EvidenceState.UNAVAILABLE, 2),
                                            cell(ScopeState.NOT_APPLICABLE, None, 2),
                                            cell(ScopeState.UNKNOWN_APPLICABILITY, EvidenceState.SUPPORT, 1),
                                            cell(ScopeState.UNKNOWN_APPLICABILITY, EvidenceState.NEUTRAL, 1)))
    assert CoverageRow(**row).counts.total == 10
    with pytest.raises(ValidationError, match="exactly one"):
        CoverageRow(**(row | {"effective_group_key": _key()}))
    with pytest.raises(ValidationError, match="invocation counts"):
        CoverageRow(**(row | {"invocation_status_counts": {InvocationStatus.EVALUATED: 9}}))
    with pytest.raises(ValidationError, match="ratios must match"):
        CoverageRow(**(row | {"ratios": CoverageRatios.from_counts(_counts(support=2, neutral=0,
                                                                 available=2, unavailable=4))}))
    with pytest.raises(ValidationError, match="partition total"):
        CoverageRow(**(row | {"scope_evidence_state_counts": row["scope_evidence_state_counts"][:-1]}))
    with pytest.raises(ValidationError, match="duplicate scope"):
        CoverageRow(**(row | {"scope_evidence_state_counts": row["scope_evidence_state_counts"] +
                             (row["scope_evidence_state_counts"][0],)}))
    with pytest.raises(ValidationError, match="match scope totals"):
        CoverageRow(**(row | {"scope_evidence_state_counts":
                             (cell(ScopeState.APPLICABLE, EvidenceState.SUPPORT, 4),) +
                             row["scope_evidence_state_counts"][1:-1]}))
    with pytest.raises(ValidationError, match="conditional support/neutral"):
        CoverageRow(**(row | {"scope_evidence_state_counts":
                             (cell(ScopeState.APPLICABLE, EvidenceState.SUPPORT, 2),
                              cell(ScopeState.APPLICABLE, EvidenceState.NEUTRAL, 2)) +
                             row["scope_evidence_state_counts"][2:]}))
    with pytest.raises(ValidationError, match="match invocation counts"):
        CoverageRow(**(row | {"invocation_status_counts": {InvocationStatus.EVALUATED: 10}}))
    actual = CoverageRow(**row)
    assert actual.counts.available == 4  # UNKNOWN SUPPORT/NEUTRAL remain observed, excluded from numerator.
    assert sum(cell.count for cell in actual.scope_evidence_state_counts) == actual.counts.total


@pytest.mark.parametrize("state", [EvidenceState.SUPPORT, EvidenceState.NEUTRAL, EvidenceState.UNAVAILABLE, None])
def test_cross_counts_preserve_unknown_scope_for_every_observed_or_uninvoked_state(state):
    invocation = InvocationStatus.EVALUATED if state is not None else InvocationStatus.NOT_EVALUATED
    cell = ScopeEvidenceStateCount(scope=ScopeState.UNKNOWN_APPLICABILITY,
                                   invocation=invocation, evidence_state=state, count=1)
    assert cell.evidence_state is state
    assert ScopeEvidenceStateCount.model_validate_json(cell.model_dump_json()) == cell


def test_cross_count_requires_evidence_only_for_evaluated_cell():
    with pytest.raises(ValidationError, match="EVALUATED cross-count cells"):
        ScopeEvidenceStateCount(scope=ScopeState.UNKNOWN_APPLICABILITY,
                                invocation=InvocationStatus.NOT_EVALUATED,
                                evidence_state=EvidenceState.UNAVAILABLE, count=1)


def test_delta_is_optional_and_must_exceed_numeric_tolerance():
    assert MaterialityPolicy().delta_phi is None
    assert MaterialityPolicy(delta_phi=0.005).approved_by is None
    for delta in (0.0, -1.0, 1e-12, 1e-13):
        with pytest.raises(ValidationError):
            MaterialityPolicy(delta_phi=delta)


def test_pure_logo_uses_one_full_audit_eligible_key_without_config_changes():
    assert VariantSpec(variant_id="logo", kind=VariantKind.LOGO, excluded_group=_key()).excluded_group == _key()
    for changes in ({}, {"excluded_group": _key(provenance_class=ProvenanceClass.BEHAVIORAL,
                                               role_eligible=False, audit_eligible=False)},
                    {"excluded_group": _key(), "parameters": {"threshold": 0.9}}):
        with pytest.raises(ValidationError):
            VariantSpec(variant_id="logo", kind=VariantKind.LOGO, **changes)


def test_manifest_is_validated_nested_roundtrip_and_has_no_fabricated_approval():
    manifest = _manifest()
    assert FrozenManifest.model_validate_json(manifest.model_dump_json()) == manifest
    assert manifest.materiality_policy.approved_by is None
    assert manifest.limits.max_variants == 32
    assert "properties" in FrozenManifest.model_json_schema()
    with pytest.raises(ValidationError):
        FrozenManifest.model_validate(manifest.model_dump() | {"unexpected": True})


@pytest.mark.parametrize("changes,message", [
    ({"prepared_at": "2026-09-27T00:00:00"}, "timezone-aware UTC"),
    ({"prepared_at": "2026-09-27T00:00:00+07:00"}, "timezone-aware UTC"),
    ({"variants": ()}, "exactly one baseline"),
    ({"variants": (VariantSpec(variant_id="baseline", kind=VariantKind.BASELINE),) * 2}, "duplicate variant"),
    ({"scope_policy_digest": "not-a-digest"}, "pattern"),
])
def test_manifest_requires_pinned_identity_and_unique_declared_variants(changes, message):
    with pytest.raises(ValidationError, match=message):
        _manifest(**changes)


def test_manifest_variant_budget_includes_baseline():
    with pytest.raises(ValidationError, match="including baseline"):
        _manifest(limits=ResourceLimits(max_variants=1),
                  variants=(VariantSpec(variant_id="baseline", kind=VariantKind.BASELINE),
                            VariantSpec(variant_id="logo", kind=VariantKind.LOGO, excluded_group=_key())))


def test_manifest_requires_experiment_reference_and_digest():
    payload = _manifest().model_dump()
    for field in ("experiment_ref", "experiment_digest"):
        incomplete = payload.copy()
        del incomplete[field]
        with pytest.raises(ValidationError, match="Field required"):
            FrozenManifest.model_validate(incomplete)
    assert _manifest().experiment_digest == DIGEST
    with pytest.raises(ValidationError):
        _manifest(experiment_digest="unpinned")


def test_candidate_sides_are_a_partition_and_do_not_silently_deduplicate():
    candidate = dict(partition_id=DIGEST, members=("a", "b", "c"), side_a=("a", "b"),
                     side_b=("c",), side_a_fingerprint=DIGEST, side_b_fingerprint=DIGEST,
                     origins=(CandidateOrigin(source="ENTITY", label="fixture", baseline_order=0),))
    assert FrozenCandidate(**candidate).side_b == ("c",)
    for changes in ({"side_a": ("a", "a", "b")}, {"side_b": ("b", "c")}, {"side_b": ()}):
        with pytest.raises(ValidationError):
            FrozenCandidate(**(candidate | changes))


def test_zero_volume_is_not_a_zero_phi_ranked_candidate():
    score = CandidateScore(partition_id=DIGEST, status=CandidateScoreStatus.ZERO_SIDE_VOLUME,
                           volume_a=0.0, volume_b=2.0)
    assert score.phi is None and score.rank is None
    with pytest.raises(ValidationError, match="cannot have phi"):
        CandidateScore(partition_id=DIGEST, status=CandidateScoreStatus.ZERO_SIDE_VOLUME,
                       volume_a=0.0, volume_b=2.0, phi=0.0, rank=1)


def test_edge_deletion_and_weight_change_are_distinct():
    data = dict(pair=PairKey(left="b", right="a"), baseline_weight=0.5, variant_weight=None,
                baseline_available_group_count=3, variant_available_group_count=2,
                baseline_support_group_count=2, variant_support_group_count=1)
    assert EdgeTransition(**data, transition=EdgeTransitionKind.REMOVED_MIN_SUPPORT_GROUPS).variant_weight is None
    with pytest.raises(ValidationError, match="both edge weights"):
        EdgeTransition(**data, transition=EdgeTransitionKind.RETAINED_WEIGHT_INCREASED)
    with pytest.raises(ValidationError, match="fewer than two"):
        EdgeTransition(**(data | {"variant_support_group_count": 2}),
                       transition=EdgeTransitionKind.REMOVED_MIN_SUPPORT_GROUPS)


def test_materiality_and_verdict_flip_are_independent():
    data = dict(production_baseline_winner_id=DIGEST, variant_best_id=DIGEST, regret=0.0,
                winner_status=WinnerStatus.WINNER_UNCHANGED,
                materiality_status=MaterialityStatus.NOT_CONFIGURED, verdict_flip=True)
    assert CandidateComparison(**data).verdict_flip is True
    with pytest.raises(ValidationError, match="configured materiality"):
        CandidateComparison(**(data | {"winner_status": WinnerStatus.MATERIAL_WINNER_CHANGE}))
    with pytest.raises(ValidationError, match="null regret"):
        CandidateComparison(**(data | {"winner_status": WinnerStatus.NO_SCORABLE_CANDIDATE}))


def test_exact_logo_cannot_claim_added_edge_as_success():
    data = dict(variant=VariantSpec(variant_id="logo", kind=VariantKind.LOGO, excluded_group=_key()),
                edge_transition_summary=EdgeTransitionSummary(counts={EdgeTransitionKind.ADDED: 1}))
    with pytest.raises(ValidationError, match="cannot add edges"):
        VariantResult(**data, computation_status=ComputationStatus.EXACT)
    assert VariantResult(**data, computation_status=ComputationStatus.FAILED).edge_transition_summary.counts[EdgeTransitionKind.ADDED] == 1


def test_complete_report_rejects_failed_variant_and_unmeasured_invariant():
    from audit_diagnostics.contracts import InvariantResult

    data = dict(run_status=RunStatus.COMPLETE, complete=True, manifest_digest=DIGEST,
                semantic_result_digest=DIGEST,
                baseline_binding=_binding(), candidate_set_digest=DIGEST,
                registry_complete=True, pair_matrix_complete=True)
    with pytest.raises(ValidationError, match="incomplete variants"):
        DiagnosticReport(**data, variants=(VariantResult(
            variant=VariantSpec(variant_id="baseline", kind=VariantKind.BASELINE),
            computation_status=ComputationStatus.PARTIAL),))
    with pytest.raises(ValidationError, match="unmeasured invariants"):
        DiagnosticReport(**data, invariant_results=(InvariantResult(invariant_id="all_pairs", passed=None),))


def test_report_cannot_claim_complete_for_missing_matrix_or_registry():
    data = dict(run_status=RunStatus.COMPLETE, complete=True, manifest_digest=DIGEST,
                semantic_result_digest=DIGEST,
                baseline_binding=_binding(), candidate_set_digest=DIGEST,
                registry_complete=True, pair_matrix_complete=True,
                variants=(VariantResult(
                    variant=VariantSpec(variant_id="baseline", kind=VariantKind.BASELINE),
                    computation_status=ComputationStatus.EXACT,
                ),))
    assert DiagnosticReport(**data).scope_quality_threshold_status == "QUALITY_THRESHOLD_NOT_CONFIGURED"
    for changes in ({"registry_complete": False}, {"pair_matrix_complete": False},
                    {"candidate_set_digest": None}, {"complete": False}):
        with pytest.raises(ValidationError):
            DiagnosticReport(**(data | changes))
    partial = DiagnosticReport(**(data | {"run_status": RunStatus.PARTIAL, "complete": False,
                                        "pair_matrix_complete": False}))
    assert json.loads(partial.model_dump_json())["complete"] is False

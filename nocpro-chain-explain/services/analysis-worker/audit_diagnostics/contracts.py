"""Validated v1 contracts for offline Audit coverage and sensitivity.

These schemas describe inputs and results only. They do not classify scope,
evaluate channels, rebuild graphs, select candidates, or activate policy.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, model_validator

from channels.base import EvidenceState
from libs.provenance import EffectiveGroupKey, ProvenanceClass, ProvenanceSubtype
from libs.provenance.eligibility import baseline_eligibility


Identifier = Annotated[str, Field(min_length=1, pattern=r"^\S(?:.*\S)?$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0)]
PositiveCount = Annotated[int, Field(strict=True, gt=0)]
FiniteNonnegative = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
UnitValue = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class DiagnosticModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, validate_default=True,
    )

    @model_validator(mode="after")
    def strict_json_values(self) -> Self:
        # JsonValue metadata must obey the same finite-number rule as metrics.
        json.dumps(self.model_dump(mode="python"), allow_nan=False, default=str)
        return self


class ScopeState(str, Enum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN_APPLICABILITY = "UNKNOWN_APPLICABILITY"


class InvocationStatus(str, Enum):
    EVALUATED = "EVALUATED"
    NOT_EVALUATED = "NOT_EVALUATED"


class ComputationStatus(str, Enum):
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    NOT_EVALUATED = "NOT_EVALUATED"


class RunStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class ReasonOrigin(str, Enum):
    DATA = "DATA"
    MAPPING = "MAPPING"
    PROVENANCE = "PROVENANCE"
    CAPABILITY = "CAPABILITY"
    EXECUTION = "EXECUTION"
    SCOPE = "SCOPE"


class DiagnosticReason(DiagnosticModel):
    code: Identifier
    origin: ReasonOrigin
    detail: str | None = None


class PairKey(DiagnosticModel):
    left: Identifier
    right: Identifier

    @model_validator(mode="after")
    def unordered_distinct_pair(self) -> Self:
        if self.left == self.right:
            raise ValueError("pair endpoints must be distinct")
        if self.left > self.right:
            left, right = self.right, self.left
            object.__setattr__(self, "left", left)
            object.__setattr__(self, "right", right)
        return self


class PairEvidencePriority(str, Enum):
    UNKNOWN_APPLICABILITY = "UNKNOWN_APPLICABILITY"
    APPLICABLE_UNAVAILABLE = "APPLICABLE_UNAVAILABLE"
    OBSERVED = "OBSERVED"


class ChannelPairTrace(DiagnosticModel):
    channel_id: Identifier
    effective_group_key: GroupKey
    scope: ScopeState
    invocation: InvocationStatus
    evidence_state: EvidenceState | None
    primary_reason_code: Identifier | None = None

    @model_validator(mode="after")
    def invocation_trace_consistency(self) -> Self:
        if (self.invocation is InvocationStatus.EVALUATED) != (self.evidence_state is not None):
            raise ValueError("pair trace evidence state must match invocation status")
        if self.scope is ScopeState.NOT_APPLICABLE and self.evidence_state in {
            EvidenceState.SUPPORT, EvidenceState.NEUTRAL,
        }:
            raise ValueError("pair trace cannot report available evidence outside scope")
        return self


class PairEvidenceExample(DiagnosticModel):
    pair: PairKey
    priority: PairEvidencePriority
    channel_traces: tuple[ChannelPairTrace, ...]
    omitted_channel_trace_count: Count = 0

    @model_validator(mode="after")
    def unique_channels(self) -> Self:
        channel_ids = [item.channel_id for item in self.channel_traces]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("pair evidence example has duplicate channel traces")
        return self


class PairUniverse(DiagnosticModel):
    members: tuple[Identifier, ...]
    pairs: tuple[PairKey, ...]
    computation_status: ComputationStatus

    @model_validator(mode="after")
    def valid_population(self) -> Self:
        members = set(self.members)
        if len(members) != len(self.members):
            raise ValueError("duplicate member IDs")
        seen: set[tuple[str, str]] = set()
        for pair in self.pairs:
            key = (pair.left, pair.right)
            if key in seen:
                raise ValueError("duplicate unordered pair")
            if not {pair.left, pair.right} <= members:
                raise ValueError("pair endpoints outside member universe")
            seen.add(key)
        expected = len(members) * (len(members) - 1) // 2
        if self.computation_status is ComputationStatus.EXACT and len(seen) != expected:
            raise ValueError("EXACT requires the complete unordered pair universe")
        return self


class GroupKey(DiagnosticModel):
    """Lossless serialized form of the canonical full effective group key."""

    derivation_tag: Identifier
    provenance_class: ProvenanceClass
    explain_eligible: StrictBool
    role_eligible: StrictBool
    audit_eligible: StrictBool

    @model_validator(mode="after")
    def canonical_eligibility(self) -> Self:
        # Full group identity intentionally omits subtype. Retain every
        # signature the canonical resolver can produce for this class, including
        # fail-closed unresolved EXTERNAL_OPERATIONAL; never invent a signature.
        allowed = {
            baseline_eligibility(self.provenance_class, subtype).as_tuple()
            for subtype in (None, *ProvenanceSubtype)
        }
        actual = (self.explain_eligible, self.role_eligible, self.audit_eligible)
        if actual not in allowed:
            raise ValueError("group eligibility must match a canonical baseline signature for its provenance class")
        return self

    @classmethod
    def from_effective_key(cls, key: EffectiveGroupKey) -> Self:
        return cls(**{name: getattr(key, name) for name in cls.model_fields})

    def to_effective_key(self) -> EffectiveGroupKey:
        return EffectiveGroupKey(**self.model_dump())


class GroupRegistryEntry(DiagnosticModel):
    effective_group_key: GroupKey
    channel_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def nonempty_unique_channels(self) -> Self:
        if not self.channel_ids or len(self.channel_ids) != len(set(self.channel_ids)):
            raise ValueError("registered effective group must have unique channel IDs")
        return self


class ScopeDecision(DiagnosticModel):
    scope: ScopeState
    rule_ids: tuple[Identifier, ...]
    invocation: InvocationStatus
    evidence_state: EvidenceState | None
    primary_reason: DiagnosticReason | None = None
    secondary_reasons: tuple[DiagnosticReason, ...] = ()

    @model_validator(mode="after")
    def independent_axes(self) -> Self:
        evaluated = self.invocation is InvocationStatus.EVALUATED
        if evaluated != (self.evidence_state is not None):
            raise ValueError("only EVALUATED records must contain evidence_state")
        if self.evidence_state in (EvidenceState.SUPPORT, EvidenceState.NEUTRAL):
            if self.scope is ScopeState.NOT_APPLICABLE:
                raise ValueError("available evidence cannot be NOT_APPLICABLE")
        if self.scope is ScopeState.UNKNOWN_APPLICABILITY:
            if self.primary_reason is None or self.primary_reason.code not in {
                "SCOPE_METADATA_MISSING", "SCOPE_METADATA_CONFLICT", "SCOPE_RULE_UNDEFINED",
            } or self.primary_reason.origin is not ReasonOrigin.SCOPE:
                raise ValueError("unknown applicability requires a primary scope reason")
        return self


class ApplicabilityCounts(DiagnosticModel):
    total: Count
    applicable: Count
    not_applicable: Count
    unknown_applicability: Count
    available: Count
    unavailable: Count
    support: Count
    neutral: Count

    @model_validator(mode="after")
    def disjoint_counts(self) -> Self:
        if self.total != self.applicable + self.not_applicable + self.unknown_applicability:
            raise ValueError("scope counts must partition total")
        if self.available > self.applicable:
            raise ValueError("available cannot exceed applicable")
        if self.available != self.support + self.neutral:
            raise ValueError("available must equal support + neutral")
        if self.unavailable != self.applicable - self.available:
            raise ValueError("unavailable must equal applicable - available")
        return self


class RatioStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NO_APPLICABLE_PAIRS = "NO_APPLICABLE_PAIRS"
    EMPTY_POPULATION = "EMPTY_POPULATION"


class Ratio(DiagnosticModel):
    numerator: Count
    denominator: Count
    value: UnitValue | None
    status: RatioStatus

    @model_validator(mode="after")
    def defined_denominator(self) -> Self:
        if self.numerator > self.denominator:
            raise ValueError("ratio numerator cannot exceed denominator")
        if self.denominator == 0:
            if self.value is not None or self.status is RatioStatus.AVAILABLE:
                raise ValueError("zero denominator requires null value and missing status")
        elif self.status is not RatioStatus.AVAILABLE or self.value != self.numerator / self.denominator:
            raise ValueError("ratio value/status must match numerator and denominator")
        return self

    @classmethod
    def from_counts(cls, numerator: int, denominator: int, *, zero_status: RatioStatus) -> Self:
        return cls(
            numerator=numerator, denominator=denominator,
            value=numerator / denominator if denominator else None,
            status=RatioStatus.AVAILABLE if denominator else zero_status,
        )


class CoverageRatios(DiagnosticModel):
    coverage: Ratio
    applicability_share: Ratio
    unknown_scope_share: Ratio
    not_applicable_share: Ratio

    @classmethod
    def from_counts(cls, counts: ApplicabilityCounts) -> Self:
        def share(numerator: int) -> Ratio:
            return Ratio.from_counts(numerator, counts.total, zero_status=RatioStatus.EMPTY_POPULATION)

        return cls(
            coverage=Ratio.from_counts(counts.available, counts.applicable,
                                       zero_status=RatioStatus.NO_APPLICABLE_PAIRS),
            applicability_share=share(counts.applicable),
            unknown_scope_share=share(counts.unknown_applicability),
            not_applicable_share=share(counts.not_applicable),
        )


class PopulationRegion(str, Enum):
    ALL = "all"
    WITHIN_A = "within_A"
    WITHIN_B = "within_B"
    CROSS = "cross"


class ScopeEvidenceStateCount(DiagnosticModel):
    """One disjoint scope × invocation × observed evidence population cell."""

    scope: ScopeState
    invocation: InvocationStatus
    evidence_state: EvidenceState | None
    count: Count

    @model_validator(mode="after")
    def independent_axes(self) -> Self:
        if (self.invocation is InvocationStatus.EVALUATED) != (self.evidence_state is not None):
            raise ValueError("only EVALUATED cross-count cells must contain evidence_state")
        if self.scope is ScopeState.NOT_APPLICABLE and self.evidence_state in {
            EvidenceState.SUPPORT, EvidenceState.NEUTRAL,
        }:
            raise ValueError("available evidence cannot be NOT_APPLICABLE")
        return self


class CoverageRow(DiagnosticModel):
    population_id: Identifier
    region: PopulationRegion
    channel_id: Identifier | None = None
    effective_group_key: GroupKey | None = None
    scope_policy_id: Identifier
    rule_ids: tuple[Identifier, ...]
    counts: ApplicabilityCounts
    ratios: CoverageRatios
    computation_status: ComputationStatus
    scope_evidence_state_counts: tuple[ScopeEvidenceStateCount, ...]
    primary_reason_counts: dict[Identifier, Count] = Field(default_factory=dict)
    invocation_status_counts: dict[InvocationStatus, Count] = Field(default_factory=dict)
    partial_group_observability_counts: dict[Identifier, Count] = Field(default_factory=dict)

    @model_validator(mode="after")
    def row_consistency(self) -> Self:
        if (self.channel_id is None) == (self.effective_group_key is None):
            raise ValueError("coverage row needs exactly one channel or full group key")
        if self.ratios != CoverageRatios.from_counts(self.counts):
            raise ValueError("coverage ratios must match scope counts")
        if sum(self.primary_reason_counts.values()) > self.counts.total:
            raise ValueError("primary reasons cannot exceed the disjoint population")
        if self.invocation_status_counts and sum(self.invocation_status_counts.values()) != self.counts.total:
            raise ValueError("invocation counts must partition total")
        if self.channel_id is not None and self.partial_group_observability_counts:
            raise ValueError("partial group observability applies only to group rows")
        cells = self.scope_evidence_state_counts
        keys = [(cell.scope, cell.invocation, cell.evidence_state) for cell in cells]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate scope/invocation/evidence cross-count cell")
        if sum(cell.count for cell in cells) != self.counts.total:
            raise ValueError("scope evidence state counts must partition total")
        scope_totals = {
            ScopeState.APPLICABLE: self.counts.applicable,
            ScopeState.NOT_APPLICABLE: self.counts.not_applicable,
            ScopeState.UNKNOWN_APPLICABILITY: self.counts.unknown_applicability,
        }
        for scope, expected in scope_totals.items():
            if sum(cell.count for cell in cells if cell.scope is scope) != expected:
                raise ValueError("scope evidence state counts must match scope totals")
        for state, expected in ((EvidenceState.SUPPORT, self.counts.support),
                                (EvidenceState.NEUTRAL, self.counts.neutral)):
            actual = sum(cell.count for cell in cells if cell.scope is ScopeState.APPLICABLE
                         and cell.evidence_state is state)
            if actual != expected:
                raise ValueError("scope evidence state counts must match conditional support/neutral counts")
        if self.invocation_status_counts:
            for invocation in InvocationStatus:
                actual = sum(cell.count for cell in cells if cell.invocation is invocation)
                if actual != self.invocation_status_counts.get(invocation, 0):
                    raise ValueError("scope evidence state counts must match invocation counts")
        return self


class MaterialityStatus(str, Enum):
    NOT_CONFIGURED = "MATERIALITY_NOT_CONFIGURED"
    CONFIGURED = "CONFIGURED"
    NOT_COMPUTABLE = "NOT_COMPUTABLE"


class MaterialityPolicy(DiagnosticModel):
    epsilon_num: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 1e-12
    delta_phi: FiniteNonnegative | None = None
    rationale: str | None = None
    approved_by: Identifier | None = None
    policy_version: Identifier | None = None

    @model_validator(mode="after")
    def operational_threshold(self) -> Self:
        if self.delta_phi is not None and self.delta_phi <= self.epsilon_num:
            raise ValueError("delta_phi must be positive and greater than epsilon_num")
        return self


class ResourceLimits(DiagnosticModel):
    max_members: PositiveCount = 500
    max_pairs: PositiveCount = 124750
    max_variants: PositiveCount = 32
    max_candidates: PositiveCount = 128
    max_example_pairs_per_section: Count = 50
    max_channel_traces_per_pair: PositiveCount = 64
    timeout_seconds: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 300.0


class VariantKind(str, Enum):
    BASELINE = "BASELINE"
    LOGO = "LOGO"
    EPSILON_ONLY = "EPSILON_ONLY"
    CHANNEL_CONFIG = "CHANNEL_CONFIG"
    ENTITY_REGROUPING = "ENTITY_REGROUPING"


class VariantSpec(DiagnosticModel):
    variant_id: Identifier
    kind: VariantKind
    excluded_group: GroupKey | None = None
    parameters: dict[Identifier, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def intervention_identity(self) -> Self:
        if (self.kind is VariantKind.LOGO) != (self.excluded_group is not None):
            raise ValueError("only LOGO must identify one full excluded group")
        if self.excluded_group is not None and not self.excluded_group.audit_eligible:
            raise ValueError("LOGO group must be audit eligible")
        if self.kind in (VariantKind.BASELINE, VariantKind.LOGO) and self.parameters:
            raise ValueError("baseline and pure LOGO cannot change configuration")
        return self


class InputBinding(DiagnosticModel):
    snapshot_id: Identifier
    snapshot_version: Identifier
    chain_id: Identifier
    snapshot_ref: Identifier
    input_bytes_digest: Digest
    canonical_package_digest: Digest
    member_fingerprint: Digest
    topology_ref: Identifier | None = None
    topology_version: Identifier | None = None
    topology_digest: Digest | None = None
    mapping_digest: Digest | None = None
    provenance_digest: Digest | None = None
    hydration_digest: Digest | None = None
    taxonomy_digest: Digest | None = None
    delay_model_digest: Digest | None = None


class SourceBinding(DiagnosticModel):
    git_commit: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
    dirty: StrictBool
    file_digests: dict[Identifier, Digest]
    source_bundle_digest: Digest

    @model_validator(mode="after")
    def source_present(self) -> Self:
        if not self.file_digests:
            raise ValueError("source binding requires relevant source file digests")
        return self


class FrozenManifest(DiagnosticModel):
    schema_version: Literal["audit-diagnostics-manifest-v1"] = "audit-diagnostics-manifest-v1"
    run_id: Identifier
    prepared_at: datetime
    analysis_version: Identifier
    baseline_policy_version: Identifier
    input_binding: InputBinding
    source_binding: SourceBinding
    analysis_config_ref: Identifier
    analysis_config_digest: Digest
    scope_policy_ref: Identifier
    scope_policy_id: Identifier
    scope_policy_version: Identifier
    scope_policy_digest: Digest
    group_registry_digest: Digest
    execution_profile_digest: Digest
    candidate_generation_config_digest: Digest
    experiment_ref: Identifier
    experiment_digest: Digest
    audit_epsilon_phi: UnitValue
    audit_epsilon_phi_source: Identifier
    variants: tuple[VariantSpec, ...]
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    materiality_policy: MaterialityPolicy = Field(default_factory=MaterialityPolicy)

    @model_validator(mode="after")
    def frozen_experiment(self) -> Self:
        if self.prepared_at.utcoffset() is None or self.prepared_at.utcoffset().total_seconds() != 0:
            raise ValueError("manifest timestamp must be timezone-aware UTC")
        ids = [variant.variant_id for variant in self.variants]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate variant IDs")
        if sum(v.kind is VariantKind.BASELINE for v in self.variants) != 1:
            raise ValueError("manifest requires exactly one baseline variant")
        if len(ids) > self.limits.max_variants:
            raise ValueError("variant count exceeds declared budget including baseline")
        return self


class CandidateOrigin(DiagnosticModel):
    source: Identifier
    label: Identifier
    baseline_order: Count
    parameters: dict[Identifier, JsonValue] = Field(default_factory=dict)


class FrozenCandidate(DiagnosticModel):
    partition_id: Digest
    members: tuple[Identifier, ...]
    side_a: tuple[Identifier, ...]
    side_b: tuple[Identifier, ...]
    side_a_fingerprint: Digest
    side_b_fingerprint: Digest
    origins: tuple[CandidateOrigin, ...]

    @model_validator(mode="after")
    def partition(self) -> Self:
        for values in (self.members, self.side_a, self.side_b):
            if len(values) != len(set(values)):
                raise ValueError("duplicate members in candidate partition")
        a, b = set(self.side_a), set(self.side_b)
        if a & b or a | b != set(self.members):
            raise ValueError("candidate sides must partition member universe")
        if not self.origins:
            raise ValueError("candidate requires origin provenance")
        return self


class CandidateScoreStatus(str, Enum):
    SCORABLE = "SCORABLE"
    ZERO_SIDE_VOLUME = "ZERO_SIDE_VOLUME"
    INFEASIBLE = "INFEASIBLE"
    EMPTY_CANDIDATE = "EMPTY_CANDIDATE"
    EMPTY_GRAPH = "EMPTY_GRAPH"
    SKIPPED_SMALL_CHAIN = "SKIPPED_SMALL_CHAIN"
    UNAVAILABLE = "UNAVAILABLE"


class CandidateScore(DiagnosticModel):
    partition_id: Digest
    status: CandidateScoreStatus
    edge_count: Count | None = None
    isolate_count: Count | None = None
    cut_weight: FiniteNonnegative | None = None
    volume_a: FiniteNonnegative | None = None
    volume_b: FiniteNonnegative | None = None
    phi: UnitValue | None = None
    rank: PositiveCount | None = None
    reason: Identifier | None = None

    @model_validator(mode="after")
    def score_availability(self) -> Self:
        if self.status is CandidateScoreStatus.SCORABLE:
            if self.phi is None or self.cut_weight is None or self.volume_a is None or self.volume_b is None:
                raise ValueError("scorable candidate requires phi, cut weight and side volumes")
            if min(self.volume_a, self.volume_b) <= 0:
                raise ValueError("scorable candidate requires positive side volumes")
        elif self.phi is not None or self.rank is not None:
            raise ValueError("unscorable candidate cannot have phi or rank")
        if self.status is CandidateScoreStatus.ZERO_SIDE_VOLUME:
            if self.volume_a is None or self.volume_b is None or min(self.volume_a, self.volume_b) != 0:
                raise ValueError("ZERO_SIDE_VOLUME requires a measured zero side volume")
        return self


class EdgeTransitionKind(str, Enum):
    RETAINED_UNCHANGED = "RETAINED_UNCHANGED"
    RETAINED_WEIGHT_INCREASED = "RETAINED_WEIGHT_INCREASED"
    RETAINED_WEIGHT_DECREASED = "RETAINED_WEIGHT_DECREASED"
    REMOVED_MIN_SUPPORT_GROUPS = "REMOVED_MIN_SUPPORT_GROUPS"
    ADDED = "ADDED"


class RemovedGroupState(str, Enum):
    SUPPORT = "SUPPORT"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"
    ABSENT = "ABSENT"


class EdgeTransition(DiagnosticModel):
    pair: PairKey
    transition: EdgeTransitionKind
    baseline_weight: UnitValue | None
    variant_weight: UnitValue | None
    baseline_available_group_count: Count
    variant_available_group_count: Count
    baseline_support_group_count: Count
    variant_support_group_count: Count
    removed_group_state: RemovedGroupState | None = None
    baseline_group_keys: tuple[GroupKey, ...] = ()
    variant_group_keys: tuple[GroupKey, ...] = ()
    reason: Identifier | None = None

    @model_validator(mode="after")
    def edge_presence(self) -> Self:
        if self.baseline_support_group_count > self.baseline_available_group_count:
            raise ValueError("baseline supporting groups cannot exceed available groups")
        if self.variant_support_group_count > self.variant_available_group_count:
            raise ValueError("variant supporting groups cannot exceed available groups")
        if self.transition is EdgeTransitionKind.REMOVED_MIN_SUPPORT_GROUPS:
            if self.baseline_weight is None or self.variant_weight is not None or self.variant_support_group_count >= 2:
                raise ValueError("removed edge requires baseline edge and fewer than two remaining support groups")
        elif self.transition is EdgeTransitionKind.ADDED:
            if self.baseline_weight is not None or self.variant_weight is None:
                raise ValueError("added edge requires only variant weight")
        elif self.baseline_weight is None or self.variant_weight is None:
            raise ValueError("retained transition requires both edge weights")
        return self


class EdgeTransitionSummary(DiagnosticModel):
    counts: dict[EdgeTransitionKind, Count] = Field(default_factory=dict)
    removed_baseline_weight: FiniteNonnegative = 0.0
    retained_positive_weight_delta: FiniteNonnegative = 0.0
    retained_negative_weight_delta_absolute: FiniteNonnegative = 0.0
    boundary_pair_count: Count = 0
    boundary_population_count: Count = 0
    boundary_removed_group_state_counts: dict[RemovedGroupState, Count] = Field(default_factory=dict)

    @model_validator(mode="after")
    def boundary_population(self) -> Self:
        if self.boundary_pair_count > self.boundary_population_count:
            raise ValueError("boundary pair count cannot exceed its declared population")
        if sum(self.boundary_removed_group_state_counts.values()) != self.boundary_pair_count:
            raise ValueError("boundary group-state counts must partition boundary pairs")
        return self


class CandidateRegionSummary(DiagnosticModel):
    candidate_id: Digest
    region: PopulationRegion
    population_pair_count: Count
    baseline_region_edge_count: Count
    variant_region_edge_count: Count
    baseline_region_isolate_count: Count
    variant_region_isolate_count: Count
    edge_transitions: EdgeTransitionSummary


class WinnerStatus(str, Enum):
    WINNER_UNCHANGED = "WINNER_UNCHANGED"
    WINNER_CHANGED = "WINNER_CHANGED"
    NUMERICAL_TIE = "NUMERICAL_TIE"
    NEAR_TIE_REORDER = "NEAR_TIE_REORDER"
    MATERIAL_WINNER_CHANGE = "MATERIAL_WINNER_CHANGE"
    BASELINE_WINNER_UNSCORABLE = "BASELINE_WINNER_UNSCORABLE"
    NO_SCORABLE_CANDIDATE = "NO_SCORABLE_CANDIDATE"


class CandidateComparison(DiagnosticModel):
    production_baseline_winner_id: Digest | None
    diagnostic_tie_winner_id: Digest | None = None
    variant_best_id: Digest | None
    winner_status: WinnerStatus
    regret: FiniteNonnegative | None
    absolute_phi_drift: FiniteNonnegative | None = None
    materiality_status: MaterialityStatus
    verdict_flip: StrictBool | None = None

    @model_validator(mode="after")
    def unavailable_regret(self) -> Self:
        unscorable = self.winner_status in {
            WinnerStatus.BASELINE_WINNER_UNSCORABLE, WinnerStatus.NO_SCORABLE_CANDIDATE,
        }
        if unscorable and self.regret is not None:
            raise ValueError("unscorable winner comparison requires null regret")
        if not unscorable and (self.regret is None or self.production_baseline_winner_id is None or self.variant_best_id is None):
            raise ValueError("scorable winner comparison requires both winner IDs and regret")
        if self.winner_status is WinnerStatus.MATERIAL_WINNER_CHANGE and self.materiality_status is not MaterialityStatus.CONFIGURED:
            raise ValueError("material winner change requires configured materiality")
        return self


class VariantResult(DiagnosticModel):
    variant: VariantSpec
    computation_status: ComputationStatus
    reason: Identifier | None = None
    edge_transition_summary: EdgeTransitionSummary | None = None
    candidate_scores: tuple[CandidateScore, ...] = ()
    comparison: CandidateComparison | None = None
    candidate_region_summaries: tuple[CandidateRegionSummary, ...] = ()
    bounded_pair_examples: tuple[EdgeTransition, ...] = ()
    omitted_example_count: Count = 0

    @model_validator(mode="after")
    def logo_invariants(self) -> Self:
        if self.variant.kind is VariantKind.LOGO and self.computation_status is ComputationStatus.EXACT:
            if self.edge_transition_summary is not None:
                if self.edge_transition_summary.counts.get(EdgeTransitionKind.ADDED, 0):
                    raise ValueError("exact pure LOGO cannot add edges")
            for example in self.bounded_pair_examples:
                if example.transition is EdgeTransitionKind.ADDED:
                    raise ValueError("exact pure LOGO cannot add edges")
                if example.variant_support_group_count > example.baseline_support_group_count:
                    raise ValueError("exact pure LOGO cannot increase support group count")
        ids = [score.partition_id for score in self.candidate_scores]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate scores in variant")
        return self


class InvariantResult(DiagnosticModel):
    invariant_id: Identifier
    passed: StrictBool | None
    detail: str | None = None


class ScopeQualityFlag(DiagnosticModel):
    channel_id: Identifier
    unknown_applicability_count: Count
    unknown_applicability_share: Ratio
    undefined_rule_count: Count
    reason_counts: dict[Identifier, Count] = Field(default_factory=dict)
    threshold_status: Literal["QUALITY_THRESHOLD_NOT_CONFIGURED", "CONFIGURED"] = "QUALITY_THRESHOLD_NOT_CONFIGURED"

    @model_validator(mode="after")
    def reason_consistency(self) -> Self:
        if self.unknown_applicability_share.numerator != self.unknown_applicability_count:
            raise ValueError("unknown applicability count must match its reported share numerator")
        if self.undefined_rule_count > self.unknown_applicability_count:
            raise ValueError("undefined rules cannot exceed unknown applicability pairs")
        if sum(self.reason_counts.values()) > self.unknown_applicability_count:
            raise ValueError("scope reason counts cannot exceed unknown applicability pairs")
        return self


class DiagnosticReport(DiagnosticModel):
    schema_version: Literal["audit-coverage-sensitivity-v1"] = "audit-coverage-sensitivity-v1"
    run_status: RunStatus
    complete: StrictBool
    manifest_digest: Digest
    semantic_result_digest: Digest | None = None
    baseline_binding: InputBinding
    audit_epsilon_phi: UnitValue | None = None
    audit_epsilon_phi_source: Identifier | None = None
    baseline_production_verdict: Identifier | None = None
    materiality_policy: MaterialityPolicy = Field(default_factory=MaterialityPolicy)
    execution_profile_digest: Digest | None = None
    group_registry_digest: Digest | None = None
    registered_channel_ids: tuple[Identifier, ...] = ()
    registered_group_keys: tuple[GroupKey, ...] = ()
    registered_groups: tuple[GroupRegistryEntry, ...] = ()
    capability_catalog: dict[Identifier, dict[str, str]] = Field(default_factory=dict)
    candidate_set_digest: Digest | None = None
    registry_complete: StrictBool
    pair_matrix_complete: StrictBool
    scope_quality: tuple[CoverageRow, ...] = ()
    scope_quality_flags: tuple[ScopeQualityFlag, ...] = ()
    scope_quality_threshold_status: Literal["QUALITY_THRESHOLD_NOT_CONFIGURED", "CONFIGURED"] = "QUALITY_THRESHOLD_NOT_CONFIGURED"
    coverage_all_pairs: tuple[CoverageRow, ...] = ()
    coverage_pair_examples: tuple[PairEvidenceExample, ...] = ()
    omitted_coverage_pair_example_count: Count = 0
    candidates: tuple[FrozenCandidate, ...] = ()
    coverage_by_candidate_region: dict[Digest, tuple[CoverageRow, ...]] = Field(default_factory=dict)
    variants: tuple[VariantResult, ...] = ()
    invariant_results: tuple[InvariantResult, ...] = ()
    limitations: tuple[str, ...] = ()
    resource_counts: dict[Identifier, Count] = Field(default_factory=dict)
    timings_seconds: dict[Identifier, FiniteNonnegative] = Field(default_factory=dict)

    @model_validator(mode="after")
    def truthful_completeness(self) -> Self:
        if self.complete != (self.run_status is RunStatus.COMPLETE):
            raise ValueError("completeness must match run status")
        if self.complete:
            if not self.registry_complete or not self.pair_matrix_complete or self.candidate_set_digest is None:
                raise ValueError("complete report requires complete registry/matrix and candidate-set digest")
            if self.semantic_result_digest is None:
                raise ValueError("complete report requires a semantic result digest")
            if any(v.computation_status is not ComputationStatus.EXACT for v in self.variants):
                raise ValueError("complete report cannot contain incomplete variants")
            if any(result.passed is not True for result in self.invariant_results):
                raise ValueError("complete report cannot contain failed or unmeasured invariants")
            if any(row.computation_status is not ComputationStatus.EXACT
                   for row in (*self.scope_quality, *self.coverage_all_pairs)):
                raise ValueError("complete report cannot contain partial coverage rows")
            if any(row.computation_status is not ComputationStatus.EXACT
                   for rows in self.coverage_by_candidate_region.values() for row in rows):
                raise ValueError("complete report cannot contain partial candidate-region coverage")
            candidate_ids = {candidate.partition_id for candidate in self.candidates}
            if len(candidate_ids) != len(self.candidates):
                raise ValueError("report candidates must have unique canonical partitions")
            if sum(variant.variant.kind is VariantKind.BASELINE for variant in self.variants) != 1:
                raise ValueError("complete report requires exactly one baseline variant")
            expected_score_ids = candidate_ids
            if any({score.partition_id for score in variant.candidate_scores} != expected_score_ids
                   for variant in self.variants):
                raise ValueError("every variant must score the fixed candidate set")
            if any(score.edge_count is None or score.isolate_count is None
                   for variant in self.variants for score in variant.candidate_scores):
                raise ValueError("complete candidate scores require graph edge and isolate counts")
            for variant in self.variants:
                if variant.variant.kind is VariantKind.LOGO:
                    if variant.edge_transition_summary is None or variant.comparison is None:
                        raise ValueError("complete LOGO variants require edge and candidate comparison summaries")
                    region_keys = [
                        (item.candidate_id, item.region)
                        for item in variant.candidate_region_summaries
                    ]
                    if len(region_keys) != len(set(region_keys)):
                        raise ValueError("duplicate candidate-region LOGO summary")
                    if len(region_keys) != 4 * len(candidate_ids):
                        raise ValueError("complete LOGO variants require all four regions per candidate")
            if any(candidate_id not in candidate_ids for candidate_id in self.coverage_by_candidate_region):
                raise ValueError("candidate-region coverage references an unknown frozen candidate")
            if len({item.invariant_id for item in self.invariant_results}) != len(self.invariant_results):
                raise ValueError("invariant IDs must be unique")
            if self.registered_groups:
                group_channels = [
                    channel_id for group in self.registered_groups for channel_id in group.channel_ids
                ]
                if len(group_channels) != len(set(group_channels)):
                    raise ValueError("a channel cannot belong to multiple registered groups")
                if set(group_channels) != set(self.registered_channel_ids):
                    raise ValueError("registered groups must partition the resolved channel registry")
                if set(self.registered_group_keys) != {
                    group.effective_group_key for group in self.registered_groups
                }:
                    raise ValueError("registered group keys must match registry entries")
        return self

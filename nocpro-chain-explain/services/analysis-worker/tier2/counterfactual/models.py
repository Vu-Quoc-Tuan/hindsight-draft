"""Immutable contracts for review-only counterfactual chain proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from channels.cross_chain import CrossChainEvidence


class Operation(str, Enum):
    REMOVE_MEMBER = "REMOVE_MEMBER"
    SPLIT_CHAIN = "SPLIT_CHAIN"
    MOVE_MEMBER = "MOVE_MEMBER"
    MERGE_CHAINS = "MERGE_CHAINS"


class DomainStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SearchMode(str, Enum):
    BOUNDED = "BOUNDED"
    NOT_RUN = "NOT_RUN"


class CandidateStatus(str, Enum):
    GENERATED = "GENERATED"
    EVALUATED = "EVALUATED"
    HARD_GATE_REJECTED = "HARD_GATE_REJECTED"
    PARETO_FRONTIER = "PARETO_FRONTIER"
    EXTERNALLY_CONTRADICTED = "EXTERNALLY_CONTRADICTED"
    BETTER_SUPPORTED = "BETTER_SUPPORTED"
    EXTERNALLY_SUPPORTED = "EXTERNALLY_SUPPORTED"


class MetricAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RecommendationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NO_CLEAR_ALTERNATIVE = "NO_CLEAR_ALTERNATIVE"


class SemanticEffect(str, Enum):
    """A post-edit fact; it never changes operation selection or acceptance."""

    BECOMES_CONNECTOR = "BECOMES_CONNECTOR"


@dataclass(frozen=True)
class MetricValue:
    availability: MetricAvailability
    value: float | int | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.availability is MetricAvailability.AVAILABLE:
            if self.value is None:
                raise ValueError("available metric requires a value")
            if self.reason is not None:
                raise ValueError("available metric cannot have an unavailable reason")
        elif self.value is not None:
            raise ValueError("unavailable metric cannot carry a numeric value")

    @classmethod
    def available(cls, value: float | int) -> "MetricValue":
        return cls(MetricAvailability.AVAILABLE, value)

    @classmethod
    def unavailable(cls, reason: str) -> "MetricValue":
        return cls(MetricAvailability.UNAVAILABLE, None, reason)

    @classmethod
    def not_applicable(cls, reason: str) -> "MetricValue":
        return cls(MetricAvailability.NOT_APPLICABLE, None, reason)


@dataclass(frozen=True)
class MetricVector:
    weak_member_count: MetricValue
    minimum_membership_support: MetricValue
    evidence_union_coverage: MetricValue
    component_count: MetricValue
    audit_conductance: MetricValue
    audit_verdict_severity: MetricValue
    eligible_external_contradiction_count: MetricValue


@dataclass(frozen=True, order=True)
class EditCost:
    operation_count: int
    membership_reassignments: int
    affected_member_count: int

    def __post_init__(self) -> None:
        if min(
            self.operation_count,
            self.membership_reassignments,
            self.affected_member_count,
        ) < 0:
            raise ValueError("edit cost values must be non-negative")


ChainMembers: TypeAlias = tuple[str, tuple[str, ...]]


def _canonical_partition(chains: tuple[ChainMembers, ...]) -> tuple[ChainMembers, ...]:
    canonical: list[ChainMembers] = []
    seen_chain_ids: set[str] = set()
    seen_alarm_ids: set[str] = set()
    for chain_id, raw_members in chains:
        if not isinstance(chain_id, str) or not chain_id:
            raise ValueError("partition chain_id must be a non-empty string")
        if chain_id in seen_chain_ids:
            raise ValueError(f"duplicate affected chain_id {chain_id!r}")
        members = tuple(sorted(raw_members))
        if not members:
            raise ValueError("affected chains cannot be empty")
        if len(set(members)) != len(members):
            raise ValueError(f"chain {chain_id!r} contains duplicate alarms")
        overlap = seen_alarm_ids.intersection(members)
        if overlap:
            raise ValueError(
                "an alarm appears in more than one chain: "
                + ", ".join(sorted(overlap))
            )
        seen_chain_ids.add(chain_id)
        seen_alarm_ids.update(members)
        canonical.append((chain_id, members))
    return tuple(sorted(canonical, key=lambda item: item[0]))


@dataclass(frozen=True)
class PartitionDelta:
    before: tuple[ChainMembers, ...]
    after: tuple[ChainMembers, ...]

    def __post_init__(self) -> None:
        before = _canonical_partition(self.before)
        after = _canonical_partition(self.after)
        before_ids = {alarm_id for _, members in before for alarm_id in members}
        after_ids = {alarm_id for _, members in after for alarm_id in members}
        if before_ids != after_ids:
            raise ValueError("before and after alarm universe must be identical")
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "after", after)

    @property
    def alarm_ids(self) -> tuple[str, ...]:
        return tuple(sorted(alarm_id for _, members in self.before for alarm_id in members))

    def canonical_tuple(self) -> tuple[tuple[ChainMembers, ...], tuple[ChainMembers, ...]]:
        return self.before, self.after


@dataclass(frozen=True)
class ReviewIdentity:
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    alarm_universe_fingerprint: str
    analysis_version: str
    engine_version: str
    config_version: str
    tier1b_artifact_fingerprint: str
    structural_audit_artifact_fingerprint: str | None = None
    external_validation_artifact_fingerprint: str | None = None

    def cache_tuple(self) -> tuple[str, ...]:
        return (
            self.snapshot_id,
            self.snapshot_version,
            self.chain_id,
            self.alarm_universe_fingerprint,
            self.analysis_version,
            self.engine_version,
            self.config_version,
            self.tier1b_artifact_fingerprint,
            self.structural_audit_artifact_fingerprint or "UNAVAILABLE",
            self.external_validation_artifact_fingerprint or "UNAVAILABLE",
        )


@dataclass(frozen=True)
class ExternalValidationArtifact:
    """Already eligibility-gated external conclusions for Review P0."""

    fingerprint: str
    contradicted_member_ids: frozenset[str] = frozenset()
    supported_candidate_ids: frozenset[str] = frozenset()
    contradicted_candidate_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CounterfactualCandidate:
    candidate_id: str
    operation: Operation
    partition_delta: PartitionDelta
    edit_cost: EditCost
    source_ref: str
    member_ids: tuple[str, ...]
    source_chain_id: str | None = None
    target_chain_id: str | None = None
    merged_chain_ids: tuple[str, str] | None = None
    merge_evidence: CrossChainEvidence | None = None
    operation_evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MoveStructuralFacts:
    """Exact structural facts for the moved member in a two-chain evaluation."""

    before_structural_role: str
    after_structural_role: str
    after_is_articulation_point: bool
    after_blocks_supported: int


@dataclass(frozen=True)
class CandidateBatch:
    operation: Operation
    discovered_count: int
    evaluated_count: int
    candidate_limit: int
    candidates: tuple[CounterfactualCandidate, ...]
    canonical_remove_member_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: CounterfactualCandidate
    status: CandidateStatus
    before: MetricVector | None = None
    after: MetricVector | None = None
    materially_improved_metrics: tuple[str, ...] = ()
    reason: str | None = None
    move_structural_facts: MoveStructuralFacts | None = None
    semantic_effects: tuple[SemanticEffect, ...] = ()
    # Exact signed deltas actually calculated by the evaluator: positive means
    # improvement according to the metric's frozen direction.
    metric_deltas: dict[str, float] = field(default_factory=dict)
    external_validation: str = "UNAVAILABLE"


@dataclass(frozen=True)
class OperationResult:
    operation: Operation
    status: DomainStatus
    reason: str | None
    search_mode: SearchMode
    discovered_candidate_count: int
    evaluated_candidate_count: int
    rejected_candidate_count: int
    candidate_limit: int | None
    candidates: tuple[CandidateEvaluation, ...] = ()


@dataclass(frozen=True)
class CounterfactualResult:
    identity: ReviewIdentity
    status: DomainStatus
    reason: str | None
    recommendation_status: RecommendationStatus
    remove: OperationResult
    split: OperationResult
    move: OperationResult
    merge: OperationResult
    calibration_status: str | None = None
    recommendations: tuple[CandidateEvaluation, ...] = ()
    frontier_count_before_limit: int = 0
    frontier_truncated: bool = False
    frontier_candidate_ids: tuple[str, ...] = ()
    parameter_provenance: dict[str, str] = field(default_factory=dict)

"""Immutable review, exposure, feedback, and truth-tier contracts.

Frozen per 2026-09-11 implementation plan.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DEFER = "DEFER"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NONE_ACCEPTABLE = "NONE_ACCEPTABLE"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"


class ReviewSessionNotFound(Exception):
    """Raised when a review session cannot be found in memory or database."""


class ReviewFeedbackNotFound(Exception):
    """Raised when a review feedback record cannot be found or does not belong to the target review."""


class UnknownExposureCandidate(ValueError):
    """Raised when an action references a candidate_id not present in evaluated exposures."""


class ImmutableReviewConflict(ValueError):
    """Raised when persisting or replaying a bundle with mismatched fingerprint or snapshot context."""


class InactiveFeedbackConflict(ValueError):
    """Raised when attempting to supersede or modify an already inactive feedback record."""


class ReviewIdentityUnavailable(Exception):
    """Raised when the reviewer identity mode is disabled or unconfigured."""


class ReviewDomainForbidden(Exception):
    """Raised when a principal is unauthorized for a target incident domain."""


class ReviewerRoleForbidden(Exception):
    """Raised when a principal lacks the required role to assert review feedback ground truth."""


AUTHORIZED_PO_ROLES = frozenset({"PRODUCT_OWNER", "PO", "PRINCIPAL_OPERATOR"})
AUTHORIZED_FEEDBACK_ROLES = frozenset({
    "PRODUCT_OWNER",
    "PO",
    "PRINCIPAL_OPERATOR",
    "OPERATOR",
    "ENGINEER",
    "SRE",
    "INCIDENT_COMMANDER",
})

class OperationPattern(str, Enum):
    REMOVE_MEMBER = "REMOVE_MEMBER"
    SPLIT_CHAIN = "SPLIT_CHAIN"
    MOVE_MEMBER = "MOVE_MEMBER"
    MERGE_CHAINS = "MERGE_CHAINS"
    NONE_ACCEPTABLE = "NONE_ACCEPTABLE"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"


def normalize_operation_pattern(raw: str | OperationPattern) -> OperationPattern:
    """Normalize operation pattern aliases to canonical OperationPattern."""
    if isinstance(raw, OperationPattern):
        return raw
    cleaned = str(raw).strip().upper()
    if cleaned in {"REMOVE", "REMOVE_MEMBER"}:
        return OperationPattern.REMOVE_MEMBER
    if cleaned in {"SPLIT", "SPLIT_CHAIN"}:
        return OperationPattern.SPLIT_CHAIN
    if cleaned in {"MOVE", "MOVE_MEMBER"}:
        return OperationPattern.MOVE_MEMBER
    if cleaned in {"MERGE", "MERGE_CHAINS"}:
        return OperationPattern.MERGE_CHAINS
    if cleaned in {"NONE_ACCEPTABLE"}:
        return OperationPattern.NONE_ACCEPTABLE
    if cleaned in {"MANUAL_CORRECTION", "MANUAL_SPLIT", "MANUAL_MOVE", "MANUAL_MERGE", "MANUAL_REMOVE"}:
        return OperationPattern.MANUAL_CORRECTION
    try:
        return OperationPattern(cleaned)
    except ValueError:
        raise ValueError(f"Unsupported review operation pattern: {raw!r}") from None


def normalize_review_decision(raw: str | ReviewDecision) -> ReviewDecision:
    """Normalize legacy feedback aliases only at ingress boundary."""
    if isinstance(raw, ReviewDecision):
        return raw
    cleaned = str(raw).strip().upper()
    if cleaned in {"APPROVED", "ACCEPTED", "APPROVE"}:
        return ReviewDecision.APPROVE
    if cleaned in {"REJECTED", "REJECT"}:
        return ReviewDecision.REJECT
    return ReviewDecision(cleaned)


class TruthTier(str, Enum):
    PO_ASSERTED = "PO_ASSERTED"
    EXPERT_CONSENSUS = "EXPERT_CONSENSUS"
    APPLIED_CONFIRMED = "APPLIED_CONFIRMED"
    OUTCOME_VERIFIED = "OUTCOME_VERIFIED"
    OUTCOME_CONTRADICTED = "OUTCOME_CONTRADICTED"
    TEST_FIXTURE = "TEST_FIXTURE"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"


class FeedbackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class FeedbackLifecycleType(str, Enum):
    CREATED = "CREATED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


def canonical_fingerprint(data: Any) -> str:
    """Compute deterministic SHA-256 fingerprint under sorted dictionary ordering."""
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


canonical_json_hash = canonical_fingerprint


canonical_json_hash = canonical_fingerprint


@dataclass(frozen=True)
class ReviewSession:
    """Immutable session recording the evaluation of a candidate set."""

    review_id: str
    job_id: str
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    review_time: Any
    source_kind: str
    candidate_set_fingerprint: str
    generator_version: str
    config_version: str
    lineage_component_id: str | None = None
    delay_model_version: str | None = None
    retrieval_version: str | None = None
    ranker_version: str | None = None
    exposure_policy: str = "ALL_EVALUATED"
    status: str = "COMPLETED"
    review_domain: str = "UNKNOWN_DOMAIN"
    snapshot_observed_at: Any = None
    job_completed_at: Any = None
    source_alarm_universe_fingerprint: str | None = None
    created_at: Any = ""


@dataclass(frozen=True)
class CandidateExposure:
    """Immutable capture of an evaluated candidate shown (or not shown) to reviewers."""

    review_id: str
    candidate_id: str
    candidate_fingerprint: str
    operation: str
    original_rank: int
    displayed_rank: int
    deterministic_eligibility: Any
    hard_gate_status: str
    pareto_state: str
    feature_fingerprint: str = ""
    deterministic_context: dict[str, Any] = field(default_factory=dict)
    case_context: dict[str, Any] = field(default_factory=dict)
    temporal_context: dict[str, Any] = field(default_factory=dict)
    feature_schema_version: str = "cf-features-v1"
    feature_payload: dict[str, Any] = field(default_factory=dict)
    shown_to_reviewer: bool = True
    created_at: Any = ""


class CandidateDisplaySurface(str, Enum):
    VALIDATION_TOP_CARD = "VALIDATION_TOP_CARD"
    PARETO_DRAWER = "PARETO_DRAWER"
    COMPARISON_MODAL = "COMPARISON_MODAL"
    VALIDATION_VIEW_TOP_CARD = "VALIDATION_VIEW_TOP_CARD"  # alias for backward-compatibility


@dataclass(frozen=True)
class CandidateDisplayEvent:
    display_event_id: str
    review_id: str
    candidate_id: str
    displayed_rank: int
    exposure_policy: str
    surface: str | CandidateDisplaySurface
    rendered_at: Any
    viewer_session_id: str | None = None
    client_event_id: str | None = None
    created_at: Any = ""


@dataclass(frozen=True)
class ImmutableReviewSnapshotContext:
    snapshot_id: str
    snapshot_version: str
    review_time: Any
    chain_id: str
    snapshot_observed_at: Any = None
    job_completed_at: Any = None
    review_domain: str = "UNKNOWN_DOMAIN"
    lineage_component_id: str | None = "LINEAGE_UNAVAILABLE"
    lineage_prefix_fingerprint: str | None = None
    source_kind: str = "SOURCE_KIND_UNAVAILABLE"
    taxonomy_version: str | None = None
    topology_version: str | None = None
    temporal_model_version: str | None = None
    temporal_model_cutoff: str | None = None
    temporal_corpus_fingerprint: str | None = None
    generator_version: str = "v1"
    config_version: str = "v1"
    exposure_policy_version: str = "ALL_EVALUATED"


@dataclass(frozen=True)
class SimilarCaseMatch:
    case_id: str
    review_id: str
    candidate_id: str | None
    decision: str
    truth_tier: str
    similarity_score: float
    common_block_count: int
    block_scores: dict[str, Any]
    lineage_component_id: str | None = "LINEAGE_UNAVAILABLE"
    case_domain: str = "UNKNOWN_DOMAIN"
    disclaimer: str = (
        "Historical reference only — not probability or automated recommendation. "
        "Intended solely as peer context for human decision-making."
    )


@dataclass(frozen=True)
class SimilarCaseRetrievalResult:
    retrieval_status: str  # "AVAILABLE" | "UNAVAILABLE"
    min_similarity: float = 0.65
    cross_incident_cases: list[SimilarCaseMatch] = field(default_factory=list)
    same_lineage_history: list[SimilarCaseMatch] = field(default_factory=list)
    reason: str | None = None
    common_block_count: int = 0
    required_common_block_count: int = 3
    block_scores: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = (
        "Historical reference only — not probability or automated recommendation. "
        "Intended solely as peer context for human decision-making."
    )

    def __iter__(self):
        return iter(self.cross_incident_cases)


ALLOWED_MANUAL_OPERATIONS = frozenset({
    "MANUAL_SPLIT",
    "MANUAL_MOVE",
    "MANUAL_MERGE",
    "MANUAL_REMOVE",
})


def validate_manual_correction(
    *,
    operation: str,
    partition_delta: Mapping[str, Any],
    server_chain_alarms: Sequence[str],
    server_target_chain_alarms: Sequence[str] | None = None,
    allowed_reason_codes: Sequence[str] | None = None,
    submitted_reason_code: str | None = None,
    submitted_reason_codes: Sequence[str] | None = None,
    decision: ReviewDecision | str = ReviewDecision.MANUAL_CORRECTION,
    source_chain_id: str | None = None,
    target_chain_id: str | None = None,
) -> None:
    """Validate manual correction invariants per operation.

    Rules:
    1. Operation must belong to allowed manual operations (MANUAL_SPLIT, MANUAL_MOVE, MANUAL_MERGE, MANUAL_REMOVE).
    2. Decision must be MANUAL_CORRECTION.
    3. At least one reason code must be provided and every code must be in the server policy.
    4. The affected alarm universe is strictly conserved: multiset(before) == multiset(after).
    5. 'before' alarms, if specified, must match the frozen server snapshot alarms.
    6. Source chain cannot equal target chain.
    7. No duplicate alarms across resulting partitions.
    8. For MANUAL_SPLIT: must produce >= 2 partitions strictly within source chain alarms.
    9. For MANUAL_MOVE: source and target must both be present and non-empty after move.
    10. For MANUAL_MERGE: after must have exactly 1 merged partition with all alarms.
    11. For MANUAL_REMOVE: removed alarms must be assigned to an UNASSIGNED partition in the universe.
    12. Backend constructs before universe strictly from server-side snapshot alarms.
    """
    op_clean = str(operation).strip().upper()
    if op_clean not in ALLOWED_MANUAL_OPERATIONS:
        raise ValueError(
            f"Operation {operation!r} is not an allowed manual correction operation. "
            f"Allowed: {sorted(ALLOWED_MANUAL_OPERATIONS)}"
        )

    dec_norm = normalize_review_decision(decision)
    if dec_norm != ReviewDecision.MANUAL_CORRECTION:
        raise ValueError(f"Manual correction payload is only valid for decision MANUAL_CORRECTION, got {dec_norm.value}")

    if source_chain_id and target_chain_id and str(source_chain_id) == str(target_chain_id):
        raise ValueError("Source chain cannot equal target chain in manual correction")

    # Canonicalize and validate reason codes
    all_submitted_codes: list[str] = []
    if submitted_reason_codes:
        all_submitted_codes.extend([str(c) for c in submitted_reason_codes if c])
    if submitted_reason_code and submitted_reason_code not in all_submitted_codes:
        all_submitted_codes.append(submitted_reason_code)

    if allowed_reason_codes is not None:
        if not all_submitted_codes:
            raise ValueError(f"Decision {dec_norm.value} requires at least one reason code from active policy")
        for code in all_submitted_codes:
            if code not in allowed_reason_codes:
                raise ValueError(
                    f"Reason code {code!r} is not in the active policy: {list(allowed_reason_codes)}"
                )

    source_alarms = set(server_chain_alarms)
    target_alarms = set(server_target_chain_alarms or [])
    if op_clean in {"MANUAL_SPLIT", "MANUAL_REMOVE"}:
        if target_chain_id:
            raise ValueError(f"{op_clean} must not specify target_chain_id")
        expected_universe = source_alarms
    else:
        expected_universe = source_alarms | target_alarms
    if not expected_universe:
        raise ValueError("Cannot validate manual correction against an empty frozen alarm universe")

    if op_clean in {"MANUAL_MOVE", "MANUAL_MERGE"}:
        if not server_target_chain_alarms:
            raise ValueError(f"{op_clean} requires valid server_target_chain_alarms in the snapshot")
        if not target_chain_id:
            raise ValueError(f"{op_clean} requires target_chain_id")
        if source_chain_id and target_chain_id == source_chain_id:
            raise ValueError(f"{op_clean} source_chain_id and target_chain_id cannot be the same ({source_chain_id})")

    # Validate before alarms if present
    if "before" in partition_delta:
        before_raw = partition_delta["before"]
        before_alarms = []
        if isinstance(before_raw, list):
            for item in before_raw:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    before_alarms.extend([str(a) for a in item[1]])
                elif isinstance(item, (list, tuple)):
                    before_alarms.extend([str(a) for a in item])
        elif isinstance(before_raw, dict):
            if op_clean in {"MANUAL_MOVE", "MANUAL_MERGE"} and source_chain_id and target_chain_id:
                if set(before_raw.keys()) != {source_chain_id, target_chain_id}:
                    raise ValueError(
                        f"{op_clean} before partitions must use exact keys [{source_chain_id}, {target_chain_id}], got: {sorted(before_raw.keys())}"
                    )
                if set(str(a) for a in before_raw[source_chain_id]) != source_alarms:
                    raise ValueError(f"{op_clean} before source partition alarms do not match server source chain")
                if set(str(a) for a in before_raw[target_chain_id]) != target_alarms:
                    raise ValueError(f"{op_clean} before target partition alarms do not match server target chain")
            for _, p_alarms in before_raw.items():
                before_alarms.extend([str(a) for a in p_alarms])
        if before_alarms and set(before_alarms) != expected_universe:
            raise ValueError(
                f"Manual correction 'before' alarms {sorted(set(before_alarms))} do not match server snapshot universe {sorted(expected_universe)}"
            )

    after_partitions: list[tuple[str, list[str]]] = []
    if "after" in partition_delta:
        after_raw = partition_delta["after"]
        if isinstance(after_raw, list):
            for idx, item in enumerate(after_raw):
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    p_id, p_alarms = item
                    after_partitions.append((str(p_id), [str(a) for a in p_alarms]))
                elif isinstance(item, (list, tuple)):
                    after_partitions.append((f"partition_{idx}", [str(a) for a in item]))
        elif isinstance(after_raw, dict):
            for p_id, p_alarms in after_raw.items():
                after_partitions.append((str(p_id), [str(a) for a in p_alarms]))
    elif "partitions" in partition_delta:
        for idx, p_alarms in enumerate(partition_delta["partitions"]):
            after_partitions.append((f"partition_{idx}", [str(a) for a in p_alarms]))
    else:
        raise ValueError("Manual correction partition_delta must specify 'after' or 'partitions'")

    # Check partition uniqueness
    partition_ids = [p_id for p_id, _ in after_partitions]
    if len(partition_ids) != len(set(partition_ids)):
        raise ValueError(f"Manual correction partition IDs must be unique: {partition_ids}")

    # Check alarm uniqueness and conservation
    all_after_alarms: list[str] = []
    for _, p_alarms in after_partitions:
        all_after_alarms.extend(p_alarms)

    after_set = set(all_after_alarms)
    if len(all_after_alarms) != len(after_set):
        seen = set()
        duplicates = set()
        for a in all_after_alarms:
            if a in seen:
                duplicates.add(a)
            seen.add(a)
        raise ValueError(f"Manual correction contains duplicate alarm assignments: {sorted(duplicates)}")

    if after_set != expected_universe:
        missing = expected_universe - after_set
        unexpected = after_set - expected_universe
        msg_parts = []
        if missing:
            msg_parts.append(f"Missing alarms from affected universe: {sorted(missing)}")
        if unexpected:
            msg_parts.append(f"Unexpected alarms outside affected universe: {sorted(unexpected)}")
        raise ValueError(f"Alarm universe conservation violated. {'; '.join(msg_parts)}")

    after_dict = dict(after_partitions)
    if op_clean == "MANUAL_SPLIT":
        non_empty_parts = [p for p in after_partitions if len(p[1]) > 0]
        if len(non_empty_parts) < 2:
            raise ValueError("MANUAL_SPLIT must produce at least 2 non-empty partitions")
        if after_set != source_alarms:
            raise ValueError("MANUAL_SPLIT alarms must match the source chain alarms exactly")

    elif op_clean == "MANUAL_MOVE":
        if source_chain_id and target_chain_id:
            if set(after_dict.keys()) != {source_chain_id, target_chain_id}:
                raise ValueError(
                    f"MANUAL_MOVE after partitions must use exact keys [{source_chain_id}, {target_chain_id}], got: {sorted(after_dict.keys())}"
                )
        non_empty_parts = [p for p in after_partitions if len(p[1]) > 0]
        if len(non_empty_parts) < 2:
            raise ValueError("MANUAL_MOVE must leave at least two non-empty partitions")

    elif op_clean == "MANUAL_MERGE":
        non_empty_parts = [p for p in after_partitions if len(p[1]) > 0]
        if len(non_empty_parts) != 1:
            raise ValueError("MANUAL_MERGE must result in exactly 1 merged partition")
        if source_chain_id and target_chain_id:
            merged_key = list(after_dict.keys())[0]
            valid_keys = {source_chain_id, target_chain_id, f"{source_chain_id}+{target_chain_id}"}
            if merged_key not in valid_keys:
                raise ValueError(
                    f"MANUAL_MERGE destination partition key must be one of {sorted(valid_keys)}, got {merged_key!r}"
                )

    elif op_clean == "MANUAL_REMOVE":
        unassigned_found = any("UNASSIGNED" in p_id.upper() or "OUTSIDE" in p_id.upper() for p_id, p_alarms in after_partitions if p_alarms)
        if not unassigned_found:
            raise ValueError("MANUAL_REMOVE must place removed alarms into an UNASSIGNED partition")


@dataclass(frozen=True)
class ManualCorrection:
    """Human-defined alternative partition delta when no proposed candidate was right."""

    correction_id: str
    feedback_id: str
    operation: str
    partition_delta: dict[str, Any]
    correction_fingerprint: str
    created_at: Any = ""


@dataclass(frozen=True)
class FeedbackLifecycleEvent:
    event_id: str
    feedback_id: str
    event_type: str | FeedbackLifecycleType
    actor_subject: str
    reason: str | None = None
    created_at: Any = ""


@dataclass(frozen=True)
class ReviewFeedback:
    """Append-only reviewer decision.

    Corrections never update existing records; they append a new one and supersede.
    """

    feedback_id: str
    review_id: str
    decision: ReviewDecision
    confidence: float | None = 1.0
    truth_tier: TruthTier = TruthTier.PO_ASSERTED
    status: FeedbackStatus = FeedbackStatus.ACTIVE
    candidate_id: str | None = None
    reviewer_subject: str = "system:anonymous"
    reviewer_role: str = "OPERATOR"
    domain_scope: tuple[str, ...] = ()
    reviewer_domain_scope: tuple[str, ...] = ()
    reason_policy_version: str = "v1"
    reason_codes: tuple[str, ...] = ()
    reason_text: str | None = None
    supersedes_feedback_id: str | None = None
    artifact_fingerprints: dict[str, str] = field(default_factory=dict)
    manual_correction: ManualCorrection | None = None
    created_at: Any = ""

    def __post_init__(self) -> None:
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")

        if not self.reviewer_domain_scope and self.domain_scope:
            object.__setattr__(self, "reviewer_domain_scope", self.domain_scope)
        elif not self.domain_scope and self.reviewer_domain_scope:
            object.__setattr__(self, "domain_scope", self.reviewer_domain_scope)

        if self.decision is ReviewDecision.NONE_ACCEPTABLE:
            if self.candidate_id is not None:
                raise ValueError("NONE_ACCEPTABLE cannot name a candidate_id; it is a group-level decision")
        elif self.decision in {ReviewDecision.APPROVE, ReviewDecision.REJECT}:
            if not self.candidate_id:
                raise ValueError(f"{self.decision.value} must reference a specific candidate_id")


@dataclass(frozen=True)
class ReviewCase:
    """Materialized case in the review memory store."""

    case_id: str
    review_id: str
    feedback_id: str
    case_time: Any
    lineage_component_id: str
    operation_pattern: str
    fingerprint_schema_version: str
    fingerprint_payload: dict[str, Any]
    fingerprint_hash: str
    case_domain: str = "UNKNOWN_DOMAIN"
    domain_scope: tuple[str, ...] = ()
    truth_tier: TruthTier = TruthTier.PO_ASSERTED
    outcome_status: str = "PENDING"
    candidate_id: str | None = None
    decision: ReviewDecision = ReviewDecision.APPROVE
    status: str = "ACTIVE"
    created_at: Any = ""


def compute_candidate_set_fingerprint(
    candidate_fingerprints: Sequence[str],
    generator_version: str,
    config_version: str,
    exposure_policy: str,
) -> str:
    payload = {
        "candidate_fingerprints": sorted(candidate_fingerprints),
        "generator_version": generator_version,
        "config_version": config_version,
        "exposure_policy": exposure_policy,
    }
    return canonical_fingerprint(payload)


def compute_candidate_fingerprint(
    *,
    candidate_id: str,
    operation: str,
    feature_fingerprint: str,
    displayed_rank: int,
    ranking_audit: Mapping[str, Any] | None = None,
    original_rank: int | None = None,
    delta: Mapping[str, Any] | None = None,
) -> str:
    audit_dict = dict(ranking_audit or {})
    audit_fp = canonical_fingerprint(audit_dict)
    payload: dict[str, Any] = {
        "candidate_id": str(candidate_id),
        "operation": str(operation),
        "feature_fingerprint": str(feature_fingerprint),
        "displayed_rank": int(displayed_rank),
        "audit_fingerprint": audit_fp,
    }
    if original_rank is not None:
        payload["original_rank"] = int(original_rank)
    if delta is not None:
        payload["delta"] = dict(delta)
    return canonical_fingerprint(payload)

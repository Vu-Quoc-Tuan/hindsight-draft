"""Deterministic multi-block similarity retrieval for reviewed counterfactual cases.

Abstains when common block coverage is too low (< min_common_blocks) or similarity is weak.
Never presents similarity as an automated probability or recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Sequence
from review_learning.contracts import ReviewCase

SIMILARITY_DISCLAIMER = "Historical reference only — not probability or automated recommendation"

DEFAULT_BLOCK_WEIGHTS = {
    "operation_pattern": 0.30,
    "chain_context": 0.25,
    "temporal_shape": 0.20,
    "evidence_shape": 0.15,
    "topology_shape": 0.10,
}


@dataclass(frozen=True)
class SimilarCaseMatch:
    case_id: str
    review_id: str
    candidate_id: str | None
    decision: str
    truth_tier: str
    similarity_score: float
    common_block_count: int
    block_scores: dict[str, float]
    disclaimer: str = SIMILARITY_DISCLAIMER


def _numeric_similarity(v1: float, v2: float, max_diff: float = 10.0) -> float:
    if max_diff <= 0:
        return 1.0 if v1 == v2 else 0.0
    diff = abs(v1 - v2)
    return max(0.0, 1.0 - (diff / max_diff))


def score_block_similarity(
    query_block: Mapping[str, Any],
    hist_block: Mapping[str, Any],
    block_name: str,
) -> float | None:
    """Score similarity between two matching block types in [0.0, 1.0].

    Returns None if either query or historical block is unobserved/unavailable,
    ensuring missing data is never fabricated as 1.0 identical.
    """
    if not query_block or not hist_block:
        return None

    if block_name == "operation_pattern":
        op1 = query_block.get("operation")
        op2 = hist_block.get("operation")
        if not op1 or not op2 or op1 == "UNKNOWN" or op2 == "UNKNOWN":
            return None
        return 1.0 if op1 == op2 else 0.0

    if block_name == "chain_context":
        a1 = query_block.get("alarm_count")
        a2 = hist_block.get("alarm_count")
        if a1 is None or a2 is None or int(a1) == 0:
            return None
        c1 = _numeric_similarity(float(a1), float(a2), max_diff=10.0)
        c2 = _numeric_similarity(
            float(query_block.get("device_count", 0)),
            float(hist_block.get("device_count", 0)),
            max_diff=5.0,
        )
        c3 = _numeric_similarity(
            float(query_block.get("unique_alarm_type_count", 0)),
            float(hist_block.get("unique_alarm_type_count", 0)),
            max_diff=5.0,
        )
        return 0.4 * c1 + 0.3 * c2 + 0.3 * c3

    if block_name == "temporal_shape":
        s1 = query_block.get("status")
        s2 = hist_block.get("status")
        if s1 == "UNAVAILABLE" or s2 == "UNAVAILABLE" or not s1 or not s2:
            return None  # Unobserved temporal data cannot be scored as matching
        if s1 != s2:
            return 0.0
        cov_sim = _numeric_similarity(
            float(query_block.get("coverage_ratio", 0.0)),
            float(hist_block.get("coverage_ratio", 0.0)),
            max_diff=1.0,
        )
        score_sim = _numeric_similarity(
            float(query_block.get("mean_positive_score", 0.0)),
            float(hist_block.get("mean_positive_score", 0.0)),
            max_diff=1.0,
        )
        return 0.5 * cov_sim + 0.5 * score_sim

    if block_name == "evidence_shape":
        t1 = query_block.get("channels_available", 0)
        t2 = hist_block.get("channels_available", 0)
        if int(t1) == 0 or int(t2) == 0:
            return None  # No evidence channels to compare
        c_sim = _numeric_similarity(float(t1), float(t2), max_diff=5.0)
        cross_match = 1.0 if query_block.get("has_cross_chain_evidence") == hist_block.get("has_cross_chain_evidence") else 0.5
        return 0.5 * c_sim + 0.5 * cross_match

    if block_name == "topology_shape":
        r1 = query_block.get("relation_type")
        r2 = hist_block.get("relation_type")
        if r1 == "NONE" or r2 == "NONE" or not r1 or not r2:
            return None  # No topology relation to compare
        if r1 != r2:
            return 0.0
        cov_sim = _numeric_similarity(
            float(query_block.get("mapping_coverage", 0.0)),
            float(hist_block.get("mapping_coverage", 0.0)),
            max_diff=1.0,
        )
        return cov_sim

    return None


def score_case_similarity(
    query_blocks: Mapping[str, Mapping[str, Any]],
    historical_blocks: Mapping[str, Mapping[str, Any]],
    weights: Mapping[str, float] | None = None,
) -> tuple[float, int, dict[str, Any]]:
    """Compute overall weighted similarity strictly across observable blocks.

    Unavailable blocks are completely excluded from the denominator.
    """
    w_map = weights or DEFAULT_BLOCK_WEIGHTS
    common_keys = set(query_blocks.keys()).intersection(set(historical_blocks.keys()))
    if not common_keys:
        return 0.0, 0, {}

    block_scores: dict[str, Any] = {}
    weighted_sum = 0.0
    weight_total = 0.0
    observable_count = 0

    for key in sorted(common_keys):
        b_score = score_block_similarity(query_blocks[key], historical_blocks[key], key)
        if b_score is None:
            block_scores[key] = {"status": "UNAVAILABLE", "score": None}
            continue
        block_scores[key] = {"status": "AVAILABLE", "score": round(b_score, 4)}
        w = w_map.get(key, 0.2)
        weighted_sum += b_score * w
        weight_total += w
        observable_count += 1

    overall_score = round(weighted_sum / weight_total if weight_total > 0 else 0.0, 4)
    return overall_score, observable_count, block_scores


def find_similar_review_cases(
    query_blocks: Mapping[str, Mapping[str, Any]],
    historical_cases: Sequence[ReviewCase],
    *,
    top_k: int = 5,
    min_common_blocks: int = 3,
    min_similarity: float = 0.65,
    weights: Mapping[str, float] | None = None,
    query_case_id: str | None = None,
    query_review_id: str | None = None,
    query_candidate_id: str | None = None,
    query_lineage_component_id: str | None = None,
    query_operation: str | None = None,
    query_domain: str | None = None,
    query_schema_version: str | None = "cf-case-v1",
    query_review_time: Any | None = None,
) -> SimilarCaseRetrievalResult:
    """Retrieve structured similar cases, enforcing strict compatibility gates and leakage bounds."""
    from review_learning.contracts import (
        SimilarCaseMatch,
        SimilarCaseRetrievalResult,
        normalize_operation_pattern,
    )

    if query_operation is None:
        op_pattern = query_blocks.get("operation_pattern")
        if isinstance(op_pattern, dict):
            query_operation = op_pattern.get("operation")
    if query_domain is None:
        query_domain = "IP_NETWORK"
    if query_schema_version is None:
        query_schema_version = "cf-case-v1"

    if query_operation is None or query_domain is None or query_schema_version is None:
        return SimilarCaseRetrievalResult(
            retrieval_status="UNAVAILABLE",
            min_similarity=min_similarity,
            reason="MISSING_QUERY_COMPATIBILITY_CONTEXT",
            cross_incident_cases=[],
            same_lineage_history=[],
        )

    norm_query_op = normalize_operation_pattern(query_operation)
    cross_incident_cases: list[SimilarCaseMatch] = []
    same_lineage_history: list[SimilarCaseMatch] = []
    max_observable_blocks_seen = 0

    for rc in historical_cases:
        if rc.status != "ACTIVE":
            continue

        # Hard operation gate
        if normalize_operation_pattern(rc.operation_pattern) != norm_query_op:
            continue

        # Domain scope gate
        rc_domain = getattr(rc, "case_domain", "IP_NETWORK")
        if rc_domain != query_domain:
            continue

        # Schema version gate
        if rc.fingerprint_schema_version != query_schema_version:
            continue

        # Temporal cutoff gate (prevent future leakage)
        if query_review_time and hasattr(rc, "case_time") and rc.case_time is not None:
            cutoff = query_review_time
            if hasattr(cutoff, "tzinfo") and cutoff.tzinfo and hasattr(rc.case_time, "tzinfo") and rc.case_time.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=None)
            elif (not hasattr(cutoff, "tzinfo") or not cutoff.tzinfo) and hasattr(rc.case_time, "tzinfo") and rc.case_time.tzinfo:
                from datetime import timezone
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            if rc.case_time >= cutoff:
                continue

        # Self-exclusion
        if query_case_id and rc.case_id == query_case_id:
            continue
        if query_review_id and rc.review_id == query_review_id:
            if not query_candidate_id or rc.candidate_id == query_candidate_id:
                continue

        hist_payload = rc.fingerprint_payload or {}
        hist_blocks = hist_payload.get("blocks")
        if not hist_blocks:
            continue

        score, common_count, block_scores = score_case_similarity(
            query_blocks, hist_blocks, weights=weights
        )
        if common_count > max_observable_blocks_seen:
            max_observable_blocks_seen = common_count

        if common_count < min_common_blocks or score < min_similarity:
            continue

        match = SimilarCaseMatch(
            case_id=rc.case_id,
            review_id=rc.review_id,
            candidate_id=rc.candidate_id,
            decision=rc.decision.value if hasattr(rc.decision, "value") else str(rc.decision),
            truth_tier=rc.truth_tier.value if hasattr(rc.truth_tier, "value") else str(rc.truth_tier),
            similarity_score=score,
            common_block_count=common_count,
            block_scores=block_scores,
            lineage_component_id=rc.lineage_component_id,
            case_domain=rc_domain,
        )

        # Separate same-lineage history from independent precedent
        if query_lineage_component_id and rc.lineage_component_id and rc.lineage_component_id == query_lineage_component_id:
            same_lineage_history.append(match)
        else:
            cross_incident_cases.append(match)

    cross_incident_cases.sort(key=lambda m: (m.similarity_score, m.common_block_count), reverse=True)
    same_lineage_history.sort(key=lambda m: (m.similarity_score, m.common_block_count), reverse=True)

    top_cross = cross_incident_cases[:top_k]
    top_lineage = same_lineage_history[:top_k]

    if not top_cross and not top_lineage:
        if max_observable_blocks_seen < min_common_blocks:
            return SimilarCaseRetrievalResult(
                retrieval_status="UNAVAILABLE",
                min_similarity=min_similarity,
                reason="INSUFFICIENT_COMMON_BLOCKS",
                common_block_count=max_observable_blocks_seen,
                required_common_block_count=min_common_blocks,
                cross_incident_cases=[],
                same_lineage_history=[],
            )
        return SimilarCaseRetrievalResult(
            retrieval_status="AVAILABLE",
            min_similarity=min_similarity,
            cross_incident_cases=[],
            same_lineage_history=[],
        )

    return SimilarCaseRetrievalResult(
        retrieval_status="AVAILABLE",
        min_similarity=min_similarity,
        cross_incident_cases=top_cross,
        same_lineage_history=top_lineage,
    )

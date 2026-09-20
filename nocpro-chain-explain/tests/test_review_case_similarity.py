from __future__ import annotations

from datetime import datetime, timezone

from review_learning.case_fingerprint import extract_candidate_case_blocks, compute_case_fingerprint_payload
from review_learning.case_similarity import find_similar_review_cases, score_case_similarity
from review_learning.contracts import ReviewCase, ReviewDecision, TruthTier, SimilarCaseRetrievalResult


def _make_dummy_case(
    case_id: str,
    blocks: dict,
    decision: ReviewDecision = ReviewDecision.APPROVE,
    candidate_id: str = "cand_1",
    review_id: str | None = None,
    lineage_component_id: str = "comp_1",
) -> ReviewCase:
    payload, master_hash = compute_case_fingerprint_payload(blocks)
    return ReviewCase(
        case_id=case_id,
        review_id=review_id or f"rev_{case_id}",
        feedback_id=f"fb_{case_id}",
        candidate_id=candidate_id,
        case_time=datetime.now(timezone.utc),
        lineage_component_id=lineage_component_id,
        operation_pattern="REMOVE",
        fingerprint_schema_version="cf-case-v1",
        fingerprint_payload=payload,
        fingerprint_hash=master_hash,
        case_domain="IP_NETWORK",
        decision=decision,
        truth_tier=TruthTier.PO_ASSERTED,
        status="ACTIVE",
    )


def test_similarity_scoring_all_blocks():
    blocks = {
        "operation_pattern": {"operation": "REMOVE", "removed_alarm_count": 1},
        "chain_context": {"alarm_count": 2, "device_count": 1, "unique_alarm_type_count": 1},
        "temporal_shape": {"status": "AVAILABLE", "coverage_ratio": 1.0, "mean_positive_score": 0.8},
        "evidence_shape": {"channels_available": 2, "has_cross_chain_evidence": True},
        "topology_shape": {"relation_type": "CHILD_OF", "mapping_coverage": 1.0},
    }
    score, count, block_scores = score_case_similarity(blocks, blocks)
    assert count == 5
    assert score == 1.0
    assert block_scores["operation_pattern"]["score"] == 1.0
    assert block_scores["chain_context"]["score"] == 1.0


def test_unobserved_blocks_excluded_from_denominator():
    # Only operation_pattern is observed; others are empty/unobserved
    cand = {"operation": "REMOVE", "partition_delta": {"removed_alarms": ["a1"]}}
    blocks = extract_candidate_case_blocks(
        candidate=cand,
        chain_id="C1",
        chain_alarms=[],
    )
    score, count, block_scores = score_case_similarity(blocks, blocks)
    # Only observed blocks count
    assert count == 1
    assert score == 1.0
    assert block_scores["operation_pattern"]["score"] == 1.0
    assert block_scores["temporal_shape"]["status"] == "UNAVAILABLE"
    assert block_scores["temporal_shape"]["score"] is None


def test_find_similar_cases_abstains_on_low_common_blocks():
    query_blocks = {"operation_pattern": {"operation": "REMOVE", "removed_alarm_count": 1}}
    hist_blocks = {"temporal_shape": {"status": "UNAVAILABLE"}}
    case = _make_dummy_case("c1", hist_blocks)

    # With only 0 or 1 common blocks, must return structured abstention (min_common_blocks=3)
    result = find_similar_review_cases(query_blocks, [case], min_common_blocks=3)
    assert isinstance(result, SimilarCaseRetrievalResult)
    assert result.retrieval_status == "UNAVAILABLE"
    assert result.reason == "INSUFFICIENT_COMMON_BLOCKS"
    assert len(result.cross_incident_cases) == 0
    assert len(result.same_lineage_history) == 0


def test_find_similar_cases_separates_lineage_and_cross_incident():
    blocks1 = {
        "operation_pattern": {"operation": "REMOVE", "removed_alarm_count": 1},
        "source_chain_context": {"chain_id": "C1", "alarm_count": 2},
        "temporal_shape": {"status": "AVAILABLE", "mean_delay": 5.0},
    }
    blocks2 = {
        "operation_pattern": {"operation": "REMOVE", "removed_alarm_count": 1},
        "source_chain_context": {"chain_id": "C2", "alarm_count": 2},
        "temporal_shape": {"status": "AVAILABLE", "mean_delay": 6.0},
    }

    # Case 1: same lineage component
    case_same_lineage = _make_dummy_case(
        "c_lineage", blocks1, decision=ReviewDecision.APPROVE, lineage_component_id="comp_target"
    )
    # Case 2: different lineage component (independent incident)
    case_cross = _make_dummy_case(
        "c_cross", blocks2, decision=ReviewDecision.REJECT, lineage_component_id="comp_other"
    )

    result = find_similar_review_cases(
        blocks1,
        [case_same_lineage, case_cross],
        top_k=5,
        min_similarity=0.4,
        min_common_blocks=2,
        query_lineage_component_id="comp_target",
    )

    assert result.retrieval_status == "AVAILABLE"
    assert len(result.same_lineage_history) == 1
    assert result.same_lineage_history[0].case_id == "c_lineage"
    assert len(result.cross_incident_cases) == 1
    assert result.cross_incident_cases[0].case_id == "c_cross"
    assert "not probability or automated recommendation" in result.disclaimer


def test_find_similar_cases_self_exclusion():
    blocks = {
        "operation_pattern": {"operation": "REMOVE", "removed_alarm_count": 1},
        "source_chain_context": {"chain_id": "C1", "alarm_count": 2},
        "temporal_shape": {"status": "AVAILABLE", "mean_delay": 5.0},
    }
    case_self = _make_dummy_case(
        "c_self", blocks, review_id="rev_100", candidate_id="cand_query"
    )

    result = find_similar_review_cases(
        blocks,
        [case_self],
        top_k=5,
        min_common_blocks=2,
        query_review_id="rev_100",
        query_candidate_id="cand_query",
    )
    # Self case must be strictly excluded
    assert len(result.cross_incident_cases) == 0
    assert len(result.same_lineage_history) == 0

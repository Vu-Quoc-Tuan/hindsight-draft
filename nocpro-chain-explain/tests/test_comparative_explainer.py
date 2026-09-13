from __future__ import annotations

import pytest

from tier2.counterfactual.comparative_explainer import (
    ComparativeExplanation,
    DeltaHighlight,
    build_deterministic_comparative_explanation,
    enrich_comparative_explanation_with_ai,
)


def _make_metric(val: float | None, avail: str = "AVAILABLE") -> dict:
    return {"availability": avail, "value": val, "reason": None}


def test_remove_member_comparative_explanation_vi():
    before = {
        "weak_member_count": _make_metric(2),
        "minimum_membership_support": _make_metric(0.4),
        "audit_conductance": _make_metric(0.2),
        "component_count": _make_metric(2),
        "evidence_union_coverage": _make_metric(0.75),
    }
    after = {
        "weak_member_count": _make_metric(0),
        "minimum_membership_support": _make_metric(0.65),
        "audit_conductance": _make_metric(0.2),
        "component_count": _make_metric(1),
        "evidence_union_coverage": _make_metric(0.85),
    }
    explanation = build_deterministic_comparative_explanation(
        operation="REMOVE_MEMBER",
        candidate_id="cand-remove-1",
        partition_delta=None,
        before_metrics=before,
        after_metrics=after,
        member_ids=["ALARM_001"],
        source_chain_id="6892533",
        language="vi",
    )

    assert explanation.operation == "REMOVE_MEMBER"
    assert "Đề xuất loại bỏ 1 cảnh báo" in explanation.summary_action
    assert "6892533" in explanation.summary_action
    assert len(explanation.delta_highlights) == 5

    # Check weak member delta highlight
    weak_highlight = next(h for h in explanation.delta_highlights if h["metric_name"] == "weak_member_count")
    assert weak_highlight["before"] == "2"
    assert weak_highlight["after"] == "0"
    assert weak_highlight["delta"] == "-2"
    assert weak_highlight["direction"] == "better"

    # Check min support highlight
    support_highlight = next(h for h in explanation.delta_highlights if h["metric_name"] == "minimum_membership_support")
    assert support_highlight["before"] == "40.0%"
    assert support_highlight["after"] == "65.0%"
    assert support_highlight["delta"] == "+25.0%"
    assert support_highlight["direction"] == "better"

    assert "giảm 2 cảnh báo gây nhiễu" in " ".join(explanation.comparison_points)
    assert len(explanation.why_better) > 10


def test_remove_member_comparative_explanation_en():
    before = {
        "weak_member_count": _make_metric(1),
        "minimum_membership_support": _make_metric(0.5),
    }
    after = {
        "weak_member_count": _make_metric(0),
        "minimum_membership_support": _make_metric(0.8),
    }
    explanation = build_deterministic_comparative_explanation(
        operation="REMOVE_MEMBER",
        candidate_id="cand-remove-2",
        partition_delta=None,
        before_metrics=before,
        after_metrics=after,
        member_ids=["ALARM_999"],
        source_chain_id="CHAIN_A",
        language="en",
    )

    assert "Proposal to remove 1 alarm(s)" in explanation.summary_action
    assert "CHAIN_A" in explanation.summary_action
    assert "Reduced weak member count from 1 to 0" in explanation.comparison_points[0]


def test_split_chain_comparative_explanation():
    before = {
        "component_count": _make_metric(1),
        "audit_conductance": _make_metric(0.12),
    }
    after = {
        "component_count": _make_metric(2),
        "audit_conductance": _make_metric(0.12),
    }
    evidence = {
        "audit_cut": {
            "conductance": 0.08,
            "label": "min-cut-A",
        }
    }
    explanation = build_deterministic_comparative_explanation(
        operation="SPLIT_CHAIN",
        candidate_id="cand-split-1",
        partition_delta=None,
        before_metrics=before,
        after_metrics=after,
        source_chain_id="6892487",
        operation_evidence=evidence,
        language="vi",
    )

    assert explanation.operation == "SPLIT_CHAIN"
    assert "Đề xuất phân tách chuỗi 6892487" in explanation.summary_action
    assert "min-cut-A" in explanation.summary_action
    assert any("Phi = 0.080" in pt for pt in explanation.comparison_points)
    assert "2 chuỗi con độc lập" in explanation.summary_action


def test_move_member_comparative_explanation():
    before = {
        "minimum_membership_support": _make_metric(0.35),
    }
    after = {
        "minimum_membership_support": _make_metric(0.55),
    }
    explanation = build_deterministic_comparative_explanation(
        operation="MOVE_MEMBER",
        candidate_id="cand-move-1",
        partition_delta=None,
        before_metrics=before,
        after_metrics=after,
        member_ids=["ALARM_M1"],
        source_chain_id="CHAIN_1",
        target_chain_id="CHAIN_2",
        language="vi",
    )

    assert explanation.operation == "MOVE_MEMBER"
    assert "CHAIN_1" in explanation.summary_action
    assert "CHAIN_2" in explanation.summary_action
    assert any("ưu tiên nghiêng về chuỗi đích CHAIN_2" in pt for pt in explanation.comparison_points)


def test_merge_chains_comparative_explanation():
    before = {
        "evidence_union_coverage": _make_metric(0.6),
    }
    after = {
        "evidence_union_coverage": _make_metric(0.88),
    }
    evidence = {
        "cross_chain_evidence": {
            "cross_audit_edge_count": 4,
        }
    }
    explanation = build_deterministic_comparative_explanation(
        operation="MERGE_CHAINS",
        candidate_id="cand-merge-1",
        partition_delta=None,
        before_metrics=before,
        after_metrics=after,
        source_chain_id="CHAIN_A",
        merged_chain_ids=["CHAIN_A", "CHAIN_B"],
        operation_evidence=evidence,
        language="vi",
    )

    assert explanation.operation == "MERGE_CHAINS"
    assert "Hợp nhất 2 chuỗi" in " ".join(explanation.comparison_points)
    assert any("4 liên kết" in pt for pt in explanation.comparison_points)


@pytest.mark.anyio
async def test_enrich_with_ai_fallback():
    explanation = ComparativeExplanation(
        operation="REMOVE_MEMBER",
        summary_action="Loại bỏ X",
        why_better="Gắn kết tốt hơn",
        comparison_points=["Điểm 1"],
        delta_highlights=[],
        language="vi",
    )

    enriched = await enrich_comparative_explanation_with_ai(
        explanation,
        candidate_id="cand-fallback",
        operation="REMOVE_MEMBER",
        before_metrics=None,
        after_metrics=None,
    )

    # Should safely return valid explanation even without LLM setup
    assert enriched.summary_action == "Loại bỏ X"
    assert enriched.why_better == "Gắn kết tốt hơn"


def test_public_review_result_integration_with_counterfactual_result():
    from tier2.counterfactual import analyze_counterfactual_review
    from tier2.counterfactual.public_contract import public_review_result
    from tests.test_counterfactual_analysis import (
        IDENTITY,
        CONFIG,
        _package,
        _tier1b,
        _metric_computer,
    )

    result = analyze_counterfactual_review(
        _package(),
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_metric_computer,
    )

    public_dict = public_review_result(result, package=_package(), language="vi")
    assert "evaluated_candidates" in public_dict
    assert len(public_dict["evaluated_candidates"]) == 1

    candidate = public_dict["evaluated_candidates"][0]
    assert "comparative_explanation" in candidate
    comp = candidate["comparative_explanation"]
    assert comp["operation"] == "REMOVE_MEMBER"
    assert "Đề xuất loại bỏ" in comp["summary_action"]
    assert len(comp["delta_highlights"]) > 0
    assert len(comp["why_better"]) > 0
    assert len(comp["comparison_points"]) > 0


def test_move_member_becomes_connector_explanation():
    explanation = build_deterministic_comparative_explanation(
        operation="MOVE_MEMBER",
        candidate_id="move-bridge-01",
        partition_delta=None,
        before_metrics=None,
        after_metrics=None,
        member_ids=("ALM_BRIDGE",),
        source_chain_id="6892487",
        target_chain_id="6892533",
        semantic_effects=("BECOMES_CONNECTOR",),
        structural_facts={
            "after_structural_role": "CONNECTOR",
            "after_is_articulation_point": True,
            "after_blocks_supported": 2,
        },
        language="vi",
    )

    assert "CẦU NỐI (CONNECTOR)" in explanation.summary_action
    assert "CẦU NỐI (Articulation Point)" in explanation.comparison_points[0]
    assert "2 phân đoạn mạng" in explanation.comparison_points[0]
    assert "CẦU NỐI (CONNECTOR) then chốt" in explanation.why_better
    assert "bắc cầu kết nối trực tiếp giữa 2 phân đoạn mạng" in explanation.why_better


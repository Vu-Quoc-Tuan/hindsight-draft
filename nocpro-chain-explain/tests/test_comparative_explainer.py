from __future__ import annotations

import pytest

from tier2.counterfactual.comparative_explainer import (
    ComparativeExplanation,
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

    assert "Giảm số thành viên WEAK từ 2 xuống 0" in " ".join(explanation.comparison_points)
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
    assert "Audit Graph" in explanation.summary_action
    assert "weak separation" in " ".join(explanation.comparison_points)
    assert "topology vật lý" in explanation.why_better


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
    assert any("35.0% → 55.0%" in pt for pt in explanation.comparison_points)
    assert "nhân quả chưa được xác minh" in explanation.why_better


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
    assert "hợp nhất các chuỗi" in explanation.summary_action
    assert any("Cross-audit edge count: 4" in pt for pt in explanation.comparison_points)


@pytest.mark.anyio
async def test_enrich_with_ai_fallback(monkeypatch):
    monkeypatch.setattr("nocpro_api.grounded_llm.is_provider_configured", lambda: False)
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

    assert "structural role là CONNECTOR" in explanation.comparison_points[0]
    assert "2 block" in explanation.comparison_points[0]
    assert "structural fact CONNECTOR" in explanation.why_better


def test_explanations_do_not_invent_causality_topology_or_fault_domains():
    explanations = [
        build_deterministic_comparative_explanation(
            operation="REMOVE_MEMBER",
            candidate_id="remove-1",
            partition_delta=None,
            before_metrics={"weak_member_count": _make_metric(1)},
            after_metrics={"weak_member_count": _make_metric(0)},
            member_ids=["A1"],
            source_chain_id="C1",
            language="vi",
        ),
        build_deterministic_comparative_explanation(
            operation="SPLIT_CHAIN",
            candidate_id="split-1",
            partition_delta=None,
            before_metrics={},
            after_metrics={},
            source_chain_id="C1",
            operation_evidence={"audit_cut": {"conductance": 0.08}},
            language="vi",
        ),
        build_deterministic_comparative_explanation(
            operation="MOVE_MEMBER",
            candidate_id="move-1",
            partition_delta=None,
            before_metrics={},
            after_metrics={},
            member_ids=["A1"],
            source_chain_id="C1",
            target_chain_id="C2",
            language="en",
        ),
    ]
    rendered = " ".join(
        " ".join([item.summary_action, item.why_better, *item.comparison_points])
        for item in explanations
    ).lower()
    for unsupported in (
        "nguyên nhân gốc",
        "đường lan truyền sự cố gốc",
        "không có mắt xích bắc cầu tô-pô",
        "miền sự cố độc lập",
        "chồng lấn thời gian ngẫu nhiên",
        "authentic incident context",
    ):
        assert unsupported not in rendered


@pytest.mark.anyio
async def test_comparative_explanation_temporal_spatial_context_and_ai_payload(monkeypatch: pytest.MonkeyPatch):
    from libs.contracts import load_package

    package = load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "S1",
                "snapshot_version": "1",
                "snapshot_time": "2026-03-01T10:00:00Z",
                "status": "COMPLETE",
                "source": "fixture",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-03-01T10:00:00Z",
            },
            "alarms": [
                {
                    "alarm_id": "A1",
                    "snapshot_id": "S1",
                    "device_code": "SW_CORE_01",
                    "alarm_name": "Link_Down",
                    "canonical_start_time": "2026-03-01T10:00:00Z",
                    "raw": {"location_code": ["HNI001"], "start_time": "2026-03-01T10:00:00Z"},
                },
                {
                    "alarm_id": "A2",
                    "snapshot_id": "S1",
                    "device_code": "RTR_AGG_01",
                    "alarm_name": "BGP_Neighbor_Loss",
                    "canonical_start_time": "2026-03-01T10:00:15Z",
                    "raw": {"location_code": ["HNI001"], "start_time": "2026-03-01T10:00:15Z"},
                },
            ],
            "chains": [
                {"chain_id": "C1", "snapshot_id": "S1", "member_count": 1},
                {"chain_id": "C2", "snapshot_id": "S1", "member_count": 1},
            ],
            "memberships": [
                {"chain_id": "C1", "alarm_id": "A1", "snapshot_id": "S1"},
                {"chain_id": "C2", "alarm_id": "A2", "snapshot_id": "S1"},
            ],
        }
    )

    explanation = build_deterministic_comparative_explanation(
        operation="MOVE_MEMBER",
        candidate_id="cand-move-context",
        partition_delta=None,
        before_metrics={"minimum_membership_support": _make_metric(0.4)},
        after_metrics={"minimum_membership_support": _make_metric(0.7)},
        package=package,
        member_ids=["A1"],
        source_chain_id="C1",
        target_chain_id="C2",
        language="vi",
    )

    # Check context facts
    assert explanation.context_facts is not None
    assert "HNI001" in explanation.context_facts["target_locs"]
    assert "RTR_AGG_01" in explanation.context_facts["target_dev_names"]
    assert explanation.context_facts["time_delta_seconds"] == 15

    # Check comparison points contain the business context
    comp_text = " ".join(explanation.comparison_points)
    assert "HNI001" in comp_text
    assert "RTR_AGG_01" in comp_text
    assert "15s" in comp_text

    # Check why_better is informative rather than empty/hardcoded
    assert "cùng trạm HNI001" in explanation.why_better
    assert "15s" in explanation.why_better

    # Now test enrich_comparative_explanation_with_ai with mocked render_grounded
    captured_call = {}

    def fake_render_grounded(
        *, draft, facts, fact_refs, purpose,
        requested_language=None, preserve_provider_output=False,
    ):
        captured_call["draft"] = draft
        captured_call["facts"] = facts
        captured_call["fact_refs"] = fact_refs
        captured_call["purpose"] = purpose
        from nocpro_api.grounded_llm import GroundedRenderResult
        return GroundedRenderResult(
            message="Đề xuất chuyển cảnh báo A1 sang chuỗi C2 vì cùng trạm HNI001 và khoảng cách nổ 15s.",
            model="ollama:test",
            provider_status="OK",
            used_provider=True,
        )

    monkeypatch.setattr("nocpro_api.grounded_llm.render_grounded", fake_render_grounded)
    monkeypatch.setattr("nocpro_api.grounded_llm.is_provider_configured", lambda: True)

    async def inline_to_thread(function, /, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "tier2.counterfactual.comparative_explainer.asyncio.to_thread",
        inline_to_thread,
    )

    enriched = await enrich_comparative_explanation_with_ai(
        explanation,
        candidate_id="cand-move-context",
        operation="MOVE_MEMBER",
        before_metrics=None,
        after_metrics=None,
        package=package,
        language="vi",
    )

    assert enriched.ai_narrative is not None
    assert "HNI001" in enriched.ai_narrative
    assert captured_call["facts"]["target_locs"] == ["HNI001"]
    assert captured_call["facts"]["target_dev_names"] == ["RTR_AGG_01"]
    assert captured_call["facts"]["time_delta_seconds"] == 15
    assert "location:HNI001" in captured_call["fact_refs"]
    assert "device:RTR_AGG_01" in captured_call["fact_refs"]
    assert "time_delta:15s" in captured_call["fact_refs"]
    assert captured_call["purpose"] == "ADVISOR"

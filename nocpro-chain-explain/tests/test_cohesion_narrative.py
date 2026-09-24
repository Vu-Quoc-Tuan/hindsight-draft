"""Tests for Cohesion Narrative generator and endpoint."""

import asyncio
import json
from types import SimpleNamespace

import httpx2
from nocpro_api import create_app
from nocpro_api.catalog import load_preset_payload
from nocpro_api.cohesion_advisor import (
    build_chain_quality_assessment,
    build_deterministic_cohesion_narrative,
    extract_cohesion_context,
    generate_cohesion_narrative,
    select_representative_member,
    hydrate_persisted_deep_dive,
)
from nocpro_api.workspace import Workspace
from nocpro_api.routes import _cohesion_input_fingerprint, _should_preserve_cached_cohesion
from tests.test_api import _payload


def test_vietnamese_narrative_reports_partial_topology_pair_coverage_truthfully():
    narrative = build_deterministic_cohesion_narrative(
        {
            "chain": {"chain_id": "partial", "alarm_count": 4, "is_singleton": False},
            "alarm_summary": {"top_alarm_types": [("Link Down", 3)]},
            "topology": {
                "connected_pair_count": 1,
                "pair_total": 6,
                "max_path_hops": 2,
            },
            "audit": {"status": "NOT_EVALUATED"},
        },
        language="vi",
    )

    assert "1/6 cặp resource đã ánh xạ có đường transit topology trong giới hạn 2 hop" in narrative
    assert "cùng nằm trong vùng kết nối topology" not in narrative


def test_cohesion_cache_fingerprint_changes_with_config_or_review_identity():
    service = SimpleNamespace(config=SimpleNamespace(config_version="v1"))
    base = _cohesion_input_fingerprint(
        service,
        audit_artifact=SimpleNamespace(artifact_id="audit-1"),
        deep_dive_job=SimpleNamespace(job_id="deep-1"),
        review_job=SimpleNamespace(job_id="review-1"),
    )
    changed_config = _cohesion_input_fingerprint(
        SimpleNamespace(config=SimpleNamespace(config_version="v2")),
        audit_artifact=SimpleNamespace(artifact_id="audit-1"),
        deep_dive_job=SimpleNamespace(job_id="deep-1"),
        review_job=SimpleNamespace(job_id="review-1"),
    )
    changed_review = _cohesion_input_fingerprint(
        service,
        audit_artifact=SimpleNamespace(artifact_id="audit-1"),
        deep_dive_job=SimpleNamespace(job_id="deep-1"),
        review_job=SimpleNamespace(job_id="review-2"),
    )
    assert base != changed_config
    assert base != changed_review


def test_failed_refresh_preserves_matching_provider_success_cache():
    cached = SimpleNamespace(
        input_fingerprint="same-input",
        provider_status="OK",
        model="gpt-oss:120b",
        narrative="Nhận định hoàn chỉnh trước đó.",
    )
    failed = SimpleNamespace(
        provider_status="INCOMPLETE_RESPONSE",
        model="DETERMINISTIC_EVIDENCE",
        narrative="Fallback.",
    )

    assert _should_preserve_cached_cohesion(cached, failed, "same-input") is True
    assert _should_preserve_cached_cohesion(cached, failed, "changed-input") is False
    assert _should_preserve_cached_cohesion(
        cached,
        SimpleNamespace(provider_status="OK", model="gpt-oss:120b", narrative="Bản mới."),
        "same-input",
    ) is False
    assert _should_preserve_cached_cohesion(
        SimpleNamespace(
            input_fingerprint="same-input",
            provider_status="OK",
            model="gpt-oss:120b",
            narrative="Một câu đã bị cắt giữa chừng",
        ),
        failed,
        "same-input",
    ) is False
    assert _should_preserve_cached_cohesion(
        SimpleNamespace(
            input_fingerprint="same-input",
            provider_status="OK",
            model="gpt-oss:120b",
            narrative="Chưa tạo được nhận định AI đáp ứng kiểm tra grounding. Evidence chi tiết vẫn có tại Timeline, WHY, Topology và Audit.",
        ),
        failed,
        "same-input",
    ) is False


def test_grounding_bypass_refresh_does_not_reuse_or_persist_cache():
    cached = SimpleNamespace(
        input_fingerprint="same-input",
        provider_status="OK",
        model="gpt-oss:120b",
        narrative="Nhận định đã cache.",
    )
    bypass = SimpleNamespace(
        provider_status="GROUNDING_BYPASS",
        model="gpt-oss:120b",
        narrative="Raw provider prose.",
    )

    assert _should_preserve_cached_cohesion(cached, bypass, "same-input") is False


def test_grounding_diagnostic_refresh_does_not_hide_raw_provider_prose_behind_cache():
    cached = SimpleNamespace(
        input_fingerprint="same-input",
        provider_status="OK",
        model="gpt-oss:120b",
        narrative="Nhận định đã cache.",
    )
    rejected_raw = SimpleNamespace(
        provider_status="GROUNDING_FORBIDDEN_CLAIM",
        model="gpt-oss:120b",
        narrative="Câu raw hiện tại của provider.",
    )

    assert _should_preserve_cached_cohesion(cached, rejected_raw, "same-input") is False


def test_persisted_deep_dive_projection_restores_p2_attributes():
    value = hydrate_persisted_deep_dive({
        "over_merge_strength": "MODERATE",
        "over_merge_narrative": "possible split",
        "topology_hypotheses": {
            "dominator": {
                "status": "AVAILABLE",
                "witness_resource_id": "core-1",
                "covered_resource_ids": ["r1"],
            },
            "propagation": {
                "status": "UNAVAILABLE",
                "node_scores": [],
                "hypotheses": [],
            },
        },
    })

    assert value.over_merge.strength == "MODERATE"
    assert value.topology_hypotheses.dominator.witness_resource_id == "core-1"


def test_chain_6335571_findings_are_evidence_bounded():
    payload, _profile = load_preset_payload("real_alarm_it_demo")
    workspace = Workspace()
    try:
        workspace.replace_snapshot(payload)
        context = extract_cohesion_context(workspace, "6335571")
    finally:
        workspace.close()

    findings = {
        item["finding_id"]: item for item in context["analytical_findings"]
    }
    assert findings["ALARM_CONCENTRATION"]["status"] == "AVAILABLE"
    assert "60/71" in findings["ALARM_CONCENTRATION"]["evidence"][0]
    assert findings["TEMPORAL_PROGRESSION"]["kind"] == "DERIVED"
    assert "6m 36s" in findings["TEMPORAL_PROGRESSION"]["claim"]
    assert "CAUSAL_DIRECTION_UNVERIFIED" in findings["TEMPORAL_PROGRESSION"]["limitations"]
    assert context["topology"]["mapped"] == 71
    assert context["topology"]["mapped_device_count"] == 7
    assert context["topology"]["total_device_count"] == 7
    assert context["topology"]["device_mapping_ratio"] == 1.0
    assert context["topology"]["resource_types"] == ["IT"]
    assert context["topology"]["connected_pair_count"] == 21
    assert len(context["topology"]["display_paths"]) == 6
    assert "connected_pairs" not in context["topology"]
    assert context["topology"]["display_paths_truncated"] is False
    assert all(
        path["hop_count"] == len(path["path"]) - 1
        for path in context["topology"]["display_paths"]
    )
    assert context["topology"]["max_path_hops"] == 4
    assert context["topology"]["dependency_verified"] is False
    assert context["alarm_observation_groups"]
    assert all("device" in item and "alarm_name" in item for item in context["alarm_observation_groups"])
    assert findings["SHARED_TOPOLOGY_CONTEXT"]["status"] == "AVAILABLE"
    assert "21/21" in findings["SHARED_TOPOLOGY_CONTEXT"]["evidence"][0]
    evidence_text = "\n".join(findings["SHARED_TOPOLOGY_CONTEXT"]["evidence"])
    assert all(
        " → ".join(path["path"]) in evidence_text
        for path in context["topology"]["display_paths"][:2]
    )
    assert "TRANSIT_CONNECTIVITY_IS_NOT_CAUSAL_DEPENDENCY" in findings["SHARED_TOPOLOGY_CONTEXT"]["limitations"]

    briefing = build_deterministic_cohesion_narrative(context, language="vi")
    assert "mẫu đồng diễn" in briefing
    assert "Counterfactual" not in briefing
    assert "thiết bị đã ánh xạ" not in briefing
    assert len(briefing) < 700

    rendered = json.dumps(context, ensure_ascii=False)
    for unsupported in (
        "Root/Trigger",
        "kích hoạt chuỗi",
        "dependent servers",
        "không có điểm đứt gãy",
    ):
        assert unsupported not in rendered


def test_audit_finding_explains_no_low_conductance_cut_in_plain_language():
    payload, _profile = load_preset_payload("real_alarm_it_demo")
    workspace = Workspace()
    audit_artifact = SimpleNamespace(
        status="AVAILABLE",
        verdict="NO_LOW_CONDUCTANCE_CUT",
        reason=(
            "best candidate (device_code=10.210.48.136) UNION "
            "(device_code=10.210.48.96): Phi=0.6163 > epsilon=0.3000"
        ),
        epsilon=0.3,
        best_cut_index=0,
        scored_cuts=(
            SimpleNamespace(
                label="(device_code=10.210.48.136) UNION (device_code=10.210.48.96)",
                phi=0.6163,
            ),
        ),
    )
    try:
        workspace.replace_snapshot(payload)
        context = extract_cohesion_context(
            workspace,
            "6335571",
            audit_artifact=audit_artifact,
        )
    finally:
        workspace.close()

    finding = next(
        item for item in context["analytical_findings"]
        if item["finding_id"] == "AUDIT_COHESION"
    )
    assert "không tìm thấy ranh giới đủ yếu" in finding["claim"]
    assert any("0.616" in item and "0.300" in item for item in finding["evidence"])
    assert "Audit Graph đo độ gắn kết evidence" in finding["evidence"][-1]


def test_chain_quality_assessment_rates_complete_cohesive_evidence_five_stars():
    assessment = build_chain_quality_assessment(
        alarm_count=71,
        role_counts={"CORE": 60, "PERIPHERAL": 11},
        mapped_device_count=7,
        total_device_count=7,
        connected_pair_count=21,
        pair_total=21,
        audit_status="EVALUATED",
        audit_verdict="NO_LOW_CONDUCTANCE_CUT",
        over_merge_strength="NONE",
        recommendation_count=0,
        recommendation_status="NO_CLEAR_ALTERNATIVE",
    )

    assert assessment["status"] == "EVALUATED"
    assert assessment["stars"] == 5
    assert assessment["label"] == "Rất vững"
    assert assessment["method"] == "HEURISTIC_V1"


def test_chain_quality_assessment_does_not_turn_missing_evidence_into_one_star():
    assessment = build_chain_quality_assessment(
        alarm_count=10,
        role_counts={"CORE": 4, "INSUFFICIENT_DATA": 6},
        mapped_device_count=0,
        total_device_count=4,
        connected_pair_count=0,
        pair_total=0,
        audit_status="NOT_EVALUATED",
        audit_verdict=None,
        over_merge_strength=None,
        recommendation_count=0,
        recommendation_status="NOT_EVALUATED",
    )

    assert assessment["status"] == "UNAVAILABLE"
    assert assessment["stars"] is None
    assert assessment["label"] == "Chưa thể chấm"


def test_unavailable_over_merge_does_not_count_as_an_independent_quality_dimension():
    assessment = build_chain_quality_assessment(
        alarm_count=2,
        role_counts={"CORE": 2},
        mapped_device_count=0,
        total_device_count=0,
        connected_pair_count=0,
        pair_total=0,
        audit_status="NOT_APPLICABLE",
        audit_verdict="SKIPPED_SMALL_CHAIN",
        over_merge_strength="UNAVAILABLE",
        recommendation_count=0,
        recommendation_status="NOT_EVALUATED",
    )

    assert assessment["status"] == "UNAVAILABLE"
    assert assessment["stars"] is None
    assert assessment["available_dimension_count"] == 2


def test_chain_quality_assessment_caps_split_and_over_merge_signals():
    assessment = build_chain_quality_assessment(
        alarm_count=20,
        role_counts={"CORE": 20},
        mapped_device_count=5,
        total_device_count=5,
        connected_pair_count=10,
        pair_total=10,
        audit_status="EVALUATED",
        audit_verdict="CANDIDATE_SPLIT",
        over_merge_strength="MODERATE",
        recommendation_count=1,
        recommendation_status="AVAILABLE",
    )

    assert assessment["status"] == "EVALUATED"
    assert assessment["stars"] <= 2
    assert assessment["label"] == "Có dấu hiệu nên tách"


def test_chain_quality_assessment_does_not_award_five_stars_before_counterfactual_runs():
    assessment = build_chain_quality_assessment(
        alarm_count=20,
        role_counts={"CORE": 20},
        mapped_device_count=5,
        total_device_count=5,
        connected_pair_count=10,
        pair_total=10,
        audit_status="EVALUATED",
        audit_verdict="NO_LOW_CONDUCTANCE_CUT",
        over_merge_strength="NONE",
        recommendation_count=0,
        recommendation_status="NOT_EVALUATED",
    )

    assert assessment["stars"] == 4
    assert any("Counterfactual" in reason for reason in assessment["reasons"])


def test_context_selects_core_member_as_evidence_representative_not_root_cause():
    members = {
        "peripheral": SimpleNamespace(
            alarm_id="peripheral",
            role=SimpleNamespace(verdict=SimpleNamespace(value="PERIPHERAL"), gate=SimpleNamespace(availability_coverage=1, computable_groups=4)),
            support=SimpleNamespace(support=0.99),
            representativeness=0.99,
        ),
        "core": SimpleNamespace(
            alarm_id="core",
            role=SimpleNamespace(verdict=SimpleNamespace(value="CORE"), gate=SimpleNamespace(availability_coverage=1, computable_groups=3)),
            support=SimpleNamespace(support=0.70),
            representativeness=0.70,
        ),
    }
    alarms = {
        "core": SimpleNamespace(alarm_name="Core alarm", device_code="R1", node_reference=None),
        "peripheral": SimpleNamespace(alarm_name="Peripheral alarm", device_code="R2", node_reference=None),
    }
    representative = select_representative_member(members, alarms)
    assert representative["role"] == "CORE"
    assert representative["selection_semantic"] == "EVIDENCE_REPRESENTATIVE_NOT_ROOT_CAUSE"


def test_context_marks_representative_unavailable_without_core_or_peripheral_evidence():
    representative = select_representative_member(
        {
            "weak": SimpleNamespace(
                role=SimpleNamespace(verdict=SimpleNamespace(value="WEAK")),
                support=SimpleNamespace(support=0.99),
            ),
        },
        {},
    )

    assert representative["status"] == "UNAVAILABLE"
    assert representative["selection_semantic"] == "NO_CORE_OR_PERIPHERAL_EVIDENCE_REPRESENTATIVE"


def test_context_resolves_selected_counterfactual_without_repeating_it_in_narrative():
    payload, _profile = load_preset_payload("real_alarm_it_demo")
    workspace = Workspace()
    review_result = {
        "recommendation_status": "AVAILABLE",
        "recommendations": [{"candidate_id": "split-1"}],
        "evaluated_candidates": [{
            "candidate_id": "split-1",
            "operation": "SPLIT_CHAIN",
            "comparative_explanation": {
                "summary_action": "Tách chuỗi thành hai nhóm bằng chứng.",
                "why_better": "Giảm thành viên yếu và tăng độ phủ bằng chứng.",
            },
        }],
    }
    try:
        workspace.replace_snapshot(payload)
        context = extract_cohesion_context(
            workspace,
            "6335571",
            review_result=review_result,
        )
    finally:
        workspace.close()

    assert context["recommendations"]["status"] == "AVAILABLE"
    assert context["recommendations"]["count"] == 1
    assert context["recommendations"]["split_recommended"] is True
    assert context["recommendations"]["best_alternative"]["why_better"].startswith("Giảm thành viên yếu")
    narrative = build_deterministic_cohesion_narrative(context, language="vi")
    assert "Counterfactual" not in narrative
    assert "phương án" not in narrative


def test_completed_locked_counterfactual_is_reported_as_evaluated_not_unrun():
    payload, _profile = load_preset_payload("real_alarm_ip_demo")
    workspace = Workspace()
    review_result = {
        "status": "AVAILABLE",
        "reason": "COUNTERFACTUAL_POLICY_NOT_CALIBRATED",
        "calibration_status": "SYNTHETIC_ONLY",
        "recommendation_status": "UNAVAILABLE",
        "recommendations": [],
        "evaluated_candidates": [
            {
                "candidate_id": "split-pass",
                "operation": "SPLIT_CHAIN",
                "hard_gate_result": {"status": "PASSED", "reason": None},
            },
            {
                "candidate_id": "remove-rejected",
                "operation": "REMOVE_MEMBER",
                "hard_gate_result": {"status": "REJECTED", "reason": "AUDIT_SEVERITY_WORSENED"},
            },
        ],
    }
    try:
        workspace.replace_snapshot(payload)
        context = extract_cohesion_context(
            workspace,
            "6913556",
            review_result=review_result,
        )
    finally:
        workspace.close()

    assert context["recommendations"]["status"] == "UNAVAILABLE"
    assert context["recommendations"]["evaluation_completed"] is True
    assert context["recommendations"]["evaluated_count"] == 2
    assert context["recommendations"]["rejected_count"] == 1
    narrative = build_deterministic_cohesion_narrative(context, language="vi")
    assert "Counterfactual" not in narrative
    assert "hard gate" not in narrative.lower()
    assert "policy" not in narrative.lower()
    assert "thiết bị đã ánh xạ" not in narrative
    assert "evidence mạnh nhất" not in narrative


def test_candidate_split_narrative_names_both_groups_linkage_and_weak_boundary():
    payload, _profile = load_preset_payload("real_alarm_ip_demo")
    workspace = Workspace()
    try:
        workspace.replace_snapshot(payload)
        package = workspace.require_package()
        alarms = list(package.alarms_of("6913556"))
        by_device: dict[str, list[object]] = {}
        for alarm in alarms:
            by_device.setdefault(str(alarm.device_code), []).append(alarm)
        left = next(group for group in by_device.values() if len(group) >= 2)
        left_ids = {str(alarm.alarm_id) for alarm in left}
        right_ids = {str(alarm.alarm_id) for alarm in alarms} - left_ids
        assert right_ids
        left_id = sorted(left_ids)[0]
        right_id = sorted(right_ids)[0]
        second_left_id = sorted(left_ids)[1]
        audit_artifact = SimpleNamespace(
            status="AVAILABLE",
            verdict="CANDIDATE_SPLIT",
            reason="low-conductance candidate",
            epsilon=0.3,
            best_cut_index=0,
            scored_cuts=(SimpleNamespace(
                source="ENTITY",
                label=f"device_code={left[0].device_code}",
                members=tuple(sorted(left_ids)),
                phi=0.1,
            ),),
            visualization=SimpleNamespace(
                status="AVAILABLE",
                truncated=False,
                edges=(
                    SimpleNamespace(
                        source_alarm_id=left_id,
                        target_alarm_id=right_id,
                        weight=0.2,
                        supporting_groups=("temporal_burst", "dependency_hop"),
                        crosses_best_cut=True,
                    ),
                    SimpleNamespace(
                        source_alarm_id=left_id,
                        target_alarm_id=second_left_id,
                        weight=0.9,
                        supporting_groups=("device", "temporal_burst"),
                        crosses_best_cut=False,
                    ),
                ),
            ),
        )
        context = extract_cohesion_context(
            workspace,
            "6913556",
            audit_artifact=audit_artifact,
        )
    finally:
        workspace.close()

    partition = context["audit"]["partition_summary"]
    assert partition["side_a"]["alarm_count"] == len(left_ids)
    assert partition["side_b"]["alarm_count"] == len(right_ids)
    assert partition["separation"]["cross_edge_count"] == 1
    assert partition["separation"]["internal_edge_count"] == 1
    assert {item["group"] for item in partition["linkage"]["supporting_groups"]} == {
        "temporal_burst",
        "dependency_hop",
    }
    narrative = build_deterministic_cohesion_narrative(context, language="vi")
    assert "ranh giới giữa hai cụm quan sát" in narrative
    assert str(left[0].device_code) in narrative
    assert "xuất hiện gần nhau về thời gian" in narrative
    assert "có đường liên kết topology" in narrative
    assert "Điểm yếu nằm ở ranh giới này" in narrative
    assert "Counterfactual" not in narrative


def test_deterministic_cohesion_narrative_natural_tone():
    """Verify that narrative is domain-appropriate, natural, and never stiff or hallucinated."""
    # Scenario A: IP Core chain with candidate cut
    context_a = {
        "chain": {"chain_id": "6892935", "alarm_count": 44, "duration_seconds": 31, "is_singleton": False},
        "alarm_summary": {
            "top_alarm_types": [["OPTICAL_POWER_RX_LOW", 8], ["LOSS_OF_SIGNAL", 2]],
            "network_classes": ["IP_CORE"],
            "devices": ["ROUTER-01", "ROUTER-02"],
        },
        "topology": {
            "mapped": 31,
            "total": 44,
            "resource_types": ["IP_ROUTER", "OPTICAL_PORT"],
        },
        "audit": {"status": "EVALUATED", "verdict": "CANDIDATE_SPLIT", "candidate_cut": True, "conductance": 0.12},
        "recommendations": {"split_recommended": False},
    }
    narrative_a = build_deterministic_cohesion_narrative(context_a)
    assert "6892935" in narrative_a
    assert "IP_CORE" in narrative_a
    assert "OPTICAL_POWER_RX_LOW" in narrative_a
    assert "Structural audit detected a low-conductance separation boundary" in narrative_a
    assert "conductance 0.12" in narrative_a
    assert "DWDM" not in narrative_a
    assert "passive fiber" not in narrative_a

    # Scenario B: Single alarm singleton - strictly neutral without speculative isolation claims
    context_b = {
        "chain": {"chain_id": "6892337", "alarm_count": 1, "duration_seconds": None, "is_singleton": True},
        "alarm_summary": {
            "top_alarm_types": [["REPT-LKF: not aligned", 1]],
            "network_classes": ["CORE"],
            "devices": ["STPV01"],
        },
        "topology": {"mapped": 0, "total": 1, "resource_types": []},
        "audit": {"status": "NOT_EVALUATED", "verdict": None, "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_b = build_deterministic_cohesion_narrative(context_b)
    assert "This chain contains one observed alarm" in narrative_b
    assert "Multi-member cohesion and propagation analysis are not applicable" in narrative_b
    assert "isolated" not in narrative_b
    assert "no cross-device" not in narrative_b
    assert "DWDM" not in narrative_b

    # Scenario C: Counterfactual state stays outside the investigation narrative
    context_c = {
        "chain": {"chain_id": "C-SPLIT", "alarm_count": 20, "duration_seconds": 120, "is_singleton": False},
        "alarm_summary": {
            "top_alarm_types": [["BGP_DOWN", 10], ["LINK_DOWN", 10]],
            "network_classes": ["IP_CORE"],
            "devices": ["CORE-PE1", "CORE-PE2"],
        },
        "topology": {"mapped": 20, "total": 20, "resource_types": ["ROUTER"]},
        "audit": {"status": "EVALUATED", "verdict": "CANDIDATE_SPLIT", "candidate_cut": True, "conductance": 0.05},
        "recommendations": {"split_recommended": True},
    }
    narrative_c = build_deterministic_cohesion_narrative(context_c)
    assert "evidence is stronger within the groups" in narrative_c
    assert "recommended" not in narrative_c

    # Scenario D: Evaluated with NO_LOW_CONDUCTANCE_CUT
    context_d = {
        "chain": {"chain_id": "C-SOLID", "alarm_count": 10, "duration_seconds": 15, "is_singleton": False},
        "alarm_summary": {"top_alarm_types": [["LINK_DOWN", 10]], "network_classes": ["IP_CORE"], "devices": ["PE-01"]},
        "topology": {"mapped": 10, "total": 10, "resource_types": ["ROUTER"]},
        "audit": {"status": "EVALUATED", "verdict": "NO_LOW_CONDUCTANCE_CUT", "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_d = build_deterministic_cohesion_narrative(context_d)
    assert "Structural audit evaluated candidate partitions and detected no low-conductance partition boundaries" in narrative_d

    # Scenario E: SKIPPED_SMALL_CHAIN
    context_e = {
        "chain": {"chain_id": "C-SMALL", "alarm_count": 3, "duration_seconds": 10, "is_singleton": False},
        "alarm_summary": {"top_alarm_types": [["LINK_DOWN", 3]], "network_classes": ["IP_CORE"], "devices": ["PE-01"]},
        "topology": {"mapped": 3, "total": 3, "resource_types": ["ROUTER"]},
        "audit": {"status": "NOT_APPLICABLE", "verdict": "SKIPPED_SMALL_CHAIN", "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_e = build_deterministic_cohesion_narrative(context_e)
    assert "Structural audit balance constraints are not applicable for this small chain structure" in narrative_e

    # Scenario F: Not Evaluated Audit (Honest data truth)
    context_f = {
        "chain": {"chain_id": "C-NO-AUDIT", "alarm_count": 10, "duration_seconds": 15, "is_singleton": False},
        "alarm_summary": {"top_alarm_types": [["LINK_DOWN", 10]], "network_classes": ["IP_CORE"], "devices": ["PE-01"]},
        "topology": {"mapped": 0, "total": 10, "resource_types": []},
        "audit": {"status": "NOT_EVALUATED", "verdict": None, "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_f = build_deterministic_cohesion_narrative(context_f)
    assert "Tier-2 structural audit has not been performed for this chain" in narrative_f


def test_api_cohesion_narrative_endpoint(monkeypatch):
    """Verify endpoint runs in offline isolation and accurately reports un-evaluated audit."""
    # Ensure provider doesn't hit external network by clearing API keys and forcing deterministic rendering
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OPENAI_COMPATIBLE")

    from nocpro_api import grounded_llm

    def fake_render_grounded(
        draft: str,
        facts: dict,
        fact_refs: list,
        purpose: str = "ADVISOR",
        timeout_seconds: float = 8.0,
        **_kwargs,
    ):
        return grounded_llm.GroundedRenderResult(
            message="",
            model="test-model",
            provider_status="DISABLED",
        )

    # Patch the exact import target inside cohesion_advisor
    monkeypatch.setattr("nocpro_api.cohesion_advisor.render_grounded", fake_render_grounded)

    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                loaded = await client.post("/api/v1/snapshots", json=_payload())
                assert loaded.status_code == 201

                narrative_resp = await client.get("/api/v1/chains/C1/cohesion-narrative")
                assert narrative_resp.status_code == 200
                res_json = narrative_resp.json()
                assert res_json["chain_id"] == "C1"
                assert res_json["narrative"] == ""
                assert "context" in res_json
                assert "alarm_summary" in res_json["context"]
                assert "why" in res_json["context"]
                assert "topology" in res_json["context"]
                assert "audit" in res_json["context"]
                # Must be NOT_EVALUATED since Tier-2 Deep Dive hasn't run
                assert res_json["context"]["audit"]["status"] == "NOT_EVALUATED"
                assert res_json["provider_status"] == "DISABLED"
                assert "recommendations" in res_json["context"]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_ai_investigation_accepts_detailed_grounded_prose_without_template(monkeypatch):
    monkeypatch.delenv("AI_COHESION_TIMEOUT_SECONDS", raising=False)
    payload, _profile = load_preset_payload("real_alarm_ip_demo")
    workspace = Workspace()
    captured: dict[str, object] = {}
    message = (
        "Các thay đổi giao thức tập trung ở hai đầu của cùng vùng kết nối, trong khi nhóm cảnh báo thiết bị xuất hiện muộn hơn. "
        "Sự gần nhau về thời gian cùng đường topology làm quan hệ này đáng kiểm tra, nhưng chưa chứng minh được hướng lan truyền. "
        "Audit không thấy một đường tách đủ yếu, nên evidence hiện nghiêng về một sự cố chung hơn là hai sự kiện độc lập. "
        "Kỹ sư nên đối chiếu phiên và cổng trên các thiết bị được nêu trong đường topology trước khi kết luận nguyên nhân."
    )

    def fake_render_grounded(
        *,
        draft: str,
        facts: dict,
        fact_refs: list,
        purpose: str,
        timeout_seconds: float,
        **_kwargs,
    ):
        captured.update(
            {
                "draft": draft,
                "facts": facts,
                "fact_refs": fact_refs,
                "purpose": purpose,
                "timeout_seconds": timeout_seconds,
                "requested_language": _kwargs.get("requested_language"),
                "preserve_provider_output": _kwargs.get("preserve_provider_output"),
            }
        )
        from nocpro_api.grounded_llm import GroundedRenderResult
        return GroundedRenderResult(
            message=message,
            model="test-model",
            provider_status="OK",
            used_provider=True,
        )

    monkeypatch.setattr("nocpro_api.cohesion_advisor.render_grounded", fake_render_grounded)
    try:
        workspace.replace_snapshot(payload)
        result = generate_cohesion_narrative(workspace, "6913556", language="vi")
    finally:
        workspace.close()

    assert result.narrative == message
    assert result.model == "test-model"
    assert captured["purpose"] == "COHESION"
    assert captured["timeout_seconds"] == 60.0
    instruction = captured["facts"]["instruction"]
    assert "insight" in instruction
    assert "evidence" in instruction
    assert "kiểm tra vận hành" in instruction
    assert "giả thuyết" in instruction
    assert "3 đến 5 câu" not in instruction
    assert "tối đa" not in instruction
    evidence = captured["facts"]["investigation_evidence"]
    assert evidence["alarm_groups"]
    assert "topology" in evidence
    assert "audit" in evidence
    assert "tier2" in evidence
    assert len(json.dumps(captured["facts"], ensure_ascii=False, separators=(",", ":"), default=str)) < 8_000
    assert "Dữ liệu cho thấy một mẫu" not in captured["draft"]
    assert captured["requested_language"] == "vi"
    assert captured["preserve_provider_output"] is True


def test_ai_investigation_keeps_raw_provider_prose_when_grounding_rejects_it(monkeypatch):
    payload, _profile = load_preset_payload("real_alarm_ip_demo")
    workspace = Workspace()
    raw_provider_message = "Root cause proven: Router-Z caused the incident."

    def fake_render_grounded(**_kwargs):
        from nocpro_api.grounded_llm import GroundedRenderResult

        return GroundedRenderResult(
            message=raw_provider_message,
            model="test-model",
            provider_status="GROUNDING_FORBIDDEN_CLAIM",
            used_provider=True,
        )

    monkeypatch.setattr("nocpro_api.cohesion_advisor.render_grounded", fake_render_grounded)
    try:
        workspace.replace_snapshot(payload)
        result = generate_cohesion_narrative(workspace, "6913556", language="vi")
    finally:
        workspace.close()

    assert result.narrative == raw_provider_message
    assert result.model == "test-model"
    assert result.provider_status == "GROUNDING_FORBIDDEN_CLAIM"


def test_ai_investigation_does_not_reject_a_grounded_detailed_answer_by_sentence_count(
    monkeypatch,
):
    payload, _profile = load_preset_payload("real_alarm_ip_demo")
    workspace = Workspace()
    message = " ".join(
        [
            "Các cảnh báo giao thức cùng xuất hiện trên các thiết bị đã quan sát.",
            "Đường topology cung cấp ngữ cảnh kết nối cấu trúc.",
            "Thứ tự thời gian chỉ là thứ tự quan sát.",
            "Audit chưa chứng minh quan hệ nhân quả.",
            "Thành viên đại diện chỉ là điểm neo evidence.",
            "Các cảnh báo còn lại cần được đối chiếu theo phiên.",
            "Kỹ sư nên kiểm tra đúng thiết bị và đường topology đã nêu.",
        ]
    )

    def fake_render_grounded(**_kwargs):
        from nocpro_api.grounded_llm import GroundedRenderResult
        return GroundedRenderResult(
            message=message,
            model="test-model",
            provider_status="OK",
            used_provider=True,
        )

    monkeypatch.setattr("nocpro_api.cohesion_advisor.render_grounded", fake_render_grounded)
    try:
        workspace.replace_snapshot(payload)
        result = generate_cohesion_narrative(workspace, "6913556", language="vi")
    finally:
        workspace.close()

    assert result.narrative == message
    assert result.provider_status == "OK"


def test_cohesion_narrative_rich_p2_and_operational_insights():
    """Verify that P2 deep dive facts enrich context, findings, and generate actionable operational insights."""
    payload, _profile = load_preset_payload("real_alarm_it_demo")
    workspace = Workspace()
    try:
        workspace.replace_snapshot(payload)
        deep_dive_analysis = SimpleNamespace(
            topology_hypotheses=SimpleNamespace(
                dominator=SimpleNamespace(
                    status=SimpleNamespace(value="AVAILABLE"),
                    witness_resource_id="10.210.48.136",
                    covered_resource_ids=("10.210.48.136", "10.210.48.96"),
                    semantic="DOMINATOR",
                    relation_type="TRANSIT",
                ),
                propagation=SimpleNamespace(
                    status=SimpleNamespace(value="AVAILABLE"),
                    candidate_node_count=2,
                    candidate_edge_count=1,
                    node_scores=(SimpleNamespace(alarm_id="ALM-1", score=0.75),),
                    hypotheses=(
                        SimpleNamespace(
                            source_alarm_id="6335571",
                            target_alarm_id="6335572",
                            score=0.88,
                            transition_probability=0.85,
                            temporal_delta_seconds=12.5,
                        ),
                    ),
                ),
                dependency_scope=None,
            ),
            evidence_attribution=SimpleNamespace(
                status=SimpleNamespace(value="AVAILABLE"),
                total_coverage=0.92,
                contributions=(
                    SimpleNamespace(
                        group_id="TEMPORAL_BURST",
                        derivation_tag="BURST",
                        attribution=0.65,
                        supported_pair_count=18,
                    ),
                    SimpleNamespace(
                        group_id="TOPOLOGY_TRANSIT",
                        derivation_tag="TRANSIT",
                        attribution=0.27,
                        supported_pair_count=8,
                    ),
                ),
            ),
            over_merge=SimpleNamespace(
                structural_separation=False,
                cross_evidence_agreement=False,
                strength=SimpleNamespace(value="NONE"),
                narrative="Chuỗi có tính gắn kết bằng chứng cao",
                driving_evidence=(),
            ),
            structural_roles={},
        )
        audit_artifact = SimpleNamespace(
            status="AVAILABLE",
            verdict="NO_LOW_CONDUCTANCE_CUT",
            reason="Phi=0.6163 > epsilon=0.3000",
            epsilon=0.3,
            best_cut_index=0,
            scored_cuts=(
                SimpleNamespace(
                    label="Part A vs Part B",
                    phi=0.6163,
                ),
            ),
        )

        context = extract_cohesion_context(
            workspace,
            "6335571",
            audit_artifact=audit_artifact,
            deep_dive_analysis=deep_dive_analysis,
        )

        # 1. Verify P2 enriched facts
        assert "tier2_p2" in context
        p2 = context["tier2_p2"]
        assert p2["dominator"]["witness_resource_id"] == "10.210.48.136"
        assert len(p2["dominator"]["covered_resource_ids"]) == 2
        assert p2["propagation"]["hypotheses"][0]["prob"] == 0.85
        assert len(p2["evidence_attribution"]["contributions"]) == 2

        # 2. Verify Operational Insights
        assert "operational_insights" in context
        op = context["operational_insights"]
        assert op["primary_focus"] is not None
        assert op["cohesion_verdict"] == "STRONG"
        assert op["actionable_takeaway"] is not None
        assert "tập trung xử lý tại thiết bị khởi phát" in op["actionable_takeaway"]

        # 3. Verify Analytical Findings include Dominator & Propagation
        findings = {item["finding_id"]: item for item in context["analytical_findings"]}
        assert "TOPOLOGY_DOMINATOR_WITNESS" in findings
        assert "10.210.48.136" in findings["TOPOLOGY_DOMINATOR_WITNESS"]["claim"]
        assert "TOPOLOGY_PROPAGATION_FLOW" in findings
        assert findings["TOPOLOGY_PROPAGATION_FLOW"]["status"] == "AVAILABLE"

        # 4. Verify the overview narrative stays short and adds an insight
        # instead of repeating the rating/topology cards.
        briefing = build_deterministic_cohesion_narrative(context, language="vi")
        assert "mẫu đồng diễn" in briefing
        assert "Chuỗi 6335571" not in briefing
        assert "Audit chưa tìm thấy ranh giới đủ yếu" in briefing
        assert "4/5 sao" not in briefing
        assert "thiết bị đã ánh xạ" not in briefing
        assert len(briefing) < 700
    finally:
        workspace.close()

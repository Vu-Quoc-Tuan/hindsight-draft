"""Tests for Explain Clarity Comparator and Threshold Explain Optimizer."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
import pytest
import httpx2

from tests.test_api import run_api_test
from nocpro_api.threshold_explain_optimizer import (
    apply_explain_threshold,
    find_clearest_explain_threshold,
)
from tier2.counterfactual.explain_clarity_comparator import (
    compare_proposal_explanations,
    compare_two_explanations,
    evaluate_explain_clarity,
)


def test_evaluate_explain_clarity_empty() -> None:
    score, dims = evaluate_explain_clarity("")
    assert score == 0.0
    assert len(dims) == 4
    for d in dims:
        assert d.score == 0.0


def test_evaluate_explain_clarity_vague_vs_specific() -> None:
    vague_text = "Chuỗi có một số cảnh báo, có thể có nhiều yếu tố chưa rõ ràng."
    specific_text = (
        "Cảnh báo LINK_DOWN trên trạm CMU0009AGG01 là nguyên nhân trực tiếp dẫn đến mất kết nối "
        "3 trạm BTS vệ tinh phía sau. Khuyến nghị bóc tách cảnh báo nguồn ngoại lai để tập trung xử lý tuyến quang."
    )

    vague_score, vague_dims = evaluate_explain_clarity(vague_text)
    specific_score, specific_dims = evaluate_explain_clarity(specific_text)

    assert specific_score > vague_score
    assert specific_score >= 70.0
    assert vague_score < 50.0

    # Specificity check
    spec_dim = next(d for d in specific_dims if d.name == "specificity")
    assert any("CMU0009AGG01" in s or "LINK_DOWN" in s for s in spec_dim.strengths)

    # Causality check
    caus_dim = next(d for d in specific_dims if d.name == "causality")
    assert len(caus_dim.strengths) > 0


def test_compare_two_explanations_picks_clearer() -> None:
    exp_a = "Chuỗi có một số cảnh báo liên kết yếu, conductance 0.22, chưa rõ nguyên nhân cụ thể."
    exp_b = (
        "Cảnh báo LINK_DOWN tại trạm HGG0007 là nguyên nhân gốc làm mất kết nối 3 trạm vệ tinh. "
        "Cảnh báo POWER tại trạm BLU0006 là sự cố nguồn độc lập. Khuyến nghị bóc tách nguồn để xử lý tuyến quang."
    )

    res = compare_two_explanations(
        exp_a,
        exp_b,
        label_a="Explain Ngưỡng Cũ",
        label_b="Explain Ngưỡng Mới",
    )

    assert res.winner == "B"
    assert res.clarity_score_b > res.clarity_score_a
    assert res.score_delta > 0
    assert len(res.why_clearer) >= 2
    # Ensure reasons explain why winner is clearer in specificity, causality, actionability
    joined_reasons = " ".join(res.why_clearer)
    assert "tính cụ thể" in joined_reasons.lower() or "tính nhân quả" in joined_reasons.lower()
    assert "Explain Ngưỡng Mới" in res.summary_verdict


def test_compare_two_explanations_tie() -> None:
    exp = "Cảnh báo LINK_DOWN tại Router SW01 dẫn đến mất liên lạc."
    res = compare_two_explanations(exp, exp)
    assert res.winner == "TIE"
    assert res.score_delta == 0.0


def test_compare_proposal_explanations_ranking() -> None:
    candidates = [
        {
            "candidate_id": "cand_split_001",
            "operation": "SPLIT",
            "hard_gate_result": {"status": "PASSED"},
            "pareto_state": "FRONTIER_SELECTED",
            "evaluation_status": "BETTER_SUPPORTED",
            "comparative_explanation": {
                "summary_action": "Tách chuỗi làm đôi theo mốc thời gian",
                "why_better": "Giảm độ dài của chuỗi",
                "comparison_points": ["Chuỗi 1 có 10 cảnh báo", "Chuỗi 2 có 10 cảnh báo"],
                "ai_narrative": "Tách chuỗi dựa trên tương quan thời gian chưa rõ nguyên nhân.",
            },
        },
        {
            "candidate_id": "cand_remove_002",
            "operation": "REMOVE",
            "hard_gate_result": {"status": "PASSED"},
            "pareto_state": "FRONTIER_SELECTED",
            "evaluation_status": "BETTER_SUPPORTED",
            "comparative_explanation": {
                "summary_action": "Loại bỏ cảnh báo POWER_ALARM tại trạm BLU0006",
                "why_better": "Bóc tách sự cố nguồn độc lập khỏi luồng truyền dẫn quang chính trên switch CMU0009AGG01",
                "comparison_points": [
                    "Bảo toàn nguyên nhân gốc đứt cáp quang trên trạm HGG0007",
                    "Giúp kỹ sư tập trung xử lý dứt khoát tuyến cáp quang chính",
                ],
                "ai_narrative": "Cảnh báo nguồn là ngoại lai độc lập; loại bỏ sẽ không làm phân mảnh chuỗi sự cố quang.",
            },
        },
    ]

    res = compare_proposal_explanations(candidates)
    assert len(res.proposals) == 2
    # Cand remove has high specificity and causality, so it should rank #1
    assert res.top_proposal_id == "cand_remove_002"
    assert res.top_proposal_operation == "REMOVE"
    assert res.proposals[0].is_top_pick is True
    assert res.proposals[0].clarity_rank == 1
    assert res.proposals[1].clarity_rank == 2

    # Head-to-head comparison
    assert len(res.head_to_head_comparisons) == 1
    h2h = res.head_to_head_comparisons[0]
    assert h2h["target_candidate_id"] == "cand_split_001"
    assert h2h["top_candidate_id"] == "cand_remove_002"
    assert h2h["score_advantage"] > 0
    assert len(h2h["why_top_is_clearer"]) > 0


def test_find_clearest_explain_threshold_and_apply() -> None:
    # Build mock service
    mock_alarm_1 = SimpleNamespace(alarm_id="ALM_1", device_code="CMU0009AGG01", alarm_name="LINK_DOWN", raw={})
    mock_alarm_2 = SimpleNamespace(alarm_id="ALM_2", device_code="CMU0009AGG01", alarm_name="LINK_DOWN", raw={})
    mock_alarm_3 = SimpleNamespace(alarm_id="ALM_3", device_code="BLU0006", alarm_name="POWER", raw={})

    mock_analysis = SimpleNamespace(
        member_count=3,
        members={
            "ALM_1": SimpleNamespace(role=SimpleNamespace(verdict="CORE", support=0.85)),
            "ALM_2": SimpleNamespace(role=SimpleNamespace(verdict="CORE", support=0.75)),
            "ALM_3": SimpleNamespace(role=SimpleNamespace(verdict="WEAK", support=0.18)),
        },
    )

    class MockConfig:
        def __init__(self) -> None:
            self.params = {
                "role.s_weak": SimpleNamespace(value=0.30),
                "role.c_min": SimpleNamespace(value=0.50),
                "role.s_min": SimpleNamespace(value=0.70),
            }

        def parameter(self, name: str) -> Any:
            return self.params.get(name, SimpleNamespace(value=0.5))

        def value(self, name: str) -> float:
            return float(self.parameter(name).value)

        def set_parameter(self, name: str, val: float, source: str = "") -> None:
            self.params[name] = SimpleNamespace(value=val)

    class MockPackage:
        def alarms_of(self, chain_id: str) -> list[Any]:
            return [mock_alarm_1, mock_alarm_2, mock_alarm_3]

    class MockService:
        def __init__(self) -> None:
            self.config = MockConfig()
            self.cache = SimpleNamespace(invalidate_chain=lambda cid: None)

        def require_package(self) -> Any:
            return MockPackage()

        def analyze(self, chain_id: str) -> Any:
            return mock_analysis

        def analyze_with_parameters(self, chain_id: str, parameters: dict[str, float]) -> Any:
            return mock_analysis

        def update_parameters(self, parameters: dict[str, float]) -> None:
            for key, value in parameters.items():
                self.config.set_parameter(key, value)

    service = MockService()
    opt_data = find_clearest_explain_threshold("chain_123", service)

    assert opt_data["chain_id"] == "chain_123"
    assert "optimal_parameters" in opt_data
    assert "current_explanation" in opt_data
    assert "optimal_explanation" in opt_data
    assert len(opt_data["why_clearer"]) > 0
    assert len(opt_data["sweep_results"]) > 0

    # Test applying thresholds
    apply_res = apply_explain_threshold("chain_123", service, opt_data["optimal_parameters"])
    assert apply_res["status"] == "APPLIED"
    assert "role.s_weak" in apply_res["applied_parameters"]
    assert service.config.parameter("role.s_weak").value == opt_data["optimal_parameters"]["role.s_weak"]


def test_api_threshold_optimize_and_apply_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_CONFIG_PATH", "config/thresholds/e2e-counterfactual.yaml")
    async def scenario(client: httpx2.AsyncClient) -> None:
        # Load preset snapshot
        load_resp = await client.post("/api/v1/snapshots/select", json={"snapshot_id": "synthetic_counterfactual_move_v1:snapshot_000"})
        assert load_resp.status_code == 200

        chain_id = "SYN-CHAIN-MOVE-SOURCE"

        # 1. Optimize threshold on chain
        opt_resp = await client.post(f"/api/v1/chains/{chain_id}/optimize-explain-threshold")
        assert opt_resp.status_code == 200
        opt_body = opt_resp.json()
        assert opt_body["chain_id"] == chain_id
        assert "optimal_parameters" in opt_body
        assert "optimal_explanation" in opt_body
        assert "why_clearer" in opt_body
        assert len(opt_body["why_clearer"]) > 0

        # 2. Apply the optimal parameters
        apply_resp = await client.post(
            f"/api/v1/chains/{chain_id}/apply-explain-threshold",
            json={"parameters": opt_body["optimal_parameters"]},
        )
        assert apply_resp.status_code == 200
        apply_body = apply_resp.json()
        assert apply_body["status"] == "APPLIED"

        # 3. Trigger review job to test proposal clarity comparison
        sub_resp = await client.post(f"/api/v1/chains/{chain_id}/review")
        assert sub_resp.status_code == 202
        job_id = sub_resp.json()["job_id"]

        # Wait for review job to complete
        import asyncio
        for _ in range(100):
            job_status_resp = await client.get(f"/api/v1/review-jobs/{job_id}")
            if job_status_resp.json().get("status") in {"SUCCEEDED", "FAILED"}:
                break
            await asyncio.sleep(0.02)

        # 4. Compare proposals clarity
        comp_resp = await client.get(f"/api/v1/review-jobs/{job_id}/compare-proposals-clarity")
        assert comp_resp.status_code == 200
        comp_body = comp_resp.json()
        assert comp_body["job_id"] == job_id
        assert len(comp_body["proposals"]) > 0
        assert comp_body["top_proposal_id"] is not None
        assert comp_body["overall_recommendation_rationale"] != ""

    run_api_test(scenario)


def test_render_explain_trial_with_llm_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from nocpro_api.grounded_llm import render_explain_trial_with_llm

    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "http://mock-ai:8000/v1")
    monkeypatch.setenv("AI_MODEL", "mock-gpt")
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OPENAI_COMPATIBLE")

    mock_llm_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "explanation": "Chuỗi C1 gồm 3 cảnh báo trên trạm CMU0009AGG01 và BLU0006. Cấu hình role.s_weak=0.30 và role.c_min=0.50.",
                        "llm_score": 92,
                    }),
                }
            }
        ]
    }

    class MockHTTPResponse:
        def __enter__(self) -> MockHTTPResponse:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, *args: Any) -> bytes:
            return json.dumps(mock_llm_response).encode("utf-8")

    def mock_urlopen(req: Any, timeout: float = 6.0) -> MockHTTPResponse:
        return MockHTTPResponse()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    draft = "Chuỗi C1 có 3 phần tử: 2 CORE, 1 WEAK. Role engine dùng role.s_weak=0.30 và role.c_min=0.50. Định danh quan sát: thiết bị CMU0009AGG01, BLU0006; cảnh báo LINK_DOWN, POWER. Đây là phân loại theo bằng chứng cấu hình, không phải kết luận nguyên nhân gốc hay khuyến nghị thao tác."
    facts = {"chain_id": "C1", "devices": ["CMU0009AGG01", "BLU0006"], "alarm_names": ["LINK_DOWN", "POWER"]}
    fact_refs = ["C1", "CMU0009AGG01", "BLU0006", "LINK_DOWN", "POWER"]

    result = render_explain_trial_with_llm(draft=draft, facts=facts, fact_refs=fact_refs)
    assert result.used_provider is True
    assert result.provider_status == "OK"
    assert result.model == "mock-gpt"
    assert result.llm_score == 92.0
    assert "CMU0009AGG01" in result.message


def test_find_clearest_explain_threshold_with_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from nocpro_api.threshold_explain_optimizer import find_clearest_explain_threshold

    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "http://mock-ai:8000/v1")
    monkeypatch.setenv("AI_MODEL", "mock-gpt")
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OPENAI_COMPATIBLE")

    mock_alarm_1 = SimpleNamespace(alarm_id="ALM_1", device_code="CMU0009AGG01", alarm_name="LINK_DOWN", raw={})
    mock_alarm_2 = SimpleNamespace(alarm_id="ALM_2", device_code="CMU0009AGG01", alarm_name="LINK_DOWN", raw={})
    mock_alarm_3 = SimpleNamespace(alarm_id="ALM_3", device_code="BLU0006", alarm_name="POWER", raw={})

    mock_analysis = SimpleNamespace(
        member_count=3,
        members={
            "ALM_1": SimpleNamespace(role=SimpleNamespace(verdict="CORE", support=0.85)),
            "ALM_2": SimpleNamespace(role=SimpleNamespace(verdict="CORE", support=0.75)),
            "ALM_3": SimpleNamespace(role=SimpleNamespace(verdict="WEAK", support=0.18)),
        },
    )

    class MockConfig:
        def __init__(self) -> None:
            self.params = {
                "role.s_weak": SimpleNamespace(value=0.30),
                "role.c_min": SimpleNamespace(value=0.50),
                "role.s_min": SimpleNamespace(value=0.70),
            }

        def parameter(self, name: str) -> Any:
            return self.params.get(name, SimpleNamespace(value=0.5))

        def value(self, name: str) -> float:
            return float(self.parameter(name).value)

        def set_parameter(self, name: str, val: float, source: str = "") -> None:
            self.params[name] = SimpleNamespace(value=val)

    class MockService:
        def __init__(self) -> None:
            self.config = MockConfig()
            self.cache = SimpleNamespace(invalidate_chain=lambda cid: None)

        def require_package(self) -> Any:
            return SimpleNamespace(alarms_of=lambda cid: [mock_alarm_1, mock_alarm_2, mock_alarm_3])

        def analyze(self, chain_id: str) -> Any:
            return mock_analysis

        def analyze_with_parameters(self, chain_id: str, parameters: dict[str, float]) -> Any:
            return mock_analysis

        def update_parameters(self, parameters: dict[str, float]) -> None:
            for k, v in parameters.items():
                self.config.set_parameter(k, v)

    mock_llm_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "explanation": "Chuỗi C1 gồm 3 cảnh báo trên trạm CMU0009AGG01 và BLU0006. Cấu hình role.s_weak=0.30 và role.c_min=0.50.",
                        "llm_score": 88,
                    }),
                }
            }
        ]
    }

    class MockHTTPResponse:
        def __enter__(self) -> MockHTTPResponse:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, *args: Any) -> bytes:
            return json.dumps(mock_llm_response).encode("utf-8")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=6.0: MockHTTPResponse())

    service = MockService()
    opt_data = find_clearest_explain_threshold("C1", service)

    assert opt_data["chain_id"] == "C1"
    assert opt_data["ai_model"] == "mock-gpt"
    assert opt_data["ai_provider_status"] == "OK"
    assert opt_data["optimal_llm_score"] is not None
    assert opt_data["optimal_hybrid_score"] is not None
    assert any(t.get("llm_score") == 88.0 for t in opt_data["sweep_results"])


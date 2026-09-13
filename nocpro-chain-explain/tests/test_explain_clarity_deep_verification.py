"""Deep regression, boundary condition, and edge case tests for Explain Clarity Comparison."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
import pytest
import httpx2

from nocpro_api import create_app
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


def test_clarity_boundary_extreme_lengths() -> None:
    # 1. Extremely short explanation
    short_text = "Lỗi mạng"
    score_short, dims_short = evaluate_explain_clarity(short_text)
    assert score_short < 40.0
    conc_dim_short = next(d for d in dims_short if d.name == "conciseness")
    assert conc_dim_short.score < 0.5
    assert any("quá ngắn" in s for s in conc_dim_short.shortcomings)

    # 2. Extremely long repetitive explanation
    long_text = "Cảnh báo LINK_DOWN trên trạm AGG01. " * 50
    score_long, dims_long = evaluate_explain_clarity(long_text)
    conc_dim_long = next(d for d in dims_long if d.name == "conciseness")
    assert any("hơi dài" in s for s in conc_dim_long.shortcomings)


def test_clarity_boundary_special_characters_and_unicode() -> None:
    text_with_symbols = (
        "Sự cố Cáp Quang [Tuyến: HN-HP-01/Gi0/1] gặp lỗi LINK_DOWN lúc 03:15:00 UTC+7. "
        "Nguyên nhân cốt lõi do đứt cáp truyền dẫn tại trạm CMU0009AGG01 (99.8% suy hao). "
        "Hệ quả làm mất tín hiệu 5 trạm BTS vệ tinh. Đề xuất cô lập cảnh báo ngoại lai và tập trung xử lý tuyến cáp!"
    )
    score, dims = evaluate_explain_clarity(text_with_symbols)
    assert score >= 75.0
    spec_dim = next(d for d in dims if d.name == "specificity")
    caus_dim = next(d for d in dims if d.name == "causality")
    act_dim = next(d for d in dims if d.name == "actionability")
    assert spec_dim.score > 0.7
    assert caus_dim.score > 0.7
    assert act_dim.score >= 0.7


def test_compare_proposal_explanations_empty_and_single() -> None:
    # Empty candidates
    res_empty = compare_proposal_explanations([])
    assert res_empty.proposals == []
    assert res_empty.top_proposal_id is None
    assert len(res_empty.head_to_head_comparisons) == 0

    # Single candidate
    single = [{
        "candidate_id": "cand_single_001",
        "operation": "REMOVE",
        "comparative_explanation": {
            "summary_action": "Bóc tách cảnh báo nhiễu tại trạm AGG01",
            "why_better": "Bảo toàn luồng truyền dẫn chính",
            "comparison_points": ["Nguyên nhân do sự cố nguồn độc lập"],
            "ai_narrative": "Loại bỏ cảnh báo nguồn.",
        },
    }]
    res_single = compare_proposal_explanations(single)
    assert len(res_single.proposals) == 1
    assert res_single.proposals[0].is_top_pick is True
    assert res_single.top_proposal_id == "cand_single_001"
    assert len(res_single.head_to_head_comparisons) == 0  # No other candidates to compare with


def test_compare_proposal_explanations_missing_or_none_fields() -> None:
    # Candidate with None or missing comparative_explanation
    corrupted_candidates = [
        {"candidate_id": "c1", "operation": "SPLIT"},
        {"candidate_id": "c2", "operation": "REMOVE", "comparative_explanation": None},
        {"candidate_id": "c3", "operation": "MOVE", "comparative_explanation": {
            "summary_action": None,
            "why_better": None,
            "comparison_points": None,
            "ai_narrative": None,
        }},
    ]
    res = compare_proposal_explanations(corrupted_candidates)
    assert len(res.proposals) == 3
    assert res.top_proposal_id is not None
    # None of them crash, ranks are populated
    assert set(p.clarity_rank for p in res.proposals) == {1, 2, 3}


def test_threshold_optimizer_singleton_chain() -> None:
    # Chain with only 1 alarm
    singleton_alarm = SimpleNamespace(alarm_id="ALM_SINGLE", device_code="BTS001", alarm_name="POWER", raw={})
    singleton_analysis = SimpleNamespace(
        member_count=1,
        members={
            "ALM_SINGLE": SimpleNamespace(role=SimpleNamespace(verdict="CORE", support=1.0)),
        },
    )

    class MockConfig:
        def value(self, name: str) -> float:
            return 0.3 if "s_weak" in name else 0.5

    class MockPackage:
        def alarms_of(self, chain_id: str) -> list[Any]:
            return [singleton_alarm]

    class MockService:
        config = MockConfig()
        cache = SimpleNamespace(invalidate_chain=lambda cid: None)
        def require_package(self) -> Any:
            return MockPackage()
        def analyze(self, chain_id: str) -> Any:
            return singleton_analysis

    service = MockService()
    res = find_clearest_explain_threshold("chain_singleton", service)
    assert res["chain_id"] == "chain_singleton"
    assert res["current_clarity_score"] > 0
    assert res["optimal_clarity_score"] > 0
    assert len(res["why_clearer"]) > 0


def test_apply_explain_threshold_error_handling() -> None:
    # Service with failing or invalid update_parameters
    class FailingService:
        def update_parameters(self, params: dict[str, Any]) -> None:
            raise ValueError("role.s_weak (0.8) must be <= role.s_min (0.5)")

    service = FailingService()
    # Should safely catch exception and return status
    res = apply_explain_threshold("chain_test", service, {"role.s_weak": 0.8})
    assert res["status"] == "APPLIED"
    assert res["chain_id"] == "chain_test"


def test_multi_preset_e2e_clarity_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYSIS_CONFIG_PATH", "config/thresholds/e2e-counterfactual.yaml")

    async def scenario(client: httpx2.AsyncClient) -> None:
        presets_to_test = [
            ("synthetic_counterfactual_split_v1:snapshot_000", "SYN-CHAIN-SPLIT-MUTATED"),
            ("synthetic_counterfactual_merge_v1:snapshot_000", "SYN-CHAIN-MERGE-LEFT"),
            ("synthetic_counterfactual_move_v1:snapshot_000", "SYN-CHAIN-MOVE-SOURCE"),
        ]

        import asyncio

        for preset_id, chain_id in presets_to_test:
            # 1. Ingest preset
            load_resp = await client.post("/api/v1/snapshots/select", json={"snapshot_id": preset_id})
            assert load_resp.status_code == 200, f"Failed loading {preset_id}"

            # 2. Optimize threshold for this chain
            opt_resp = await client.post(f"/api/v1/chains/{chain_id}/optimize-explain-threshold")
            assert opt_resp.status_code == 200, f"Optimization failed for {chain_id}"
            opt_data = opt_resp.json()
            assert opt_data["chain_id"] == chain_id
            assert opt_data["optimal_clarity_score"] >= opt_data["current_clarity_score"]
            assert len(opt_data["why_clearer"]) > 0

            # 3. Apply optimal threshold
            apply_resp = await client.post(
                f"/api/v1/chains/{chain_id}/apply-explain-threshold",
                json={"parameters": opt_data["optimal_parameters"]},
            )
            assert apply_resp.status_code == 200

            # 4. Review job and proposals comparison
            sub_resp = await client.post(f"/api/v1/chains/{chain_id}/review")
            assert sub_resp.status_code == 202
            job_id = sub_resp.json()["job_id"]

            for _ in range(100):
                st_resp = await client.get(f"/api/v1/review-jobs/{job_id}")
                if st_resp.json().get("status") in {"SUCCEEDED", "FAILED"}:
                    break
                await asyncio.sleep(0.02)

            comp_resp = await client.get(f"/api/v1/review-jobs/{job_id}/compare-proposals-clarity")
            assert comp_resp.status_code == 200
            comp_data = comp_resp.json()
            assert comp_data["job_id"] == job_id
            if comp_data["proposals"]:
                assert comp_data["top_proposal_id"] is not None
                assert comp_data["top_proposal_operation"] is not None
                assert "trên biên Pareto" in comp_data["overall_recommendation_rationale"]
            else:
                assert comp_data["top_proposal_id"] is None
                assert "Không có đề xuất nào" in comp_data["overall_recommendation_rationale"]

        # 5. Nonexistent chain 404 test
        unknown_resp = await client.post("/api/v1/chains/NONEXISTENT_CHAIN_ID/optimize-explain-threshold")
        assert unknown_resp.status_code == 404

    run_api_test(scenario)


@pytest.mark.realdata
def test_real_replay_chain_optimization_and_clarity() -> None:
    import json
    import subprocess
    import sys
    from tests.conftest import MOCK_ROOT
    from nocpro_api.workspace import Workspace

    if not MOCK_ROOT.is_dir():
        pytest.skip("sibling nocpro-mock repo not present")
    if not (MOCK_ROOT / "datasets/raw/alarm/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")

    venv_python = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv_python) if venv_python.is_file() else sys.executable
    real_chain_id = "6905665"
    res = subprocess.run(
        [interpreter, "-m", "nocpro_mock.cli", "replay", "--chain-id", real_chain_id, "--snapshot-id", "s_real_deep"],
        cwd=MOCK_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if res.returncode != 0:
        pytest.skip(f"mock replay failed: {res.stderr[:200]}")

    payload = json.loads(res.stdout)
    ws = Workspace()
    ws.replace_snapshot(payload)

    # 1. Sweep thresholds on real 42-member alarm chain
    opt = find_clearest_explain_threshold(real_chain_id, ws)
    assert opt["chain_id"] == real_chain_id
    assert 0.0 <= opt["current_clarity_score"] <= 100.0
    assert 0.0 <= opt["optimal_clarity_score"] <= 100.0
    assert opt["optimal_clarity_score"] >= opt["current_clarity_score"]
    assert len(opt["why_clearer"]) >= 1
    assert "GSHT05" in opt["optimal_explanation"] or "GSHL02" in opt["optimal_explanation"]

    # 2. Apply optimal threshold and verify workspace parameter update
    apply_res = apply_explain_threshold(real_chain_id, ws, opt["optimal_parameters"])
    assert apply_res["status"] == "APPLIED"
    assert ws.config.value("role.s_weak") == opt["optimal_parameters"]["role.s_weak"]


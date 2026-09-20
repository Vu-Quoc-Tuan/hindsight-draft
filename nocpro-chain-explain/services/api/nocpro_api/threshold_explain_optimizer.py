"""Evidence-faithful threshold exploration for configured Tier-1B roles."""

from __future__ import annotations

from typing import Any, Mapping

from concurrent.futures import ThreadPoolExecutor
from tier2.counterfactual.explain_clarity_comparator import compare_two_explanations, evaluate_explain_clarity
from .grounded_llm import is_provider_configured, render_explain_trial_with_llm


def _role_counts(analysis: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for member in getattr(analysis, "members", {}).values():
        verdict = getattr(getattr(member, "role", None), "verdict", "UNKNOWN")
        name = str(getattr(verdict, "value", verdict))
        counts[name] = counts.get(name, 0) + 1
    return counts


def _observed_facts(chain_id: str, package: Any) -> dict[str, list[str]]:
    devices: list[str] = []
    alarms: list[str] = []
    for alarm in package.alarms_of(chain_id):
        raw = getattr(alarm, "raw", {}) if isinstance(getattr(alarm, "raw", {}), dict) else {}
        for value, target in ((getattr(alarm, "device_code", None) or raw.get("device_code") or raw.get("device_name"), devices), (getattr(alarm, "alarm_name", None) or raw.get("alarm_name"), alarms)):
            if value and str(value) not in target:
                target.append(str(value))
    return {"devices": devices[:3], "alarm_names": alarms[:3]}


def _narrative(chain_id: str, parameters: Mapping[str, float], analysis: Any, facts: Mapping[str, list[str]]) -> str:
    counts = _role_counts(analysis)
    roles = ", ".join(f"{count} {name}" for name, count in sorted(counts.items())) or "không có verdict"
    device_text = ", ".join(facts.get("devices", [])) or "không có định danh thiết bị"
    alarm_text = ", ".join(facts.get("alarm_names", [])) or "không có loại cảnh báo"
    return (
        f"Chuỗi {chain_id} có {sum(counts.values())} phần tử: {roles}. "
        f"Role engine dùng role.s_weak={parameters['role.s_weak']:.2f} và role.c_min={parameters['role.c_min']:.2f}. "
        f"Định danh quan sát: thiết bị {device_text}; cảnh báo {alarm_text}. "
        "Đây là phân loại theo bằng chứng cấu hình, không phải kết luận nguyên nhân gốc hay khuyến nghị thao tác."
    )


def _valid_trials(service: Any) -> list[tuple[str, dict[str, float]]]:
    current = {"role.s_weak": float(service.config.value("role.s_weak")), "role.c_min": float(service.config.value("role.c_min"))}
    s_min = float(service.config.value("role.s_min"))
    candidates = [
        ("Cấu hình hiện tại", current),
        ("Giảm ngưỡng weak", {**current, "role.s_weak": max(0.05, current["role.s_weak"] - 0.05)}),
        ("Tăng ngưỡng weak", {**current, "role.s_weak": min(s_min, current["role.s_weak"] + 0.05)}),
        ("Giảm ngưỡng clustering", {**current, "role.c_min": max(0.1, current["role.c_min"] - 0.05)}),
        ("Tăng ngưỡng clustering", {**current, "role.c_min": min(1.0, current["role.c_min"] + 0.05)}),
    ]
    unique: dict[tuple[float, float], tuple[str, dict[str, float]]] = {}
    for label, params in candidates:
        unique.setdefault((params["role.s_weak"], params["role.c_min"]), (label, params))
    return list(unique.values())


def _evidence_quality(counts: Mapping[str, int]) -> tuple[int, int, int]:
    insufficient = counts.get("INSUFFICIENT_DATA", 0)
    total = sum(counts.values())
    return (-insufficient, total - insufficient, total)


def _eval_single_trial(
    label: str,
    params: dict[str, float],
    chain_id: str,
    service: Any,
    facts: Mapping[str, list[str]],
    context: Mapping[str, Any],
    fact_refs: Sequence[str],
) -> dict[str, Any]:
    analysis = service.analyze_with_parameters(chain_id, params)
    counts = _role_counts(analysis)
    draft = _narrative(chain_id, params, analysis, facts)

    llm_res = render_explain_trial_with_llm(
        draft=draft,
        facts={
            "chain_id": chain_id,
            "parameters": dict(params),
            "roles": counts,
            "devices": facts.get("devices", []),
            "alarm_names": facts.get("alarm_names", []),
        },
        fact_refs=fact_refs,
    )
    explanation = (
        llm_res.message
        if (llm_res.used_provider and llm_res.provider_status == "OK")
        else draft
    )
    score, _ = evaluate_explain_clarity(explanation, context)
    llm_score = llm_res.llm_score
    hybrid_score = round(0.6 * score + 0.4 * llm_score, 1) if llm_score is not None else score

    return {
        "parameters": params,
        "label": label,
        "explanation": explanation,
        "clarity_score": score,
        "llm_score": llm_score,
        "hybrid_score": hybrid_score,
        "role_counts": counts,
        "weak_count": counts.get("WEAK", 0),
        "core_count": counts.get("CORE", 0),
        "evidence_quality": {
            "insufficient_count": counts.get("INSUFFICIENT_DATA", 0),
            "computable_count": sum(counts.values()) - counts.get("INSUFFICIENT_DATA", 0),
        },
        "config_version": getattr(analysis, "config_version", None),
        "ai_model": llm_res.model,
        "ai_provider_status": llm_res.provider_status,
        "used_provider": llm_res.used_provider,
    }


def find_clearest_explain_threshold(chain_id: str, service: Any) -> dict[str, Any]:
    """Evaluate bounded configurations through the real configured role engine."""
    package = service.require_package()
    current = {"role.s_weak": float(service.config.value("role.s_weak")), "role.c_min": float(service.config.value("role.c_min"))}
    facts = _observed_facts(chain_id, package)
    context = {"observed_facts": [chain_id, *facts["devices"], *facts["alarm_names"]], "causal_status": "UNAVAILABLE"}
    fact_refs = [chain_id, *facts["devices"], *facts["alarm_names"]]

    candidates = _valid_trials(service)
    if is_provider_configured():
        with ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as executor:
            trials = list(executor.map(
                lambda item: _eval_single_trial(item[0], item[1], chain_id, service, facts, context, fact_refs),
                candidates,
            ))
    else:
        trials = [
            _eval_single_trial(label, params, chain_id, service, facts, context, fact_refs)
            for label, params in candidates
        ]

    baseline = next(t for t in trials if t["parameters"] == current)
    base_tuple = (
        _evidence_quality(baseline["role_counts"]),
        baseline.get("hybrid_score", baseline["clarity_score"]),
        baseline["clarity_score"],
    )

    # Only consider candidates that strictly improve evidence quality or scores
    improving_candidates = [
        t for t in trials
        if (
            _evidence_quality(t["role_counts"]),
            t.get("hybrid_score", t["clarity_score"]),
            t["clarity_score"],
        ) > base_tuple
    ]

    if improving_candidates:
        best = max(
            improving_candidates,
            key=lambda t: (
                _evidence_quality(t["role_counts"]),
                t.get("hybrid_score", t["clarity_score"]),
                t["clarity_score"],
            ),
        )
        base_score = baseline.get("hybrid_score", baseline["clarity_score"])
        best_score = best.get("hybrid_score", best["clarity_score"])

        comparison = compare_two_explanations(
            baseline["explanation"],
            best["explanation"],
            label_a="Cấu hình hiện tại",
            label_b="Cấu hình được chọn",
            context_a=context,
            context_b=context,
            custom_score_a=base_score,
            custom_score_b=best_score,
        )
        winner = comparison.winner
        why_clearer = comparison.why_clearer
        summary_verdict = comparison.summary_verdict
        is_already_optimal = False

        if winner == "TIE" or (best["explanation"].strip() == baseline["explanation"].strip() and abs(best_score - base_score) < 0.5):
            best = baseline
            winner = "Cấu hình hiện tại"
            why_clearer = [
                "Cấu hình hiện tại đã đạt độ rõ ràng và phân định vai trò tối ưu nhất.",
                "Các phương án thử nghiệm ngưỡng khác có độ rõ ràng tương đương nên không cần điều chỉnh.",
            ]
            summary_verdict = "Cấu hình hiện tại đã tối ưu; các phương án thử nghiệm tương đương nên khuyến nghị giữ nguyên cấu hình gốc."
            is_already_optimal = True
    else:
        best = baseline
        winner = "Cấu hình hiện tại"
        why_clearer = [
            "Cấu hình hiện tại đã đạt độ rõ ràng và phân định vai trò tối ưu nhất.",
            "Tất cả các phương án thử nghiệm ngưỡng khác đều không mang lại điểm số cao hơn hay phân loại sắc nét hơn.",
        ]
        summary_verdict = "Cấu hình hiện tại đã tối ưu; khuyến nghị giữ nguyên tham số ngưỡng, không cần điều chỉnh."
        is_already_optimal = True

    active_ai = next((t for t in trials if t.get("used_provider")), None)
    ai_model = active_ai["ai_model"] if active_ai else "DETERMINISTIC_EVIDENCE"
    ai_provider_status = active_ai["ai_provider_status"] if active_ai else (
        "OK" if is_provider_configured() else "NOT_CONFIGURED"
    )

    score_delta = round(
        max(
            best["clarity_score"] - baseline["clarity_score"],
            best.get("hybrid_score", best["clarity_score"]) - baseline.get("hybrid_score", baseline["clarity_score"]),
        ),
        1,
    )
    clarity_gain = 0.0 if is_already_optimal else max(score_delta, 0.0)

    return {
        "chain_id": chain_id,
        "current_parameters": current,
        "optimal_parameters": best["parameters"],
        "current_clarity_score": baseline["clarity_score"],
        "optimal_clarity_score": best["clarity_score"],
        "current_llm_score": baseline.get("llm_score"),
        "optimal_llm_score": best.get("llm_score"),
        "current_hybrid_score": baseline.get("hybrid_score", baseline["clarity_score"]),
        "optimal_hybrid_score": best.get("hybrid_score", best["clarity_score"]),
        "clarity_gain": clarity_gain,
        "current_explanation": baseline["explanation"],
        "optimal_explanation": best["explanation"],
        "winner": winner,
        "why_clearer": why_clearer,
        "summary_verdict": summary_verdict,
        "sweep_results": trials,
        "ai_model": ai_model,
        "ai_provider_status": ai_provider_status,
        "is_already_optimal": is_already_optimal,
    }


def apply_explain_threshold(chain_id: str, service: Any, parameters: Mapping[str, float]) -> dict[str, Any]:
    """Apply a validated workspace-wide configuration; failures intentionally propagate."""
    if not hasattr(service, "update_parameters"):
        raise RuntimeError("Workspace does not support threshold updates")
    service.update_parameters(dict(parameters))
    return {"chain_id": chain_id, "status": "APPLIED", "applied_parameters": dict(parameters), "message": "Đã áp dụng cấu hình ngưỡng cho toàn bộ workspace; cache phân tích đã được làm mới."}

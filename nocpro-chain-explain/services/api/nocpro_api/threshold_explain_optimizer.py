"""Evidence-faithful threshold exploration for configured Tier-1B roles."""

from __future__ import annotations

from typing import Any, Mapping

from tier2.counterfactual.explain_clarity_comparator import compare_two_explanations, evaluate_explain_clarity


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


def find_clearest_explain_threshold(chain_id: str, service: Any) -> dict[str, Any]:
    """Evaluate bounded configurations through the real configured role engine."""
    package = service.require_package()
    current = {"role.s_weak": float(service.config.value("role.s_weak")), "role.c_min": float(service.config.value("role.c_min"))}
    facts = _observed_facts(chain_id, package)
    context = {"observed_facts": [chain_id, *facts["devices"], *facts["alarm_names"]], "causal_status": "UNAVAILABLE"}
    trials: list[dict[str, Any]] = []
    for label, params in _valid_trials(service):
        analysis = service.analyze_with_parameters(chain_id, params)
        counts = _role_counts(analysis)
        explanation = _narrative(chain_id, params, analysis, facts)
        score, _ = evaluate_explain_clarity(explanation, context)
        trials.append({"parameters": params, "label": label, "explanation": explanation, "clarity_score": score, "role_counts": counts, "weak_count": counts.get("WEAK", 0), "core_count": counts.get("CORE", 0), "evidence_quality": {"insufficient_count": counts.get("INSUFFICIENT_DATA", 0), "computable_count": sum(counts.values()) - counts.get("INSUFFICIENT_DATA", 0)}, "config_version": getattr(analysis, "config_version", None)})
    baseline = next(t for t in trials if t["parameters"] == current)
    best = max(trials, key=lambda t: (_evidence_quality(t["role_counts"]), t["clarity_score"], t["label"]))
    comparison = compare_two_explanations(baseline["explanation"], best["explanation"], label_a="Cấu hình hiện tại", label_b="Cấu hình được chọn", context_a=context, context_b=context)
    return {"chain_id": chain_id, "current_parameters": current, "optimal_parameters": best["parameters"], "current_clarity_score": baseline["clarity_score"], "optimal_clarity_score": best["clarity_score"], "clarity_gain": round(best["clarity_score"] - baseline["clarity_score"], 1), "current_explanation": baseline["explanation"], "optimal_explanation": best["explanation"], "winner": comparison.winner, "why_clearer": comparison.why_clearer, "summary_verdict": comparison.summary_verdict, "sweep_results": trials, "ai_model": "NOT_USED", "ai_provider_status": "NOT_USED"}


def apply_explain_threshold(chain_id: str, service: Any, parameters: Mapping[str, float]) -> dict[str, Any]:
    """Apply a validated workspace-wide configuration; failures intentionally propagate."""
    if not hasattr(service, "update_parameters"):
        raise RuntimeError("Workspace does not support threshold updates")
    service.update_parameters(dict(parameters))
    return {"chain_id": chain_id, "status": "APPLIED", "applied_parameters": dict(parameters), "message": "Đã áp dụng cấu hình ngưỡng cho toàn bộ workspace; cache phân tích đã được làm mới."}

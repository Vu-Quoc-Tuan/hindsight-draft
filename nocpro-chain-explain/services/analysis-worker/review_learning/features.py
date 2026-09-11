"""Stable ranker feature schema and vectorizer.

Schema version: cf-features-v1
Frozen per 2026-09-11 implementation plan.
Excludes all raw alarm IDs, chain IDs, snapshot IDs, reviewer IDs, and direct device codes.
Every optional feature has a corresponding <name>__available indicator.
"""

from __future__ import annotations

from typing import Any

FEATURE_SCHEMA_VERSION = "cf-features-v1"

FEATURE_NAMES: tuple[str, ...] = (
    # Operation one-hot
    "op__remove",
    "op__split",
    "op__move",
    "op__merge",
    # Metric deltas
    "delta__weak_member_count",
    "delta__weak_member_count__available",
    "delta__minimum_membership_support",
    "delta__minimum_membership_support__available",
    "delta__evidence_union_coverage",
    "delta__evidence_union_coverage__available",
    "delta__component_count",
    "delta__component_count__available",
    "delta__audit_conductance",
    "delta__audit_conductance__available",
    "delta__audit_verdict_severity",
    "delta__audit_verdict_severity__available",
    # Baseline before metrics
    "before__weak_member_count",
    "before__weak_member_count__available",
    "before__minimum_membership_support",
    "before__minimum_membership_support__available",
    "before__component_count",
    "before__component_count__available",
    # Edit cost
    "edit_cost__members_moved",
    "edit_cost__chains_created",
    "edit_cost__chains_removed",
    # Hard gate & Pareto state
    "hard_gate__passed",
    "pareto__selected",
    "pareto__truncated",
    "pareto__dominated",
    # Temporal KDE features
    "temporal__delay_score_mean",
    "temporal__delay_score_mean__available",
    "temporal__atypical_fraction",
    "temporal__atypical_fraction__available",
    "temporal__fallback_fraction",
    "temporal__fallback_fraction__available",
    # Similar-case memory features
    "similar_cases__approved_ratio",
    "similar_cases__approved_ratio__available",
    "similar_cases__max_similarity",
    "similar_cases__max_similarity__available",
    # Source kind
    "source_kind__real_live",
    "source_kind__real_export_replay",
    "source_kind__synthetic_test",
    # Topology capability
    "topology__dep_hop_available",
)


def _extract_metric_val(metric_obj: Any) -> tuple[float, float]:
    """Extract (value, available_flag) from a metric dict or object."""
    if metric_obj is None:
        return 0.0, 0.0
    if isinstance(metric_obj, dict):
        avail = metric_obj.get("availability", "")
        is_avail = 1.0 if avail in {"AVAILABLE", "SUPPORT"} else 0.0
        val = metric_obj.get("value")
        if val is not None and is_avail == 1.0:
            try:
                return float(val), 1.0
            except (ValueError, TypeError):
                return 0.0, 0.0
        return 0.0, is_avail
    # Object with attributes
    avail = getattr(metric_obj, "availability", None)
    is_avail = 1.0 if getattr(avail, "value", str(avail)) in {"AVAILABLE", "SUPPORT"} else 0.0
    val = getattr(metric_obj, "value", None)
    if val is not None and is_avail == 1.0:
        try:
            return float(val), 1.0
        except (ValueError, TypeError):
            return 0.0, 0.0
    return 0.0, is_avail


def materialize_candidate_features(
    *,
    operation: str,
    deterministic_context: dict[str, Any] | None = None,
    temporal_context: dict[str, Any] | None = None,
    case_context: dict[str, Any] | None = None,
    hard_gate_status: str = "PASSED",
    pareto_state: str = "FRONTIER_SELECTED",
    source_kind: str = "SYNTHETIC_TEST",
) -> dict[str, float]:
    """Extract flat numeric feature dictionary adhering to cf-features-v1."""
    d_ctx = deterministic_context or {}
    t_ctx = temporal_context or {}
    c_ctx = case_context or {}

    features: dict[str, float] = {}

    # 1. Operation one-hot
    op_clean = str(operation).upper()
    features["op__remove"] = 1.0 if op_clean.startswith("REMOVE") else 0.0
    features["op__split"] = 1.0 if op_clean.startswith("SPLIT") else 0.0
    features["op__move"] = 1.0 if op_clean.startswith("MOVE") else 0.0
    features["op__merge"] = 1.0 if op_clean.startswith("MERGE") else 0.0

    # 2. Metric deltas
    deltas = d_ctx.get("metric_deltas") or d_ctx.get("deltas") or {}
    for metric_name in (
        "weak_member_count",
        "minimum_membership_support",
        "evidence_union_coverage",
        "component_count",
        "audit_conductance",
        "audit_verdict_severity",
    ):
        v = deltas.get(metric_name)
        if v is not None:
            features[f"delta__{metric_name}"] = float(v)
            features[f"delta__{metric_name}__available"] = 1.0
        else:
            features[f"delta__{metric_name}"] = 0.0
            features[f"delta__{metric_name}__available"] = 0.0

    # 3. Before metrics
    before_metrics = d_ctx.get("before_metrics", {})
    for metric_name in (
        "weak_member_count",
        "minimum_membership_support",
        "component_count",
    ):
        val, avail = _extract_metric_val(before_metrics.get(metric_name))
        features[f"before__{metric_name}"] = val
        features[f"before__{metric_name}__available"] = avail

    # 4. Edit cost
    edit_cost = d_ctx.get("edit_cost") or {}
    if not edit_cost and ("partition_delta" in d_ctx or "delta" in d_ctx):
        p_delta = d_ctx.get("partition_delta") or d_ctx.get("delta")
        if isinstance(p_delta, dict):
            before_chains = p_delta.get("before", [])
            after_chains = p_delta.get("after", [])
            b_cnt = len(before_chains)
            a_cnt = len(after_chains)
            created = max(0, a_cnt - b_cnt)
            removed = max(0, b_cnt - a_cnt)
            b_map: dict[str, Any] = {}
            for ch in before_chains:
                if isinstance(ch, (list, tuple)) and len(ch) >= 2:
                    cid, members = ch[0], ch[1]
                    for m in members:
                        b_map[m] = cid
            moved = 0
            for ch in after_chains:
                if isinstance(ch, (list, tuple)) and len(ch) >= 2:
                    cid, members = ch[0], ch[1]
                    for m in members:
                        if m in b_map and b_map[m] != cid:
                            moved += 1
            edit_cost = {
                "members_moved": moved,
                "chains_created": created,
                "chains_removed": removed,
            }

    features["edit_cost__members_moved"] = float(edit_cost.get("members_moved", 0))
    features["edit_cost__chains_created"] = float(edit_cost.get("chains_created", 0))
    features["edit_cost__chains_removed"] = float(edit_cost.get("chains_removed", 0))

    # 5. Hard gate & Pareto
    features["hard_gate__passed"] = 1.0 if hard_gate_status.upper() == "PASSED" else 0.0
    p_state = str(pareto_state).upper()
    features["pareto__selected"] = 1.0 if "SELECTED" in p_state else 0.0
    features["pareto__truncated"] = 1.0 if "TRUNCATED" in p_state else 0.0
    features["pareto__dominated"] = 1.0 if "DOMINATED" in p_state else 0.0

    # 6. Temporal KDE
    t_status = str(t_ctx.get("status", "UNAVAILABLE")).upper()
    if t_status == "AVAILABLE":
        after_t = t_ctx.get("after") if isinstance(t_ctx.get("after"), dict) else {}
        delta_t = t_ctx.get("delta") if isinstance(t_ctx.get("delta"), dict) else {}

        delay_score = (
            delta_t.get("delta_mean_positive_score")
            if delta_t.get("delta_mean_positive_score") is not None
            else (after_t.get("mean_positive_score") if after_t.get("mean_positive_score") is not None else t_ctx.get("delay_score_mean", 0.0))
        )
        atypical = (
            after_t.get("atypical_fraction")
            if after_t.get("atypical_fraction") is not None
            else t_ctx.get("atypical_fraction", 0.0)
        )
        fallback = (
            after_t.get("fallback_fraction")
            if after_t.get("fallback_fraction") is not None
            else t_ctx.get("fallback_fraction", 0.0)
        )

        features["temporal__delay_score_mean"] = float(delay_score)
        features["temporal__delay_score_mean__available"] = 1.0
        features["temporal__atypical_fraction"] = float(atypical)
        features["temporal__atypical_fraction__available"] = 1.0
        features["temporal__fallback_fraction"] = float(fallback)
        features["temporal__fallback_fraction__available"] = 1.0
    else:
        features["temporal__delay_score_mean"] = 0.0
        features["temporal__delay_score_mean__available"] = 0.0
        features["temporal__atypical_fraction"] = 0.0
        features["temporal__atypical_fraction__available"] = 0.0
        features["temporal__fallback_fraction"] = 0.0
        features["temporal__fallback_fraction__available"] = 0.0

    # 7. Similar Cases
    c_status = str(c_ctx.get("status", "UNAVAILABLE")).upper()
    if c_status in {"AVAILABLE", "READY"}:
        approved_ratio = c_ctx.get("approved_ratio")
        if approved_ratio is None and "approved_count" in c_ctx and "total_cases" in c_ctx:
            tot = c_ctx.get("total_cases", 0)
            approved_ratio = (c_ctx.get("approved_count", 0) / tot) if tot > 0 else 0.0
        max_sim = c_ctx.get("max_similarity") or c_ctx.get("top_similarity") or 0.0

        features["similar_cases__approved_ratio"] = float(approved_ratio or 0.0)
        features["similar_cases__approved_ratio__available"] = 1.0
        features["similar_cases__max_similarity"] = float(max_sim)
        features["similar_cases__max_similarity__available"] = 1.0
    else:
        features["similar_cases__approved_ratio"] = 0.0
        features["similar_cases__approved_ratio__available"] = 0.0
        features["similar_cases__max_similarity"] = 0.0
        features["similar_cases__max_similarity__available"] = 0.0

    # 8. Source kind
    sk_clean = str(source_kind).upper()
    features["source_kind__real_live"] = 1.0 if sk_clean == "REAL_LIVE" else 0.0
    features["source_kind__real_export_replay"] = 1.0 if sk_clean == "REAL_EXPORT_REPLAY" else 0.0
    features["source_kind__synthetic_test"] = 1.0 if sk_clean == "SYNTHETIC_TEST" else 0.0

    # 9. Topology
    topo_avail = d_ctx.get("topology_dep_hop_available", False)
    features["topology__dep_hop_available"] = 1.0 if bool(topo_avail) else 0.0

    return features


def features_to_vector(features: dict[str, float]) -> list[float]:
    """Convert features dict to an ordered list matching FEATURE_NAMES exactly."""
    return [float(features.get(name, 0.0)) for name in FEATURE_NAMES]

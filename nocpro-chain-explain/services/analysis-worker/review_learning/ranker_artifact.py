"""Frozen ranker artifact and metadata manifest.

Frozen per Task 9 of the 2026-09-11 implementation plan.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RankerMetrics:
    ndcg_1: float
    ndcg_3: float
    ndcg_5: float
    top1_approved_recall: float
    top3_approved_recall: float
    baseline_ndcg_3: float
    ndcg_improvement: float
    mean_regret: float = 0.0
    linear_baseline_ndcg_3: float = 0.0
    ndcg_improvement_over_linear: float = 0.0
    confidence_intervals: dict[str, Any] = field(default_factory=dict)
    no_positive_coverage: float = 0.0
    abstention_rate: float = 0.0
    coverage: float = 1.0
    model_conditional_ndcg_3: float = 0.0
    model_conditional_regret: float = 0.0
    fallback_ndcg_3: float = 0.0
    fallback_regret: float = 0.0
    policy_ndcg_3: float = 0.0
    policy_regret: float = 0.0


@dataclass(frozen=True)
class RankerArtifactManifest:
    model_version: str
    model_family: str
    feature_schema_version: str
    label_policy_version: str
    training_cutoff: str
    corpus_fingerprint: str
    hyperparameters: dict[str, Any]
    metrics: RankerMetrics
    slice_metrics: dict[str, Any]
    artifact_sha256: str
    lineage_fingerprint: str = ""
    bundle_checksums: dict[str, str] = field(default_factory=dict)
    dependency_versions: dict[str, str] = field(default_factory=dict)
    qid_counts: dict[str, int] = field(default_factory=dict)
    operation_coverage: dict[str, int] = field(default_factory=dict)
    source_kind_mix: dict[str, int] = field(default_factory=dict)
    creation_command: str = ""
    best_iteration: int | None = None
    selection_trace: list[dict[str, Any]] = field(default_factory=list)
    approval_status: str = "DRAFT"
    approved_by: str | None = None
    approved_at: str | None = None
    approval_signature: str | None = None
    approval_notes: str | None = None
    truth_tier_distribution: dict[str, int] = field(default_factory=dict)
    abstention_threshold: float = 0.0
    protected_mode_used: bool = False
    strict_temporal_holdout_used: bool = False
    lineage_overlap_detected: bool = False
    temporal_inversion_detected: bool = False
    excluded_straddling_lineages: list[str] = field(default_factory=list)
    data_profile_fingerprint: str | None = None
    created_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str | dict[str, Any]) -> RankerArtifactManifest:
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        required_fields = {
            "model_version",
            "model_family",
            "feature_schema_version",
            "label_policy_version",
            "training_cutoff",
            "corpus_fingerprint",
            "hyperparameters",
            "metrics",
            "artifact_sha256",
        }
        missing = required_fields - set(data.keys())
        if missing:
            raise ValueError(f"Manifest is missing required fields: {sorted(missing)}")

        metrics_raw = data.get("metrics", {})
        if isinstance(metrics_raw, dict):
            metric_kwargs = {
                k: v for k, v in metrics_raw.items() if k in RankerMetrics.__dataclass_fields__
            }
            metrics = RankerMetrics(**metric_kwargs)
            data["metrics"] = metrics
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)

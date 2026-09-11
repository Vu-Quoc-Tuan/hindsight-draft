"""Offline grouped ranking model training, scoring, and NDCG evaluation.

Implements pure-Python NDCG metrics and XGBoost XGBRanker integration.
Frozen per Task 9 of the 2026-09-11 implementation plan.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
from typing import Any, Sequence

from .contracts import TruthTier
from .features import FEATURE_SCHEMA_VERSION
from .labels import LABEL_POLICY_VERSION
from .materializer import GroupedRankingDataset
from .ranker_artifact import RankerArtifactManifest, RankerMetrics


def dcg_at_k(relevances: Sequence[int | float], k: int) -> float:
    """Compute Discounted Cumulative Gain at rank k."""
    dcg = 0.0
    for i, rel in enumerate(relevances[:k], 1):
        if rel > 0:
            dcg += (math.pow(2.0, float(rel)) - 1.0) / math.log2(float(i + 1))
    return dcg


def ndcg_at_k(y_true: Sequence[int], y_score: Sequence[float], k: int) -> float:
    """Compute Normalized Discounted Cumulative Gain at rank k for one group."""
    if not y_true:
        return 0.0

    # Sort true labels by predicted score descending
    paired = sorted(zip(y_score, y_true), key=lambda x: x[0], reverse=True)
    sorted_true_by_pred = [rel for _, rel in paired]

    actual_dcg = dcg_at_k(sorted_true_by_pred, k)

    # Ideal ranking
    ideal_sorted = sorted(y_true, reverse=True)
    ideal_dcg = dcg_at_k(ideal_sorted, k)

    if ideal_dcg == 0.0:
        return 1.0 if actual_dcg == 0.0 else 0.0

    return actual_dcg / ideal_dcg


def compute_metric_confidence_intervals(
    dataset: GroupedRankingDataset,
    scores: Sequence[float],
    abstention_threshold: float = 0.0,
    n_resamples: int = 1000,
    seed: int = 42,
) -> dict[str, tuple[float, float]]:
    """Compute 95% bootstrap confidence intervals for effective policy NDCG@3 and mean regret."""
    if dataset.num_groups < 2:
        return {
            "ndcg_3_ci95": (0.0, 0.0),
            "mean_regret_ci95": (0.0, 0.0),
        }
    import random
    rng = random.Random(seed)

    groups_data = []
    idx = 0
    for size in dataset.group_sizes:
        group_y = dataset.y[idx : idx + size]
        group_scores = scores[idx : idx + size]
        idx += size

        is_abstained = False
        if abstention_threshold > 0.0:
            if len(group_scores) >= 2:
                sorted_s = sorted(group_scores, reverse=True)
                if (sorted_s[0] - sorted_s[1]) < abstention_threshold:
                    is_abstained = True
            elif len(group_scores) == 1:
                if group_scores[0] < abstention_threshold:
                    is_abstained = True

        if is_abstained:
            effective_scores = [float(size - i) for i in range(size)]
        else:
            effective_scores = list(group_scores)

        groups_data.append((group_y, effective_scores))

    ndcg_boot: list[float] = []
    regret_boot: list[float] = []

    for _ in range(n_resamples):
        sample = rng.choices(groups_data, k=len(groups_data))
        sample_ndcg = [ndcg_at_k(y, s, 3) for y, s in sample]
        sample_regret = []
        for y, s in sample:
            ranked = sorted(zip(s, y), key=lambda x: x[0], reverse=True)
            top1_y = ranked[0][1] if ranked else 0
            max_y = max(y) if y else 0
            sample_regret.append(float(max_y - top1_y))

        ndcg_boot.append(sum(sample_ndcg) / len(sample_ndcg))
        regret_boot.append(sum(sample_regret) / len(sample_regret))

    ndcg_boot.sort()
    regret_boot.sort()

    low_idx = int(0.025 * n_resamples)
    high_idx = min(len(ndcg_boot) - 1, int(0.975 * n_resamples))

    return {
        "ndcg_3_ci95": (round(ndcg_boot[low_idx], 4), round(ndcg_boot[high_idx], 4)),
        "mean_regret_ci95": (round(regret_boot[low_idx], 4), round(regret_boot[high_idx], 4)),
    }


def evaluate_predictions(
    dataset: GroupedRankingDataset,
    scores: Sequence[float],
    abstention_threshold: float = 0.0,
) -> RankerMetrics:
    """Evaluate predicted ranking scores across all groups in a dataset under serving policy."""
    if dataset.num_groups == 0:
        return RankerMetrics(
            ndcg_1=0.0,
            ndcg_3=0.0,
            ndcg_5=0.0,
            top1_approved_recall=0.0,
            top3_approved_recall=0.0,
            baseline_ndcg_3=0.0,
            ndcg_improvement=0.0,
            mean_regret=0.0,
            confidence_intervals={},
            no_positive_coverage=0.0,
            abstention_rate=0.0,
            coverage=1.0,
            model_conditional_ndcg_3=0.0,
            model_conditional_regret=0.0,
            fallback_ndcg_3=0.0,
            fallback_regret=0.0,
            policy_ndcg_3=0.0,
            policy_regret=0.0,
        )

    policy_ndcg_1_list: list[float] = []
    policy_ndcg_3_list: list[float] = []
    policy_ndcg_5_list: list[float] = []
    policy_regret_list: list[float] = []

    model_conditional_ndcg_3_list: list[float] = []
    model_conditional_regret_list: list[float] = []

    fallback_ndcg_3_list: list[float] = []
    fallback_regret_list: list[float] = []

    policy_top1_hits = 0
    policy_top3_hits = 0
    total_groups_with_positive = 0
    abstained_count = 0

    idx = 0
    for size in dataset.group_sizes:
        group_y = dataset.y[idx : idx + size]
        group_scores = scores[idx : idx + size]
        fallback_scores = [float(size - i) for i in range(size)]
        idx += size

        is_abstained = False
        if abstention_threshold > 0.0:
            if len(group_scores) >= 2:
                sorted_s = sorted(group_scores, reverse=True)
                if (sorted_s[0] - sorted_s[1]) < abstention_threshold:
                    is_abstained = True
            elif len(group_scores) == 1:
                if group_scores[0] < abstention_threshold:
                    is_abstained = True

        max_y = max(group_y) if group_y else 0

        if is_abstained:
            abstained_count += 1
            effective_scores = fallback_scores
            fb_ndcg3 = ndcg_at_k(group_y, fallback_scores, 3)
            fallback_ndcg_3_list.append(fb_ndcg3)
            fb_ranked = sorted(zip(fallback_scores, group_y), key=lambda x: x[0], reverse=True)
            top1_fb_y = fb_ranked[0][1] if fb_ranked else 0
            fallback_regret_list.append(float(max_y - top1_fb_y))
        else:
            effective_scores = group_scores
            mc_ndcg3 = ndcg_at_k(group_y, group_scores, 3)
            model_conditional_ndcg_3_list.append(mc_ndcg3)
            mc_ranked = sorted(zip(group_scores, group_y), key=lambda x: x[0], reverse=True)
            top1_mc_y = mc_ranked[0][1] if mc_ranked else 0
            model_conditional_regret_list.append(float(max_y - top1_mc_y))

        policy_ndcg_1_list.append(ndcg_at_k(group_y, effective_scores, 1))
        policy_ndcg_3_list.append(ndcg_at_k(group_y, effective_scores, 3))
        policy_ndcg_5_list.append(ndcg_at_k(group_y, effective_scores, 5))

        ranked_effective = sorted(zip(effective_scores, group_y), key=lambda x: x[0], reverse=True)
        top1_eff_y = ranked_effective[0][1] if ranked_effective else 0
        policy_regret_list.append(float(max_y - top1_eff_y))

        has_positive = any(rel >= 1 for rel in group_y)
        if has_positive:
            total_groups_with_positive += 1
            if top1_eff_y >= 1:
                policy_top1_hits += 1
            if any(rel >= 1 for _, rel in ranked_effective[:3]):
                policy_top3_hits += 1

    mean_ndcg_1 = sum(policy_ndcg_1_list) / len(policy_ndcg_1_list) if policy_ndcg_1_list else 0.0
    mean_ndcg_3 = sum(policy_ndcg_3_list) / len(policy_ndcg_3_list) if policy_ndcg_3_list else 0.0
    mean_ndcg_5 = sum(policy_ndcg_5_list) / len(policy_ndcg_5_list) if policy_ndcg_5_list else 0.0
    mean_regret = sum(policy_regret_list) / len(policy_regret_list) if policy_regret_list else 0.0

    mc_ndcg_3 = sum(model_conditional_ndcg_3_list) / len(model_conditional_ndcg_3_list) if model_conditional_ndcg_3_list else 0.0
    mc_regret = sum(model_conditional_regret_list) / len(model_conditional_regret_list) if model_conditional_regret_list else 0.0

    fb_ndcg_3 = sum(fallback_ndcg_3_list) / len(fallback_ndcg_3_list) if fallback_ndcg_3_list else 0.0
    fb_regret = sum(fallback_regret_list) / len(fallback_regret_list) if fallback_regret_list else 0.0

    top1_recall = policy_top1_hits / total_groups_with_positive if total_groups_with_positive > 0 else 0.0
    top3_recall = policy_top3_hits / total_groups_with_positive if total_groups_with_positive > 0 else 0.0

    no_pos_count = dataset.num_groups - total_groups_with_positive
    no_pos_coverage = no_pos_count / dataset.num_groups if dataset.num_groups > 0 else 0.0

    abstention_rate = abstained_count / dataset.num_groups if dataset.num_groups > 0 else 0.0
    coverage = 1.0 - abstention_rate

    ci = compute_metric_confidence_intervals(dataset, scores, abstention_threshold=abstention_threshold)

    return RankerMetrics(
        ndcg_1=mean_ndcg_1,
        ndcg_3=mean_ndcg_3,
        ndcg_5=mean_ndcg_5,
        top1_approved_recall=top1_recall,
        top3_approved_recall=top3_recall,
        baseline_ndcg_3=0.0,
        ndcg_improvement=0.0,
        mean_regret=mean_regret,
        confidence_intervals=ci,
        no_positive_coverage=no_pos_coverage,
        abstention_rate=abstention_rate,
        coverage=coverage,
        model_conditional_ndcg_3=mc_ndcg_3,
        model_conditional_regret=mc_regret,
        fallback_ndcg_3=fb_ndcg_3,
        fallback_regret=fb_regret,
        policy_ndcg_3=mean_ndcg_3,
        policy_regret=mean_regret,
    )


def evaluate_deterministic_baseline(dataset: GroupedRankingDataset) -> RankerMetrics:
    """Evaluate deterministic/Pareto baseline order.

    Candidates in dataset preserve their original ranking order (0, 1, 2...).
    Scores are assigned as -i so smaller original_rank comes first.
    """
    scores: list[float] = []
    idx = 0
    for size in dataset.group_sizes:
        for i in range(size):
            scores.append(-float(i))
        idx += size

    metrics = evaluate_predictions(dataset, scores)
    return RankerMetrics(
        ndcg_1=metrics.ndcg_1,
        ndcg_3=metrics.ndcg_3,
        ndcg_5=metrics.ndcg_5,
        top1_approved_recall=metrics.top1_approved_recall,
        top3_approved_recall=metrics.top3_approved_recall,
        baseline_ndcg_3=metrics.ndcg_3,
        ndcg_improvement=0.0,
        mean_regret=metrics.mean_regret,
        confidence_intervals=metrics.confidence_intervals,
        no_positive_coverage=metrics.no_positive_coverage,
        abstention_rate=metrics.abstention_rate,
    )


def evaluate_linear_baseline(
    train_ds: GroupedRankingDataset,
    eval_ds: GroupedRankingDataset,
) -> RankerMetrics:
    """Train Ridge regression on train_ds and evaluate ranking on eval_ds."""
    try:
        from sklearn.linear_model import Ridge
    except ImportError:
        return evaluate_deterministic_baseline(eval_ds)

    if train_ds.num_groups == 0 or eval_ds.num_groups == 0:
        return RankerMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    # Expand group weights to candidate rows
    row_weights: list[float] = []
    for g_idx, size in enumerate(train_ds.group_sizes):
        w = train_ds.group_weights[g_idx]
        row_weights.extend([w] * size)

    model = Ridge(alpha=1.0, random_state=42)
    model.fit(train_ds.X, train_ds.y, sample_weight=row_weights)

    preds = model.predict(eval_ds.X)
    return evaluate_predictions(eval_ds, preds)


def train_xgbranker(
    train_ds: GroupedRankingDataset,
    val_ds: GroupedRankingDataset | None = None,
    params: dict[str, Any] | None = None,
    n_jobs: int = 4,
    early_stopping_rounds: int = 10,
    abstention_threshold: float = 0.0,
) -> tuple[Any, RankerMetrics]:
    """Train XGBRanker with rank:ndcg and evaluate against deterministic and linear baselines.

    Requires xgboost. Fixed CPU threads (n_jobs) and fixed seed enforce determinism.
    """
    try:
        import xgboost as xgb
    except ImportError as e:
        raise ModuleNotFoundError(
            "xgboost is required for ranker training. Install via 'uv sync --group ml'"
        ) from e

    hyperparams: dict[str, Any] = {
        "objective": "rank:ndcg",
        "eval_metric": "ndcg@3",
        "tree_method": "hist",
        "n_estimators": 50,
        "max_depth": 4,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "random_state": 42,
        "n_jobs": n_jobs,
    }
    if val_ds and val_ds.num_groups > 0 and early_stopping_rounds > 0:
        hyperparams["early_stopping_rounds"] = early_stopping_rounds
    if params:
        hyperparams.update(params)

    model = xgb.XGBRanker(**hyperparams)

    fit_kwargs: dict[str, Any] = {
        "X": train_ds.X,
        "y": train_ds.y,
        "group": train_ds.group_sizes,
        "sample_weight": train_ds.group_weights,
        "verbose": False,
    }

    if val_ds and val_ds.num_groups > 0:
        fit_kwargs["eval_set"] = [(val_ds.X, val_ds.y)]
        fit_kwargs["eval_group"] = [val_ds.group_sizes]
        fit_kwargs["sample_weight_eval_set"] = [val_ds.group_weights]

    model.fit(**fit_kwargs)

    eval_ds = val_ds if (val_ds and val_ds.num_groups > 0) else train_ds
    preds = model.predict(eval_ds.X)
    metrics = evaluate_predictions(eval_ds, preds, abstention_threshold=abstention_threshold)

    det_baseline = evaluate_deterministic_baseline(eval_ds)
    linear_baseline = evaluate_linear_baseline(train_ds, eval_ds)

    improvement = metrics.ndcg_3 - det_baseline.ndcg_3
    improvement_over_linear = metrics.ndcg_3 - linear_baseline.ndcg_3

    full_metrics = RankerMetrics(
        ndcg_1=metrics.ndcg_1,
        ndcg_3=metrics.ndcg_3,
        ndcg_5=metrics.ndcg_5,
        top1_approved_recall=metrics.top1_approved_recall,
        top3_approved_recall=metrics.top3_approved_recall,
        baseline_ndcg_3=det_baseline.ndcg_3,
        ndcg_improvement=improvement,
        mean_regret=metrics.mean_regret,
        linear_baseline_ndcg_3=linear_baseline.ndcg_3,
        ndcg_improvement_over_linear=improvement_over_linear,
        confidence_intervals=metrics.confidence_intervals,
        no_positive_coverage=metrics.no_positive_coverage,
        abstention_rate=metrics.abstention_rate,
    )

    return model, full_metrics


def train_best_ranker(
    train_ds: GroupedRankingDataset,
    val_ds: GroupedRankingDataset,
    param_grid: list[dict[str, Any]] | None = None,
    n_jobs: int = 4,
    abstention_threshold: float = 0.0,
) -> tuple[Any, RankerMetrics, list[dict[str, Any]]]:
    """Perform frozen search grid and select model by:
    1. Validation NDCG@3 (higher is better)
    2. Candidate regret (lower is better)
    3. Model complexity (best_iteration, lower is better)
    """
    if param_grid is None:
        param_grid = [
            {"max_depth": 3, "learning_rate": 0.03, "n_estimators": 30, "subsample": 0.8},
            {"max_depth": 3, "learning_rate": 0.05, "n_estimators": 50, "subsample": 0.8},
            {"max_depth": 4, "learning_rate": 0.03, "n_estimators": 30, "subsample": 0.8},
            {"max_depth": 4, "learning_rate": 0.05, "n_estimators": 50, "subsample": 0.8},
            {"max_depth": 4, "learning_rate": 0.08, "n_estimators": 50, "subsample": 0.9},
            {"max_depth": 5, "learning_rate": 0.05, "n_estimators": 40, "subsample": 0.8},
        ]

    candidates: list[tuple[Any, RankerMetrics, dict[str, Any]]] = []
    for idx, p in enumerate(param_grid):
        model, metrics = train_xgbranker(
            train_ds,
            val_ds,
            params=p,
            n_jobs=n_jobs,
            early_stopping_rounds=10,
            abstention_threshold=abstention_threshold,
        )
        best_iter = getattr(model, "best_iteration", None)
        if best_iter is None:
            best_iter = p.get("n_estimators", 50)
        rec = {
            "index": idx,
            "params": p,
            "val_ndcg_3": round(metrics.ndcg_3, 4),
            "val_regret": round(metrics.mean_regret, 4),
            "best_iteration": int(best_iter),
            "ndcg_improvement": round(metrics.ndcg_improvement, 4),
        }
        candidates.append((model, metrics, rec))

    # Sort deterministically by:
    # 1. val_ndcg_3 descending
    # 2. val_regret ascending
    # 3. max_depth ascending (simpler trees)
    # 4. best_iteration ascending (fewer trees)
    # 5. n_estimators ascending
    # 6. learning_rate descending
    candidates.sort(
        key=lambda item: (
            -item[2]["val_ndcg_3"],
            item[2]["val_regret"],
            item[2]["params"].get("max_depth", 3),
            item[2]["best_iteration"],
            item[2]["params"].get("n_estimators", 30),
            -item[2]["params"].get("learning_rate", 0.03),
        )
    )

    best_model, best_metrics, _ = candidates[0]
    trace = [item[2] for item in candidates]
    return best_model, best_metrics, trace


def save_ranker_artifact(
    model: Any,
    manifest: RankerArtifactManifest,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Save XGBRanker model and RankerArtifactManifest with SHA-256 integrity hash."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    model_file = out_path / "model.json"
    manifest_file = out_path / "manifest.json"

    model.save_model(str(model_file))

    # Compute SHA-256 of saved model
    with open(model_file, "rb") as f:
        content = f.read()
    sha256_hash = hashlib.sha256(content).hexdigest()

    # Compute checksums of any other bundle files in output_dir
    bundle_checksums = dict(manifest.bundle_checksums)
    bundle_checksums["model.json"] = sha256_hash
    for fpath in out_path.glob("*.json"):
        if fpath.name not in {"model.json", "manifest.json"}:
            with open(fpath, "rb") as bf:
                bundle_checksums[fpath.name] = hashlib.sha256(bf.read()).hexdigest()

    best_iter = getattr(model, "best_iteration", None)

    # Reconstruct manifest with computed sha256 and bundle checksums
    manifest_dict = json.loads(manifest.to_json())
    manifest_dict["artifact_sha256"] = sha256_hash
    manifest_dict["bundle_checksums"] = bundle_checksums
    if best_iter is not None:
        manifest_dict["best_iteration"] = int(best_iter)

    final_manifest = RankerArtifactManifest.from_json(manifest_dict)

    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(final_manifest.to_json())

    return model_file, manifest_file


def load_ranker_artifact(
    artifact_dir: str | Path,
    expected_feature_schema: str | None = None,
    expected_label_policy: str | None = None,
    require_approval: bool = False,
) -> tuple[Any, RankerArtifactManifest]:
    """Load XGBRanker model and manifest with fail-closed SHA-256 and bundle checksum verification."""
    try:
        import xgboost as xgb
    except ImportError as e:
        raise ModuleNotFoundError(
            "xgboost is required to load ranker artifacts."
        ) from e

    art_path = Path(artifact_dir)
    manifest_file = art_path / "manifest.json"
    model_file = art_path / "model.json"

    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_file}")
    if not model_file.exists():
        raise FileNotFoundError(f"Model file not found: {model_file}")

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = RankerArtifactManifest.from_json(f.read())

    # SHA-256 verification: fail-closed
    if not manifest.artifact_sha256 or not manifest.artifact_sha256.strip():
        raise ValueError("Manifest is missing required artifact_sha256 checksum! Rejecting unverified artifact.")

    with open(model_file, "rb") as f:
        content = f.read()
    actual_sha256 = hashlib.sha256(content).hexdigest()

    if manifest.artifact_sha256 != actual_sha256:
        raise ValueError(
            f"Artifact SHA-256 checksum mismatch! Expected {manifest.artifact_sha256}, got {actual_sha256}"
        )

    # Fail-closed bundle checksums verification: all files must exist and match
    if not manifest.bundle_checksums:
        raise ValueError("Manifest bundle_checksums is empty! Required bundle checksums are missing.")

    for fname, expected_hash in manifest.bundle_checksums.items():
        bundle_file = art_path / fname
        if not bundle_file.exists():
            raise FileNotFoundError(f"REQUIRED_BUNDLE_FILE_MISSING: {fname}")
        with open(bundle_file, "rb") as bf:
            actual_bh = hashlib.sha256(bf.read()).hexdigest()
        if actual_bh != expected_hash:
            raise ValueError(
                f"Bundle file {fname} SHA-256 checksum mismatch! Expected {expected_hash}, got {actual_bh}"
            )

    # Policy & Governance checks
    if expected_feature_schema and manifest.feature_schema_version != expected_feature_schema:
        raise ValueError(
            f"Feature schema mismatch! Expected {expected_feature_schema}, got {manifest.feature_schema_version}"
        )
    if expected_label_policy and manifest.label_policy_version != expected_label_policy:
        raise ValueError(
            f"Label policy mismatch! Expected {expected_label_policy}, got {manifest.label_policy_version}"
        )
    if require_approval and manifest.approval_status != "APPROVED":
        raise ValueError(
            f"Artifact is not approved for production deployment! Current status: {manifest.approval_status}"
        )

    model = xgb.XGBRanker()
    model.load_model(str(model_file))

    return model, manifest
ALLOWED_PRODUCTION_SOURCE_KINDS = {"REAL_LIVE", "REAL_EXPORT_REPLAY"}
ALLOWED_PRODUCTION_TRUTH_TIERS = {
    TruthTier.PO_ASSERTED.value,
    TruthTier.EXPERT_CONSENSUS.value,
    TruthTier.APPLIED_CONFIRMED.value,
    TruthTier.OUTCOME_VERIFIED.value,
    TruthTier.OUTCOME_CONTRADICTED.value,
}



def compute_manifest_digest(manifest_dict: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 digest over canonical manifest content (excluding signature)."""
    payload = {k: v for k, v in manifest_dict.items() if k != "approval_signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sign_ranker_artifact(
    artifact_dir: str | Path,
    principal_id: str,
    signing_key: str | bytes | None = None,
    approval_notes: str | None = None,
) -> str:
    """Cryptographically sign a ranker artifact manifest with an HMAC-SHA256 signature."""
    if not principal_id or not principal_id.strip():
        raise ValueError("A non-empty principal_id is required to sign a ranker artifact.")

    art_path = Path(artifact_dir)
    manifest_path = art_path / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    key = signing_key or os.environ.get("NOCPRO_GOVERNANCE_SIGNING_KEY")
    if not key:
        raise ValueError(
            "HMAC governance signing key is required! Provide signing_key or set NOCPRO_GOVERNANCE_SIGNING_KEY."
        )

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["approval_status"] = "APPROVED"
    data["approved_by"] = principal_id.strip()
    data["approved_at"] = datetime.now(timezone.utc).isoformat()
    if approval_notes:
        data["approval_notes"] = approval_notes

    digest = compute_manifest_digest(data)
    if isinstance(key, str):
        key_bytes = key.encode("utf-8")
    else:
        key_bytes = key

    signature = hmac.new(key_bytes, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    data["approval_signature"] = signature

    # Write updated manifest.json
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    # Write detached approval_signature.json
    sig_payload = {
        "canonical_digest": digest,
        "principal_id": data["approved_by"],
        "signature": signature,
        "approved_at": data["approved_at"],
        "approval_notes": approval_notes,
    }
    sig_path = art_path / "approval_signature.json"
    with open(sig_path, "w", encoding="utf-8") as f:
        json.dump(sig_payload, f, indent=2, sort_keys=True)

    return signature


def verify_ranker_artifact_signature(
    artifact_dir: str | Path,
    signing_key: str | bytes | None = None,
) -> bool:
    """Verify cryptographic HMAC-SHA256 signature and detached approval binding."""
    art_path = Path(artifact_dir)
    manifest_path = art_path / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    sig_file = art_path / "approval_signature.json"
    if not sig_file.exists():
        raise ValueError(
            f"Detached approval signature file missing: {sig_file}. Production artifacts require approval_signature.json."
        )

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    with open(sig_file, "r", encoding="utf-8") as f:
        sig_file_data = json.load(f)

    manifest_sig = manifest_data.get("approval_signature")
    detached_sig = sig_file_data.get("signature")

    if not manifest_sig:
        raise ValueError("No cryptographic approval signature found on manifest.json!")
    if not detached_sig:
        raise ValueError("No cryptographic signature found in approval_signature.json!")

    if not hmac.compare_digest(manifest_sig, detached_sig):
        raise ValueError(
            "Detached approval signature does not match manifest approval_signature!"
        )

    digest = compute_manifest_digest(manifest_data)
    detached_digest = sig_file_data.get("canonical_digest")
    if not detached_digest or not hmac.compare_digest(digest, detached_digest):
        raise ValueError(
            "Detached signature canonical digest does not match manifest canonical digest!"
        )

    manifest_approved_by = manifest_data.get("approved_by")
    detached_principal = sig_file_data.get("principal_id")
    if not manifest_approved_by or manifest_approved_by != detached_principal:
        raise ValueError(
            f"Approval principal mismatch: manifest '{manifest_approved_by}' vs detached '{detached_principal}'"
        )

    manifest_approved_at = manifest_data.get("approved_at")
    detached_approved_at = sig_file_data.get("approved_at")
    if not manifest_approved_at or manifest_approved_at != detached_approved_at:
        raise ValueError(
            f"Approval timestamp mismatch: manifest '{manifest_approved_at}' vs detached '{detached_approved_at}'"
        )

    key = signing_key or os.environ.get("NOCPRO_GOVERNANCE_SIGNING_KEY")
    if not key:
        raise ValueError(
            "HMAC governance signing key is required! Provide signing_key or set NOCPRO_GOVERNANCE_SIGNING_KEY."
        )
    if isinstance(key, str):
        key_bytes = key.encode("utf-8")
    else:
        key_bytes = key

    expected_sig = hmac.new(key_bytes, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(manifest_sig, expected_sig):
        raise ValueError(
            "Cryptographic signature verification failed! Artifact manifest has been altered or signing key is invalid."
        )

    return True


def load_production_ranker_artifact(
    artifact_dir: str | Path,
    expected_feature_schema: str = FEATURE_SCHEMA_VERSION,
    expected_label_policy: str = LABEL_POLICY_VERSION,
    signing_key: str | bytes | None = None,
) -> tuple[Any, RankerArtifactManifest]:
    """Load a production-grade ranker artifact enforcing strict governance:
    - Cryptographic HMAC-SHA256 signature verification over manifest digest and detached signature binding
    - Must be APPROVED (reject DRAFT or REJECTED)
    - Must have verified approved_by principal signature
    - Strict allowlist for source_kind_mix: ONLY REAL_LIVE and REAL_EXPORT_REPLAY permitted
    - Strict allowlist for truth_tier_distribution: ONLY PO_ASSERTED, EXPERT_CONSENSUS, APPLIED_CONFIRMED, OUTCOME_VERIFIED, OUTCOME_CONTRADICTED permitted
    - Requires non-empty positive counts for distributions
    - Feature schema and label policy must strictly match
    - SHA-256 and bundle checksums verified
    """
    # 1. Base loading with integrity and policy verification
    model, manifest = load_ranker_artifact(
        artifact_dir=artifact_dir,
        expected_feature_schema=expected_feature_schema,
        expected_label_policy=expected_label_policy,
        require_approval=True,
    )

    # 2. Cryptographic Signature & Detached Binding Verification
    verify_ranker_artifact_signature(artifact_dir, signing_key=signing_key)

    # 3. Approved By check
    if not manifest.approved_by or not manifest.approved_by.strip():
        raise ValueError("Production artifact lacks valid approved_by principal signature!")

    # 4. Source Kind Mix Strict Allowlist
    source_mix = manifest.source_kind_mix or {}
    if not source_mix:
        raise ValueError("Production artifact lacks required source_kind_mix metadata!")

    total_source_count = sum(v for v in source_mix.values() if isinstance(v, (int, float)))
    if total_source_count <= 0 or any(v <= 0 for v in source_mix.values()):
        raise ValueError("Production artifact source_kind_mix must contain positive counts!")

    unapproved_sources = set(source_mix.keys()) - ALLOWED_PRODUCTION_SOURCE_KINDS
    if unapproved_sources:
        raise ValueError(
            f"Production artifact contains unapproved source kinds: {sorted(unapproved_sources)}. "
            f"Only {sorted(ALLOWED_PRODUCTION_SOURCE_KINDS)} are permitted in production."
        )

    # 5. Truth Tier Strict Allowlist
    truth_tiers = getattr(manifest, "truth_tier_distribution", {}) or {}
    if not truth_tiers:
        raise ValueError("Production artifact lacks required truth_tier_distribution metadata!")

    total_truth_count = sum(v for v in truth_tiers.values() if isinstance(v, (int, float)))
    if total_truth_count <= 0 or any(v <= 0 for v in truth_tiers.values()):
        raise ValueError("Production artifact truth_tier_distribution must contain positive counts!")

    unapproved_tiers = set(truth_tiers.keys()) - ALLOWED_PRODUCTION_TRUTH_TIERS
    if unapproved_tiers:
        raise ValueError(
            f"Production artifact contains unapproved truth tiers: {sorted(unapproved_tiers)}. "
            f"Only {sorted(ALLOWED_PRODUCTION_TRUTH_TIERS)} are permitted in production."
        )

    # 6. Methodology & Debug-Training Invariants
    if not getattr(manifest, "protected_mode_used", False):
        raise ValueError(
            "Production artifact rejected: protected_mode_used=False! "
            "Artifacts trained with --allow-unprotected-debug are strictly forbidden in production."
        )
    if not getattr(manifest, "strict_temporal_holdout_used", False):
        raise ValueError(
            "Production artifact rejected: strict_temporal_holdout_used=False! "
            "Artifacts trained with --allow-temporal-inversion-debug are strictly forbidden in production."
        )
    if getattr(manifest, "lineage_overlap_detected", False):
        raise ValueError(
            "Production artifact rejected: lineage overlap was detected during corpus training!"
        )
    if getattr(manifest, "temporal_inversion_detected", False):
        raise ValueError(
            "Production artifact rejected: temporal inversion was detected during corpus training!"
        )

    # 7. Mandatory Data Profile Governance (P0 fail-closed)
    profile_path = Path(artifact_dir) / "data_profile.json"
    if not profile_path.is_file():
        raise FileNotFoundError(
            f"Production artifact rejected: missing mandatory data profile {profile_path}!"
        )

    if not manifest.bundle_checksums or "data_profile.json" not in manifest.bundle_checksums:
        raise ValueError(
            "Production artifact rejected: data_profile.json is missing from manifest bundle_checksums!"
        )

    with open(profile_path, "rb") as pf:
        profile_bytes = pf.read()

    calc_sha256 = hashlib.sha256(profile_bytes).hexdigest()
    expected_sha256 = manifest.bundle_checksums["data_profile.json"]
    if not hmac.compare_digest(calc_sha256, expected_sha256):
        raise ValueError(
            f"Production artifact rejected: data_profile.json sha256 mismatch! "
            f"Expected {expected_sha256}, got {calc_sha256}"
        )

    if not getattr(manifest, "data_profile_fingerprint", None):
        raise ValueError(
            "Production artifact rejected: missing mandatory data_profile_fingerprint in manifest!"
        )

    try:
        dp_payload = json.loads(profile_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Production artifact rejected: failed to parse data_profile.json: {e}") from e

    from .contracts import canonical_fingerprint
    calc_fp = canonical_fingerprint(dp_payload)
    if not hmac.compare_digest(calc_fp, manifest.data_profile_fingerprint):
        raise ValueError(
            "Production artifact rejected: data_profile.json fingerprint does not match manifest!"
        )

    if dp_payload.get("lineage_overlap_detected", False) is not False:
        raise ValueError(
            "Production artifact rejected: data_profile.json reports lineage_overlap_detected=True!"
        )

    if dp_payload.get("temporal_inversion_detected", False) is not False:
        raise ValueError(
            "Production artifact rejected: data_profile.json reports temporal_inversion_detected=True!"
        )

    if dp_payload.get("corpus_fingerprint") != manifest.corpus_fingerprint:
        raise ValueError(
            "Production artifact rejected: data_profile corpus_fingerprint does not match manifest!"
        )

    return model, manifest

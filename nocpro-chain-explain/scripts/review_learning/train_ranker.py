"""CLI script to train XGBRanker model and save verified artifact.

Usage:
  # Synthetic training (for pipeline validation & offline testing):
  python scripts/review_learning/train_ranker.py --synthetic-groups 30 --output-dir artifacts/review_ranker/v1

  # Postgres training (real review data):
  python scripts/review_learning/train_ranker.py --source postgres --database-url postgresql+asyncpg://... --cutoff 2026-09-10T00:00:00Z --output-dir artifacts/review_ranker/v1
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "services" / "analysis-worker"))
sys.path.insert(0, str(ROOT_DIR / "services" / "api"))
if (ROOT_DIR.parent / "nocpro-mock" / "src").exists():
    sys.path.insert(0, str(ROOT_DIR.parent / "nocpro-mock" / "src"))


def sanitize_creation_command(argv: list[str]) -> str:
    """Sanitize sensitive credentials, tokens, and passwords in command line arguments."""
    sanitized_args: list[str] = []
    skip_next = False
    for i, arg in enumerate(argv):
        if skip_next:
            sanitized_args.append("***")
            skip_next = False
            continue

        if arg in ("--signing-key", "--token", "--password", "--secret", "--api-key"):
            sanitized_args.append(arg)
            skip_next = True
            continue

        cleaned = arg
        # 1. Authority credentials: ://user:pass@
        cleaned = re.sub(r"://([^:@\s]+):([^@\s]+)@", r"://***:***@", cleaned)
        # 2. Query params and key-value pairs (e.g. password=..., token=..., sslkey=...)
        cleaned = re.sub(
            r"((?:password|token|access_token|secret|sslkey|api_key)=)[^&\s]+",
            r"\1***",
            cleaned,
            flags=re.IGNORECASE,
        )
        # 3. DSN parameter formats like 'password=xxx'
        cleaned = re.sub(
            r"(password\s*=\s*)[^\s;&'\"]+",
            r"\1***",
            cleaned,
            flags=re.IGNORECASE,
        )
        sanitized_args.append(cleaned)
    return " ".join(sanitized_args)


from review_learning import (
    FEATURE_SCHEMA_VERSION,
    LABEL_POLICY_VERSION,
    GroupedRankingDataset,
    RankerArtifactManifest,
    RankerMetrics,
    RankingCorpus,
    build_data_profile,
    canonical_fingerprint,
    evaluate_deterministic_baseline,
    evaluate_linear_baseline,
    evaluate_predictions,
    generate_synthetic_review_corpus,
    materialize_training_corpus,
    materialize_training_corpus_from_repository_groups,
    save_ranker_artifact,
    train_best_ranker,
    train_xgbranker,
)


def evaluate_slice_subset(
    dataset: GroupedRankingDataset,
    scores: list[float],
    matched_group_indices: list[int],
    abstention_threshold: float = 0.0,
) -> dict[str, Any]:
    """Helper to evaluate ranking metrics on a subset of groups."""
    if not matched_group_indices:
        return {"num_groups": 0, "status": "NO_DATA"}

    sub_X: list[list[float]] = []
    sub_y: list[int] = []
    sub_qids: list[str] = []
    sub_cand_ids: list[str] = []
    sub_sizes: list[int] = []
    sub_weights: list[float] = []
    sub_rids: list[str] = []
    sub_scores: list[float] = []

    cur = 0
    for g_i, size in enumerate(dataset.group_sizes):
        if g_i in matched_group_indices:
            sub_X.extend(dataset.X[cur : cur + size])
            sub_y.extend(dataset.y[cur : cur + size])
            sub_qids.extend(dataset.qids[cur : cur + size])
            sub_cand_ids.extend(dataset.candidate_ids[cur : cur + size])
            sub_scores.extend(scores[cur : cur + size])
            sub_sizes.append(size)
            sub_weights.append(dataset.group_weights[g_i])
            sub_rids.append(dataset.review_ids[g_i])
        cur += size

    sub_ds = GroupedRankingDataset(
        qids=sub_qids,
        X=sub_X,
        y=sub_y,
        group_sizes=sub_sizes,
        group_weights=sub_weights,
        candidate_ids=sub_cand_ids,
        review_ids=sub_rids,
    )

    sub_metrics = evaluate_predictions(sub_ds, sub_scores, abstention_threshold=abstention_threshold)
    sub_baseline = evaluate_deterministic_baseline(sub_ds)

    return {
        "num_groups": len(sub_sizes),
        "ndcg_1": round(sub_metrics.ndcg_1, 4),
        "ndcg_3": round(sub_metrics.ndcg_3, 4),
        "ndcg_5": round(sub_metrics.ndcg_5, 4),
        "mean_regret": round(sub_metrics.mean_regret, 4),
        "baseline_ndcg_3": round(sub_baseline.ndcg_3, 4),
        "ndcg_improvement": round(sub_metrics.ndcg_3 - sub_baseline.ndcg_3, 4),
        "abstention_rate": round(sub_metrics.abstention_rate, 4),
    }


def evaluate_all_slices(
    dataset: GroupedRankingDataset,
    scores: list[float],
    abstention_threshold: float = 0.0,
) -> dict[str, Any]:
    """Compute slice metrics across operations, source kinds, and truth tiers."""
    results: dict[str, Any] = {
        "operations": {},
        "source_kinds": {},
        "truth_tiers": {},
    }

    # 1. Operation slices (partitioned by operation of the best/approved candidate)
    ops = ["REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS"]
    op_groups: dict[str, list[int]] = {op: [] for op in ops}

    cur = 0
    for g_i, size in enumerate(dataset.group_sizes):
        group_X = dataset.X[cur : cur + size]
        group_y = dataset.y[cur : cur + size]
        cur += size
        if not group_y:
            continue
        max_rel = max(group_y)
        best_idx = group_y.index(max_rel)
        best_row = group_X[best_idx]
        for op_idx, op_name in enumerate(ops):
            if len(best_row) > op_idx and best_row[op_idx] == 1.0:
                op_groups[op_name].append(g_i)
                break

    for op_name in ops:
        results["operations"][op_name] = evaluate_slice_subset(dataset, scores, op_groups[op_name], abstention_threshold=abstention_threshold)

    # 2. Source kinds
    distinct_sources = set(dataset.source_kinds)
    for sk in distinct_sources:
        if not sk:
            continue
        matched_idx = [i for i, s in enumerate(dataset.source_kinds) if s == sk]
        results["source_kinds"][sk] = evaluate_slice_subset(dataset, scores, matched_idx, abstention_threshold=abstention_threshold)

    # 3. Truth tiers
    distinct_tiers: set[str] = set()
    for t_list in dataset.group_truth_tiers:
        distinct_tiers.update(t_list)
    for tier in distinct_tiers:
        if not tier:
            continue
        matched_idx = [
            i for i, t_list in enumerate(dataset.group_truth_tiers) if tier in t_list
        ]
        results["truth_tiers"][tier] = evaluate_slice_subset(dataset, scores, matched_idx, abstention_threshold=abstention_threshold)
    return results


def evaluate_operation_slices(
    dataset: GroupedRankingDataset,
    scores: list[float],
) -> dict[str, Any]:
    """Compute slice metrics across candidate operations."""
    return evaluate_all_slices(dataset, scores)["operations"]


async def fetch_postgres_groups(db_url: str, cutoff: str) -> list[dict[str, Any]]:
    """Fetch review groups from PostgreSQL database before cutoff."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from nocpro_api.persistence.repository import SnapshotRepository

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SnapshotRepository(session_factory)
    cutoff_dt = datetime.datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    if cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=datetime.timezone.utc)
    groups = await repo.training_review_groups_before(cutoff_dt)
    await engine.dispose()
    return groups


def get_dependency_versions() -> dict[str, str]:
    """Capture runtime dependency versions for governance manifest."""
    import numpy as np
    import scipy
    import sklearn
    import xgboost as xgb

    return {
        "python": sys.version.split()[0],
        "xgboost": getattr(xgb, "__version__", "unknown"),
        "scikit-learn": getattr(sklearn, "__version__", "unknown"),
        "numpy": getattr(np, "__version__", "unknown"),
        "scipy": getattr(scipy, "__version__", "unknown"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train XGBRanker and export artifact")
    parser.add_argument("--source", choices=["synthetic", "postgres"], default="synthetic", help="Data source")
    parser.add_argument("--database-url", type=str, default=os.getenv("DATABASE_URL", ""), help="Database connection URL")
    parser.add_argument("--cutoff", type=str, default="2026-09-10T00:00:00Z", help="Temporal cutoff")
    parser.add_argument("--synthetic-groups", type=int, default=30, help="Number of synthetic review groups")
    parser.add_argument("--output-dir", type=str, default="artifacts/review_ranker/v1", help="Output directory")
    parser.add_argument("--model-version", type=str, default="v1", help="Model artifact version")
    parser.add_argument("--n-estimators", type=int, default=50, help="Number of boosting trees")
    parser.add_argument("--max-depth", type=int, default=4, help="Maximum tree depth")
    parser.add_argument("--learning-rate", type=float, default=0.05, help="Learning rate")
    parser.add_argument("--n-jobs", type=int, default=4, help="Fixed CPU threads")
    parser.add_argument("--grid-search", action="store_true", default=True, help="Run hyperparameter search grid")
    parser.add_argument("--protected-mode", action="store_true", default=None, help="Enforce fail-closed verification of schema, fingerprints, and precomputed features")
    parser.add_argument("--allow-unprotected-debug", action="store_true", default=False, help="Allow unprotected debug mode for postgres source")
    parser.add_argument("--strict-temporal-holdout", action="store_true", default=None, help="Embargo straddling lineages to guarantee zero temporal inversion")
    parser.add_argument("--allow-temporal-inversion-debug", action="store_true", default=False, help="Allow temporal inversion for debug")
    parser.add_argument("--abstention-threshold", type=float, default=0.0, help="Abstention margin threshold")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.allow_unprotected_debug:
        protected = False
    elif args.protected_mode is not None:
        protected = args.protected_mode
    else:
        protected = (args.source == "postgres")

    if args.allow_temporal_inversion_debug:
        strict_temporal = False
    elif args.strict_temporal_holdout is not None:
        strict_temporal = args.strict_temporal_holdout
    else:
        strict_temporal = (args.source == "postgres")

    print(f"=== REVIEW RANKER TRAINING [{args.model_version}] ===")
    print(f"Source: {args.source}")
    print(f"Cutoff: {args.cutoff}")
    print(f"Protected Mode: {protected}")
    print(f"Strict Temporal Holdout: {strict_temporal}")
    print(f"Abstention Threshold: {args.abstention_threshold}")

    raw_sessions = None
    if args.source == "postgres":
        if not args.database_url:
            print("ERROR: --database-url is required when --source is postgres", file=sys.stderr)
            sys.exit(1)
        print(f"Connecting to PostgreSQL and fetching review groups before {args.cutoff}...")
        repo_groups = asyncio.run(fetch_postgres_groups(args.database_url, args.cutoff))
        print(f"Fetched {len(repo_groups)} raw review groups from repository.")
        corpus = materialize_training_corpus_from_repository_groups(
            repo_groups,
            cutoff=args.cutoff,
            protected_mode=protected,
            strict_temporal_holdout=strict_temporal,
        )
    else:
        print(f"Generating {args.synthetic_groups} synthetic groups (SYNTHETIC_TEST)...")
        sessions, exposures, feedbacks = generate_synthetic_review_corpus(
            group_count=args.synthetic_groups,
            base_date="2026-09-01T10:00:00Z",
        )
        raw_sessions = sessions
        corpus = materialize_training_corpus(
            sessions=sessions,
            exposures=exposures,
            feedbacks=feedbacks,
            cutoff=args.cutoff,
            protected_mode=protected,
            strict_temporal_holdout=strict_temporal,
        )

    # 1. Profile and Audit
    profile = build_data_profile(corpus, raw_sessions=raw_sessions)
    print("\n" + profile.to_markdown() + "\n")

    profile_json_path = out_dir / "data_profile.json"
    with open(profile_json_path, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, indent=2)

    # Fail-closed checks
    if profile.lineage_overlap_detected:
        print("FATAL: Lineage leakage detected in corpus splits! Refusing to train.", file=sys.stderr)
        sys.exit(1)

    if corpus.train.num_groups == 0:
        print("FATAL: Training split contains 0 valid groups. Cannot train model.", file=sys.stderr)
        sys.exit(1)

    if corpus.val.num_groups == 0 or corpus.test.num_groups == 0:
        print(
            f"FATAL: Split starvation detected! Validation ({corpus.val.num_groups}) or Test ({corpus.test.num_groups}) "
            "split contains 0 valid groups. Fail-closed: refusing to train or export unverified model.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. Train and Select Model
    val_ds = corpus.val
    selection_trace: list[dict[str, Any]] = []

    if args.grid_search and val_ds.num_groups > 0:
        print(f"Running deterministic grid search on {corpus.train.num_groups} train / {val_ds.num_groups} val groups...")
        model, eval_metrics, selection_trace = train_best_ranker(
            train_ds=corpus.train,
            val_ds=val_ds,
            n_jobs=args.n_jobs,
            abstention_threshold=args.abstention_threshold,
        )
        best_params = selection_trace[0]["params"] if selection_trace else {}
        hyperparams = {
            "objective": "rank:ndcg",
            "eval_metric": "ndcg@3",
            "tree_method": "hist",
            "random_state": 42,
            "n_jobs": args.n_jobs,
            **best_params,
        }
    else:
        hyperparams = {
            "objective": "rank:ndcg",
            "eval_metric": "ndcg@3",
            "tree_method": "hist",
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "learning_rate": args.learning_rate,
            "subsample": 0.8,
            "random_state": 42,
            "n_jobs": args.n_jobs,
        }
        print(f"Training single XGBRanker on {corpus.train.num_groups} training groups...")
        model, eval_metrics = train_xgbranker(
            corpus.train,
            val_ds,
            params=hyperparams,
            n_jobs=args.n_jobs,
            abstention_threshold=args.abstention_threshold,
        )

    print(f"\n=== Validation Split Evaluation ===")
    print(f"NDCG@1: {eval_metrics.ndcg_1:.4f}")
    print(f"NDCG@3: {eval_metrics.ndcg_3:.4f}")
    print(f"NDCG@5: {eval_metrics.ndcg_5:.4f}")
    print(f"Mean Regret: {eval_metrics.mean_regret:.4f}")
    print(f"Top-1 Recall: {eval_metrics.top1_approved_recall:.4f}")
    print(f"Top-3 Recall: {eval_metrics.top3_approved_recall:.4f}")
    print(f"Baseline NDCG@3 (Deterministic): {eval_metrics.baseline_ndcg_3:.4f}")
    print(f"Baseline NDCG@3 (Linear Ridge): {eval_metrics.linear_baseline_ndcg_3:.4f}")
    print(f"NDCG@3 Improvement (vs Deterministic): {eval_metrics.ndcg_improvement:+.4f}")
    print(f"NDCG@3 Improvement (vs Linear): {eval_metrics.ndcg_improvement_over_linear:+.4f}")
    print(f"NDCG@3 95% CI: {eval_metrics.confidence_intervals.get('ndcg_3_ci95')}")
    print(f"Mean Regret 95% CI: {eval_metrics.confidence_intervals.get('mean_regret_ci95')}")
    print(f"Abstention Rate: {eval_metrics.abstention_rate:.4f}")

    # 3. Compute slice metrics on validation set
    preds = list(model.predict(val_ds.X))
    slice_metrics = evaluate_all_slices(val_ds, preds, abstention_threshold=args.abstention_threshold)

    # 4. Fingerprints and governance metadata
    lineage_fp = canonical_fingerprint({
        "train": sorted(set(corpus.train.lineages)),
        "val": sorted(set(corpus.val.lineages)),
        "test": sorted(set(corpus.test.lineages)),
    })
    dep_versions = get_dependency_versions()

    # 5. Construct Manifest and Save Artifact
    best_iter = getattr(model, "best_iteration", None)
    manifest = RankerArtifactManifest(
        model_version=args.model_version,
        model_family="XGBRanker",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        label_policy_version=LABEL_POLICY_VERSION,
        training_cutoff=corpus.cutoff,
        corpus_fingerprint=corpus.corpus_fingerprint,
        hyperparameters=hyperparams,
        metrics=eval_metrics,
        slice_metrics=slice_metrics,
        artifact_sha256="",
        lineage_fingerprint=lineage_fp,
        bundle_checksums={},
        dependency_versions=dep_versions,
        qid_counts={
            "train": corpus.train.num_groups,
            "val": corpus.val.num_groups,
            "test": corpus.test.num_groups,
        },
        operation_coverage=profile.operation_coverage,
        source_kind_mix=profile.source_kind_distribution,
        truth_tier_distribution=profile.truth_tier_distribution,
        creation_command=sanitize_creation_command(sys.argv),
        best_iteration=int(best_iter) if best_iter is not None else None,
        selection_trace=selection_trace,
        abstention_threshold=args.abstention_threshold,
        protected_mode_used=protected,
        strict_temporal_holdout_used=strict_temporal,
        lineage_overlap_detected=profile.lineage_overlap_detected,
        temporal_inversion_detected=profile.temporal_inversion_detected,
        excluded_straddling_lineages=list(profile.excluded_straddling_lineages),
        data_profile_fingerprint=profile.data_profile_fingerprint,
        approval_status="DRAFT",
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )

    model_path, manifest_path = save_ranker_artifact(model, manifest, out_dir)
    print(f"\nArtifact saved successfully:")
    print(f"- Model: {model_path}")
    print(f"- Manifest: {manifest_path}")
    print(f"- Data Profile: {profile_json_path}")


if __name__ == "__main__":
    main()

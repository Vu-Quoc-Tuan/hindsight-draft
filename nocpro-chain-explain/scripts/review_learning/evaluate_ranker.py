"""CLI script to evaluate ranker performance and compare against deterministic baseline.

Usage:
  # Evaluate baseline only on test split of synthetic data:
  python scripts/review_learning/evaluate_ranker.py --source synthetic --allow-synthetic --synthetic-groups 30 --split test

  # Evaluate trained model artifact against baseline:
  python scripts/review_learning/evaluate_ranker.py --artifact-dir artifacts/review_ranker/synthetic-test --source synthetic --allow-synthetic --synthetic-groups 30 --split test

  # Evaluate trained model on PostgreSQL data:
  python scripts/review_learning/evaluate_ranker.py --artifact-dir artifacts/review_ranker/v1 --source postgres --database-url postgresql+asyncpg://... --cutoff 2026-09-10T00:00:00Z --split test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "services" / "analysis-worker"))
sys.path.insert(0, str(ROOT_DIR / "services" / "api"))
if (ROOT_DIR.parent / "nocpro-mock" / "src").exists():
    sys.path.insert(0, str(ROOT_DIR.parent / "nocpro-mock" / "src"))

from review_learning import (
    GroupedRankingDataset,
    RankingCorpus,
    evaluate_deterministic_baseline,
    evaluate_linear_baseline,
    evaluate_predictions,
    generate_synthetic_review_corpus,
    load_production_ranker_artifact,
    load_ranker_artifact,
    materialize_training_corpus,
    materialize_training_corpus_from_repository_groups,
)
from scripts.review_learning.postgres_source import fetch_postgres_groups
from scripts.review_learning.slice_metrics import evaluate_all_slices, evaluate_operation_slices, evaluate_slice_subset


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate baseline and model ranking")
    parser.add_argument("--artifact-dir", type=str, default="", help="Path to ranker artifact directory")
    parser.add_argument("--source", choices=["synthetic", "postgres"], default="postgres", help="Data source; PostgreSQL is required by default")
    parser.add_argument("--database-url", type=str, default=os.getenv("DATABASE_URL", ""), help="Database connection URL")
    parser.add_argument("--cutoff", type=str, default="2026-09-10T00:00:00Z", help="Temporal cutoff")
    parser.add_argument("--synthetic-groups", type=int, default=30, help="Number of synthetic groups")
    parser.add_argument("--allow-synthetic", action="store_true", help="Required acknowledgement for synthetic test data")
    parser.add_argument("--split", choices=["train", "val", "test"], default="test", help="Evaluation split")
    parser.add_argument("--allow-unprotected-debug", action="store_true", default=False, help="Allow unprotected debug mode for postgres source")
    parser.add_argument("--strict-temporal-holdout", action="store_true", default=None, help="Embargo straddling lineages to guarantee zero temporal inversion")
    parser.add_argument("--allow-temporal-inversion-debug", action="store_true", default=False, help="Allow temporal inversion for debug")
    parser.add_argument("--require-production-governance", action="store_true", default=False, help="Require production governance (valid HMAC signature, no forbidden tiers)")
    parser.add_argument("--abstention-threshold", type=float, default=None, help="Optional override for abstention margin threshold")
    args = parser.parse_args()

    if args.source == "synthetic" and not args.allow_synthetic:
        parser.error("--source synthetic requires --allow-synthetic; synthetic data is test-only")

    protected_mode = (not args.allow_unprotected_debug) if args.source == "postgres" else False

    if args.allow_temporal_inversion_debug:
        strict_temporal = False
    elif args.strict_temporal_holdout is not None:
        strict_temporal = args.strict_temporal_holdout
    else:
        strict_temporal = (args.source == "postgres")

    if args.source == "postgres":
        if not args.database_url:
            print("ERROR: --database-url is required when --source is postgres", file=sys.stderr)
            sys.exit(1)
        repo_groups = asyncio.run(fetch_postgres_groups(args.database_url, args.cutoff))
        corpus = materialize_training_corpus_from_repository_groups(
            repo_groups,
            cutoff=args.cutoff,
            protected_mode=protected_mode,
            strict_temporal_holdout=strict_temporal,
        )
    else:
        sessions, exposures, feedbacks = generate_synthetic_review_corpus(
            group_count=args.synthetic_groups,
            base_date="2026-09-01T10:00:00Z",
        )
        corpus = materialize_training_corpus(
            sessions=sessions,
            exposures=exposures,
            feedbacks=feedbacks,
            cutoff=args.cutoff,
            protected_mode=protected_mode,
            strict_temporal_holdout=strict_temporal,
        )

    split_ds: GroupedRankingDataset = getattr(corpus, args.split)
    print(f"=== EVALUATION ON {args.split.upper()} SPLIT ===")
    print(f"Groups: {split_ds.num_groups}, Candidates: {split_ds.num_candidates}")

    if split_ds.num_groups == 0:
        print(f"ERROR: {args.split} split has 0 groups. Cannot evaluate.", file=sys.stderr)
        sys.exit(1)

    det_baseline = evaluate_deterministic_baseline(split_ds)
    linear_baseline = evaluate_linear_baseline(corpus.train, split_ds)

    print("\n--- DETERMINISTIC / PARETO BASELINE ---")
    print(f"NDCG@1: {det_baseline.ndcg_1:.4f}")
    print(f"NDCG@3: {det_baseline.ndcg_3:.4f}")
    print(f"NDCG@5: {det_baseline.ndcg_5:.4f}")
    print(f"Mean Regret: {det_baseline.mean_regret:.4f}")
    print(f"Top-1 Recall: {det_baseline.top1_approved_recall:.4f}")
    print(f"Top-3 Recall: {det_baseline.top3_approved_recall:.4f}")

    print("\n--- LINEAR (RIDGE) BASELINE ---")
    print(f"NDCG@1: {linear_baseline.ndcg_1:.4f}")
    print(f"NDCG@3: {linear_baseline.ndcg_3:.4f}")
    print(f"NDCG@5: {linear_baseline.ndcg_5:.4f}")
    print(f"Mean Regret: {linear_baseline.mean_regret:.4f}")
    print(f"Top-1 Recall: {linear_baseline.top1_approved_recall:.4f}")

    if args.artifact_dir:
        print(f"\n--- LOADING TRAINED MODEL FROM {args.artifact_dir} ---")
        if args.require_production_governance:
            model, manifest = load_production_ranker_artifact(args.artifact_dir)
            print("Production Governance: VERIFIED (HMAC signature & allowed sources)")
        else:
            model, manifest = load_ranker_artifact(args.artifact_dir)
        print(f"Model Version: {manifest.model_version}")
        print(f"Artifact SHA-256: {manifest.artifact_sha256[:16]}... (VERIFIED)")

        abstention_thresh = (
            args.abstention_threshold
            if args.abstention_threshold is not None
            else getattr(manifest, "abstention_threshold", 0.0)
        )
        print(f"Abstention Threshold: {abstention_thresh}")

        preds = list(model.predict(split_ds.X))
        model_metrics = evaluate_predictions(split_ds, preds, abstention_threshold=abstention_thresh)
        improvement_vs_det = model_metrics.ndcg_3 - det_baseline.ndcg_3
        improvement_vs_linear = model_metrics.ndcg_3 - linear_baseline.ndcg_3

        print(f"\n--- MODEL PERFORMANCE ON {args.split.upper()} SPLIT ---")
        print(f"NDCG@1: {model_metrics.ndcg_1:.4f}")
        print(f"NDCG@3: {model_metrics.ndcg_3:.4f} (Det Baseline: {det_baseline.ndcg_3:.4f}, Delta: {improvement_vs_det:+.4f})")
        print(f"NDCG@3 vs Linear Baseline Delta: {improvement_vs_linear:+.4f}")
        print(f"NDCG@5: {model_metrics.ndcg_5:.4f}")
        print(f"Mean Regret: {model_metrics.mean_regret:.4f} (Det Baseline: {det_baseline.mean_regret:.4f})")
        print(f"Top-1 Recall: {model_metrics.top1_approved_recall:.4f}")
        print(f"Top-3 Recall: {model_metrics.top3_approved_recall:.4f}")
        print(f"NDCG@3 95% CI: {model_metrics.confidence_intervals.get('ndcg_3_ci95')}")
        print(f"Mean Regret 95% CI: {model_metrics.confidence_intervals.get('mean_regret_ci95')}")
        print(f"Abstention Rate: {model_metrics.abstention_rate:.4f}")

        slices = evaluate_all_slices(split_ds, preds, abstention_threshold=abstention_thresh)
        print("\n--- OPERATION SLICES ---")
        for op, data in slices["operations"].items():
            if data.get("status") == "NO_DATA":
                print(f"- {op}: No groups")
            else:
                print(
                    f"- {op} (groups={data['num_groups']}): NDCG@3={data['ndcg_3']}, "
                    f"Baseline={data['baseline_ndcg_3']}, Delta={data['ndcg_improvement']:+.4f}, Regret={data['mean_regret']}"
                )

        if any(v.get("num_groups", 0) > 0 for v in slices["truth_tiers"].values()):
            print("\n--- TRUTH TIER SLICES ---")
            for tier, data in slices["truth_tiers"].items():
                if data.get("num_groups", 0) > 0:
                    print(
                        f"- {tier} (groups={data['num_groups']}): NDCG@3={data['ndcg_3']}, "
                        f"Baseline={data['baseline_ndcg_3']}, Delta={data['ndcg_improvement']:+.4f}"
                    )


if __name__ == "__main__":
    main()

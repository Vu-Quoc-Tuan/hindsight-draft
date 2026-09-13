"""CLI script to materialize review learning training corpus and data profile.

Usage:
  # Synthetic mode (explicit test-only):
  python scripts/review_learning/materialize_training_corpus.py --source synthetic --allow-synthetic --cutoff 2026-09-10T00:00:00Z --synthetic-groups 30 --output-dir .cache/corpus

  # Postgres mode (real database):
  python scripts/review_learning/materialize_training_corpus.py --source postgres --database-url postgresql+asyncpg://... --cutoff 2026-09-10T00:00:00Z --output-dir .cache/corpus
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "services" / "analysis-worker"))
sys.path.insert(0, str(ROOT_DIR / "services" / "api"))
if (ROOT_DIR.parent / "nocpro-mock" / "src").exists():
    sys.path.insert(0, str(ROOT_DIR.parent / "nocpro-mock" / "src"))

from review_learning import (
    build_data_profile,
    generate_synthetic_review_corpus,
    materialize_training_corpus,
    materialize_training_corpus_from_repository_groups,
)
from scripts.review_learning.postgres_source import fetch_postgres_groups


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize review-learning corpus and data profile")
    parser.add_argument("--source", choices=["synthetic", "postgres"], default="postgres", help="Data source; PostgreSQL is required by default")
    parser.add_argument("--database-url", type=str, default=os.getenv("DATABASE_URL", ""), help="PostgreSQL database URL")
    parser.add_argument("--cutoff", type=str, default="2026-09-10T00:00:00Z", help="Exclusive cutoff timestamp")
    parser.add_argument("--synthetic-groups", type=int, default=30, help="Generate N synthetic review groups for testing")
    parser.add_argument("--allow-synthetic", action="store_true", help="Required acknowledgement for synthetic test data")
    parser.add_argument("--output-dir", type=str, default=".cache/corpus", help="Directory to write output artifacts")
    parser.add_argument("--allow-unprotected-debug", action="store_true", default=False, help="Allow unprotected debug mode for postgres source")
    parser.add_argument("--strict-temporal-holdout", action="store_true", default=None, help="Embargo straddling lineages to guarantee zero temporal inversion")
    parser.add_argument("--allow-temporal-inversion-debug", action="store_true", default=False, help="Allow temporal inversion for debug")
    args = parser.parse_args()

    if args.source == "synthetic" and not args.allow_synthetic:
        parser.error("--source synthetic requires --allow-synthetic; synthetic data is test-only")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    protected_mode = (not args.allow_unprotected_debug) if args.source == "postgres" else False

    if args.allow_temporal_inversion_debug:
        strict_temporal = False
    elif args.strict_temporal_holdout is not None:
        strict_temporal = args.strict_temporal_holdout
    else:
        strict_temporal = (args.source == "postgres")

    raw_sessions = None
    if args.source == "postgres":
        if not args.database_url:
            print("ERROR: --database-url is required when --source is postgres", file=sys.stderr)
            sys.exit(1)
        print(f"Fetching review groups from PostgreSQL before cutoff: {args.cutoff} (protected_mode={protected_mode}, strict_temporal={strict_temporal})...")
        repo_groups = asyncio.run(fetch_postgres_groups(args.database_url, args.cutoff))
        print(f"Fetched {len(repo_groups)} raw review groups from repository.")
        corpus = materialize_training_corpus_from_repository_groups(
            groups=repo_groups,
            cutoff=args.cutoff,
            protected_mode=protected_mode,
            strict_temporal_holdout=strict_temporal,
        )
    else:
        print(f"Generating {args.synthetic_groups} synthetic review groups (SYNTHETIC_TEST)...")
        sessions, exposures, feedbacks = generate_synthetic_review_corpus(
            group_count=args.synthetic_groups,
            base_date="2026-09-01T10:00:00Z",
        )
        raw_sessions = sessions
        print(f"Materializing training corpus with cutoff: {args.cutoff} (strict_temporal={strict_temporal})...")
        corpus = materialize_training_corpus(
            sessions=sessions,
            exposures=exposures,
            feedbacks=feedbacks,
            cutoff=args.cutoff,
            protected_mode=protected_mode,
            strict_temporal_holdout=strict_temporal,
        )

    print("Generating data profile report...")
    profile = build_data_profile(corpus, raw_sessions=raw_sessions)

    # Save data profile markdown and json
    profile_md_path = out_dir / "data_profile.md"
    profile_json_path = out_dir / "data_profile.json"
    with open(profile_md_path, "w", encoding="utf-8") as f:
        f.write(profile.to_markdown())
    with open(profile_json_path, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, indent=2)

    # Save corpus json
    corpus_json_path = out_dir / "corpus.json"
    corpus_dict = {
        "corpus_fingerprint": corpus.corpus_fingerprint,
        "cutoff": corpus.cutoff,
        "feature_schema_version": corpus.feature_schema_version,
        "label_policy_version": corpus.label_policy_version,
        "train": {
            "qids": corpus.train.qids,
            "group_sizes": corpus.train.group_sizes,
            "group_weights": corpus.train.group_weights,
            "candidate_ids": corpus.train.candidate_ids,
            "y": corpus.train.y,
            "X": corpus.train.X,
            "num_candidates": corpus.train.num_candidates,
            "num_groups": corpus.train.num_groups,
        },
        "val": {
            "qids": corpus.val.qids,
            "group_sizes": corpus.val.group_sizes,
            "group_weights": corpus.val.group_weights,
            "candidate_ids": corpus.val.candidate_ids,
            "y": corpus.val.y,
            "X": corpus.val.X,
            "num_candidates": corpus.val.num_candidates,
            "num_groups": corpus.val.num_groups,
        },
        "test": {
            "qids": corpus.test.qids,
            "group_sizes": corpus.test.group_sizes,
            "group_weights": corpus.test.group_weights,
            "candidate_ids": corpus.test.candidate_ids,
            "y": corpus.test.y,
            "X": corpus.test.X,
            "num_candidates": corpus.test.num_candidates,
            "num_groups": corpus.test.num_groups,
        },
        "excluded_groups": [
            {"review_id": eg.review_id, "reason": eg.reason, "details": eg.details}
            for eg in corpus.excluded_groups
        ],
    }
    with open(corpus_json_path, "w", encoding="utf-8") as f:
        json.dump(corpus_dict, f, indent=2)

    print(f"\nSuccessfully wrote outputs to {out_dir}:")
    print(f"  - {profile_md_path}")
    print(f"  - {profile_json_path}")
    print(f"  - {corpus_json_path}")
    print("\n" + profile.to_markdown())


if __name__ == "__main__":
    main()

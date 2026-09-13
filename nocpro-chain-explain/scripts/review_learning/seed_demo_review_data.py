"""Seed clearly-labelled synthetic review evidence for ``make dev-demo``.

This is intentionally a local demonstration utility, not an import mechanism
for operator feedback.  It only creates records in the ``demo_synthetic_*``
namespace, marks every session as ``SYNTHETIC_TEST`` and every feedback/case as
``TEST_FIXTURE``, and never deletes or changes an existing record.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "services" / "analysis-worker"))
sys.path.insert(0, str(ROOT_DIR / "services" / "api"))

from nocpro_api.persistence.repository import SnapshotRepository
from review_learning.case_fingerprint import (
    FINGERPRINT_SCHEMA_VERSION,
    compute_case_fingerprint_payload,
)
from review_learning.contracts import ReviewCase, ReviewFeedback, TruthTier
from review_learning.synthetic_factory import generate_synthetic_review_group


# A versioned namespace makes a changed fixture append-only as well: an earlier
# demo run is never rewritten merely because the fixture representation evolves.
# Keep the version suffix short because exposure primary keys include both review
# and candidate IDs and are intentionally limited to 64 characters in PostgreSQL.
DEMO_PREFIX = "demo_synthetic_"
DEMO_VERSION = "v2"
DEMO_DOMAIN = "IP_NETWORK"
DEMO_SCENARIOS = (
    "STANDARD_TOP1_APPROVED",
    "SUBOPTIMAL_TOP1_RANK2_APPROVED",
    "RANK3_APPROVED_MOVE_PREFERRED",
    "MISSING_FEATURES",
)


@dataclass(frozen=True)
class DemoSeedSummary:
    requested_groups: int
    created_groups: int
    existing_groups: int
    created_exposures: int
    created_feedbacks: int
    created_cases: int


def _ensure_not_production() -> None:
    environment = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    if environment in {"prod", "production"}:
        raise RuntimeError("dev-demo is disabled when APP_ENV/ENVIRONMENT is production")


def _case_payload(operation: str, ordinal: int) -> tuple[dict[str, object], str]:
    """Produce fully observed, deterministic blocks for the local case demo."""
    blocks: dict[str, dict[str, object]] = {
        "chain_context": {
            "alarm_count": 5 + (ordinal % 3),
            "device_count": 3,
            "unique_alarm_type_count": 3,
            "failure_domain_count": 1,
        },
        "evidence_shape": {
            "channels_available": 3,
            "channels_total": 3,
            "has_cross_chain_evidence": operation in {"MOVE_MEMBER", "MERGE_CHAINS"},
        },
        "temporal_shape": {
            "status": "AVAILABLE",
            "coverage_ratio": 0.85,
            "mean_positive_score": 0.72,
            "delta_mean_score": 0.08,
        },
        "topology_shape": {
            "status": "AVAILABLE",
            "relation_type": "SERVICE_DEPENDENCY",
            "affected_alarm_count": 2,
            "mapped_alarm_count": 2,
            "mapping_coverage": 1.0,
            "eligible_proximity_pairs": 4,
        },
        "operation_pattern": {
            "operation": operation,
            "removed_alarm_count": 1 if operation == "REMOVE_MEMBER" else 0,
            "split_partition_count": 2 if operation == "SPLIT_CHAIN" else 0,
            "relative_size_ratio": 0.8,
        },
    }
    return compute_case_fingerprint_payload(blocks)


async def seed_demo_review_data(
    repository: SnapshotRepository,
    *,
    group_count: int = 36,
) -> DemoSeedSummary:
    """Append missing synthetic demo groups through the normal repository API.

    Existing demo sessions are left untouched.  A pre-existing ID outside the
    expected immutable bundle will therefore surface as the repository's
    conflict rather than being silently overwritten.
    """
    _ensure_not_production()
    if group_count < 4:
        raise ValueError("group_count must be at least 4 so the demo covers each scenario")

    created_groups = existing_groups = created_exposures = created_feedbacks = created_cases = 0
    base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)

    for ordinal in range(1, group_count + 1):
        review_id = f"{DEMO_PREFIX}r{ordinal:03d}{DEMO_VERSION}"
        existing = await repository.get_review_session(review_id)
        if existing is not None:
            existing_groups += 1
            continue

        review_time = base_time + timedelta(hours=ordinal * 6)
        scenario = DEMO_SCENARIOS[(ordinal - 1) % len(DEMO_SCENARIOS)]
        session, exposures, feedbacks = generate_synthetic_review_group(
            review_id=review_id,
            chain_id=f"{DEMO_PREFIX}c{ordinal:03d}{DEMO_VERSION}",
            lineage_component_id=f"{DEMO_PREFIX}l{ordinal:03d}{DEMO_VERSION}",
            review_time=review_time.isoformat(),
            feedback_time=(review_time + timedelta(minutes=3)).isoformat(),
            scenario=scenario,
            truth_tier=TruthTier.TEST_FIXTURE,
            reviewer_subject="demo:synthetic-fixture",
        )
        session = replace(
            session,
            job_id=f"{DEMO_PREFIX}j{ordinal:03d}{DEMO_VERSION}",
            snapshot_id=f"{DEMO_PREFIX}s{ordinal:03d}{DEMO_VERSION}",
            source_kind="SYNTHETIC_TEST",
            review_domain=DEMO_DOMAIN,
            snapshot_observed_at=review_time,
            job_completed_at=review_time,
        )
        case_payloads: dict[str, tuple[dict[str, object], str]] = {}
        hydrated_exposures = []
        for exposure in exposures:
            payload, fingerprint_hash = _case_payload(exposure.operation, ordinal)
            case_payloads[exposure.candidate_id] = (payload, fingerprint_hash)
            hydrated_exposures.append(
                replace(
                    exposure,
                    case_context={
                        **dict(exposure.case_context or {}),
                        # Frozen with the exposure by the server.  The retrieval path
                        # can reuse it after a restart without inventing unavailable
                        # temporal/topology observations.
                        "case_blocks": payload["blocks"],
                    },
                )
            )
        exposures = hydrated_exposures
        await repository.persist_review_bundle(session, exposures)

        for feedback in feedbacks:
            persisted_feedback = replace(
                feedback,
                truth_tier=TruthTier.TEST_FIXTURE,
                reviewer_subject="demo:synthetic-fixture",
                reviewer_role="DEMO_FIXTURE",
                domain_scope=(DEMO_DOMAIN,),
                reviewer_domain_scope=(DEMO_DOMAIN,),
                reason_policy_version="demo-synthetic-v1",
                reason_codes=("DEMO_SYNTHETIC_FIXTURE",),
                created_at=review_time + timedelta(minutes=3),
            )
            exposure = next(exp for exp in exposures if exp.candidate_id == persisted_feedback.candidate_id)
            payload, fingerprint_hash = case_payloads[exposure.candidate_id]
            review_case = ReviewCase(
                case_id=f"{DEMO_PREFIX}case_{ordinal:03d}_{exposure.original_rank}{DEMO_VERSION}",
                review_id=session.review_id,
                feedback_id=persisted_feedback.feedback_id,
                candidate_id=persisted_feedback.candidate_id,
                case_time=persisted_feedback.created_at,
                lineage_component_id=session.lineage_component_id or "LINEAGE_UNAVAILABLE",
                operation_pattern=exposure.operation,
                fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
                fingerprint_payload=payload,
                fingerprint_hash=fingerprint_hash,
                case_domain=DEMO_DOMAIN,
                domain_scope=(DEMO_DOMAIN,),
                decision=persisted_feedback.decision,
                truth_tier=TruthTier.TEST_FIXTURE,
                created_at=persisted_feedback.created_at,
            )
            await repository.append_review_feedback(persisted_feedback, review_case=review_case)
            created_feedbacks += 1
            created_cases += 1

        created_groups += 1
        created_exposures += len(exposures)

    return DemoSeedSummary(
        requested_groups=group_count,
        created_groups=created_groups,
        existing_groups=existing_groups,
        created_exposures=created_exposures,
        created_feedbacks=created_feedbacks,
        created_cases=created_cases,
    )


async def _seed_from_url(database_url: str, group_count: int) -> DemoSeedSummary:
    _ensure_not_production()
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        return await seed_demo_review_data(SnapshotRepository(sessions), group_count=group_count)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Append synthetic-only review evidence for make dev-demo")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--groups", type=int, default=36)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    try:
        summary = asyncio.run(_seed_from_url(args.database_url, args.groups))
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print("DEMO DATA ONLY — SYNTHETIC_TEST / TEST_FIXTURE — NOT FOR PRODUCTION")
    print(
        "Seed summary: "
        f"created_groups={summary.created_groups}, existing_groups={summary.existing_groups}, "
        f"created_exposures={summary.created_exposures}, created_feedbacks={summary.created_feedbacks}, "
        f"created_cases={summary.created_cases}"
    )


if __name__ == "__main__":
    main()

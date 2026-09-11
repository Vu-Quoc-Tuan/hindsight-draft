"""Training materializer for real and synthetic review learning data.

Normalizes raw exposures and feedback into grouped ranking datasets:
  qid = review_id
  row = one candidate
  X = immutable candidate features (cf-features-v1)
  y = explicit reviewer relevance (review-label-v1)
  group_weight = truth-tier-derived weight

Strict safety filtering:
  - Exclude unreviewed candidates from labels (never treat unreviewed as negative)
  - Exclude retracted or superseded feedback (only latest active feedback before cutoff)
  - Exclude future feedback (cutoff enforcement: created_at < cutoff)
  - Enforce candidate eligibility: reject hard-gate-ineligible candidates
  - Reject groups with duplicate candidate IDs
  - Prevent same-lineage leakage (lineage holdout constraint)
  - Exclude groups without valid preference gradient (min(y) == max(y))
  - Support both string and timezone-aware datetime timestamps
  - Re-materialize features dynamically when feature_payload is not persisted
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from .contracts import (
    CandidateExposure,
    FeedbackStatus,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
    canonical_fingerprint,
)
from .features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    features_to_vector,
    materialize_candidate_features,
)
from .labels import (
    LABEL_POLICY_VERSION,
    resolve_candidate_relevance,
    resolve_group_weight,
)


@dataclass(frozen=True)
class GroupedRankingDataset:
    """Matrix container for grouped ranking (compatible with XGBRanker)."""

    qids: list[str]
    X: list[list[float]]
    y: list[int]
    group_sizes: list[int]
    group_weights: list[float]
    candidate_ids: list[str]
    review_ids: list[str]
    group_truth_tiers: list[list[str]] = field(default_factory=list)
    lineages: list[str] = field(default_factory=list)
    review_times: list[str] = field(default_factory=list)
    source_kinds: list[str] = field(default_factory=list)
    feature_names: tuple[str, ...] = FEATURE_NAMES

    @property
    def num_candidates(self) -> int:
        return len(self.y)

    @property
    def num_groups(self) -> int:
        return len(self.group_sizes)


@dataclass(frozen=True)
class ExcludedGroup:
    """Diagnostic record of why a review group was excluded from the training corpus."""

    review_id: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RankingCorpus:
    """Complete versioned training, validation, and test corpus with holdouts."""

    corpus_fingerprint: str
    feature_schema_version: str
    label_policy_version: str
    cutoff: str
    train: GroupedRankingDataset
    val: GroupedRankingDataset
    test: GroupedRankingDataset
    excluded_groups: list[ExcludedGroup] = field(default_factory=list)


def _parse_iso(dt_val: Any) -> datetime.datetime:
    """Safely parse timezone-aware datetime or ISO string."""
    if isinstance(dt_val, datetime.datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=datetime.timezone.utc)
        return dt_val
    clean = str(dt_val).replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _build_dataset_from_groups(
    groups: Sequence[dict[str, Any]],
) -> GroupedRankingDataset:
    qids: list[str] = []
    X: list[list[float]] = []
    y: list[int] = []
    group_sizes: list[int] = []
    group_weights: list[float] = []
    candidate_ids: list[str] = []
    review_ids: list[str] = []
    group_truth_tiers: list[list[str]] = []
    lineages: list[str] = []
    review_times: list[str] = []
    source_kinds: list[str] = []

    for group in groups:
        rid = group["review_id"]
        cands = group["candidates"]
        weight = group["group_weight"]

        review_ids.append(rid)
        group_sizes.append(len(cands))
        group_weights.append(weight)
        group_truth_tiers.append(group.get("truth_tiers", []))
        lineages.append(group.get("lineage_component_id", ""))
        rt = group.get("review_time", "")
        review_times.append(rt.isoformat() if hasattr(rt, "isoformat") else str(rt))
        source_kinds.append(group.get("source_kind", ""))

        for cand in cands:
            qids.append(rid)
            candidate_ids.append(cand["candidate_id"])
            X.append(cand["features"])
            y.append(cand["relevance"])

    return GroupedRankingDataset(
        qids=qids,
        X=X,
        y=y,
        group_sizes=group_sizes,
        group_weights=group_weights,
        candidate_ids=candidate_ids,
        review_ids=review_ids,
        group_truth_tiers=group_truth_tiers,
        lineages=lineages,
        review_times=review_times,
        source_kinds=source_kinds,
        feature_names=FEATURE_NAMES,
    )


def materialize_training_corpus(
    *,
    sessions: Sequence[ReviewSession],
    exposures: Sequence[CandidateExposure],
    feedbacks: Sequence[ReviewFeedback],
    cutoff: str | datetime.datetime,
    val_ratio: float = 0.2,
    test_ratio: float = 0.2,
    protected_mode: bool = False,
    strict_temporal_holdout: bool = False,
) -> RankingCorpus:
    """Materialize a leakage-safe grouped ranking corpus with temporal and lineage holdout."""
    cutoff_dt = _parse_iso(cutoff)
    cutoff_str = cutoff_dt.isoformat()

    # 1. Filter out feedbacks after cutoff or inactive
    active_feedbacks: dict[tuple[str, str | None], ReviewFeedback] = {}
    none_acceptable_reviews: set[str] = set()
    manual_correction_feedbacks: dict[str, ReviewFeedback] = {}

    for fb in feedbacks:
        if not fb.created_at:
            continue
        fb_time = _parse_iso(fb.created_at)
        if fb_time >= cutoff_dt:
            continue
        if fb.status is not FeedbackStatus.ACTIVE:
            continue

        if fb.decision is ReviewDecision.NONE_ACCEPTABLE:
            none_acceptable_reviews.add(fb.review_id)
            continue
        if fb.decision is ReviewDecision.MANUAL_CORRECTION:
            manual_correction_feedbacks[fb.review_id] = fb
            continue

        key = (fb.review_id, fb.candidate_id)
        # If multiple active feedbacks exist, keep the latest
        if key in active_feedbacks:
            existing_time = _parse_iso(active_feedbacks[key].created_at)
            if fb_time > existing_time:
                active_feedbacks[key] = fb
        else:
            active_feedbacks[key] = fb

    # 2. Group exposures by review_id
    exposures_by_review: dict[str, list[CandidateExposure]] = {}
    for exp in exposures:
        exposures_by_review.setdefault(exp.review_id, []).append(exp)

    # 3. Process sessions
    valid_groups: list[dict[str, Any]] = []
    excluded_groups: list[ExcludedGroup] = []

    for session in sessions:
        if not session.review_time:
            continue
        session_time = _parse_iso(session.review_time)
        if session_time >= cutoff_dt:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="SESSION_AFTER_CUTOFF",
                    details={"session_time": str(session.review_time), "cutoff": cutoff_str},
                )
            )
            continue

        # Enforce lineage component presence: fallback to chain:id or unverified lineage is invalid for protected corpus
        lin = session.lineage_component_id
        if not lin or lin in {"LINEAGE_UNAVAILABLE", "UNAVAILABLE"}:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="LINEAGE_UNAVAILABLE",
                    details={"chain_id": session.chain_id},
                )
            )
            continue
        if protected_mode and (
            lin.startswith("fallback_lineage:")
            or lin.startswith("fallback:")
            or lin.startswith("unverified_")
        ):
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="UNVERIFIED_LINEAGE_FALLBACK",
                    details={"chain_id": session.chain_id, "lineage": lin},
                )
            )
            continue

        exps = exposures_by_review.get(session.review_id, [])
        if not exps:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="NO_CANDIDATE_EXPOSURES",
                )
            )
            continue

        # Check duplicate candidate IDs in group
        seen_cand_ids: set[str] = set()
        has_duplicate = False
        for exp in exps:
            if exp.candidate_id in seen_cand_ids:
                has_duplicate = True
                break
            seen_cand_ids.add(exp.candidate_id)
        if has_duplicate:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="DUPLICATE_CANDIDATE_ID",
                )
            )
            continue

        # Check feature schema version across candidate exposures: fail-closed
        has_schema_mismatch = False
        for exp in exps:
            s_ver = getattr(exp, "feature_schema_version", None)
            if protected_mode:
                if not s_ver or s_ver != FEATURE_SCHEMA_VERSION:
                    has_schema_mismatch = True
                    break
            else:
                if s_ver and s_ver != FEATURE_SCHEMA_VERSION:
                    has_schema_mismatch = True
                    break
        if has_schema_mismatch:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="FEATURE_SCHEMA_VERSION_MISMATCH",
                )
            )
            continue

        # Extract, fingerprint-verify, and validate exact 43 features for all exposures
        has_fp_mismatch = False
        has_schema_error = False
        has_invalid_val = False
        exp_feat_dicts: dict[str, dict[str, float]] = {}

        for exp in exps:
            feat_payload = exp.feature_payload
            if protected_mode:
                if not exp.feature_fingerprint or not exp.feature_fingerprint.strip():
                    has_fp_mismatch = True
                    break
                has_precomputed = isinstance(feat_payload, dict) and (
                    ("features" in feat_payload and isinstance(feat_payload["features"], dict))
                    or any(k in feat_payload for k in ("op__remove", "delta__weak_member_count"))
                )
                if not has_precomputed:
                    has_schema_error = True
                    break

            feat_dict: dict[str, float] | None = None
            if isinstance(feat_payload, dict) and "features" in feat_payload and isinstance(feat_payload["features"], dict):
                feat_dict = feat_payload["features"]
            elif isinstance(feat_payload, dict) and any(k in feat_payload for k in ("op__remove", "delta__weak_member_count")):
                feat_dict = feat_payload
            else:
                det_ctx = dict(exp.deterministic_context or {})
                if isinstance(feat_payload, dict):
                    if "exact_metrics" in feat_payload and isinstance(feat_payload["exact_metrics"], dict):
                        for k, v in feat_payload["exact_metrics"].items():
                            if k not in det_ctx:
                                det_ctx[k] = v
                feat_dict = materialize_candidate_features(
                    operation=exp.operation,
                    deterministic_context=det_ctx,
                    temporal_context=exp.temporal_context,
                    case_context=exp.case_context,
                    hard_gate_status=exp.hard_gate_status,
                    pareto_state=exp.pareto_state,
                    source_kind=session.source_kind,
                )

            # Check fingerprint against feat_dict, feat_payload, or features_to_vector
            if exp.feature_fingerprint and exp.feature_payload:
                calc_fp_dict = canonical_fingerprint(feat_dict)
                calc_fp_payload = canonical_fingerprint(feat_payload) if feat_payload else ""
                if exp.feature_fingerprint != calc_fp_dict and exp.feature_fingerprint != calc_fp_payload:
                    has_fp_mismatch = True
                    break

            # If deterministic_context was provided alongside pre-computed features, verify context was not tampered
            if (
                isinstance(feat_payload, dict)
                and "features" in feat_payload
                and exp.deterministic_context
                and ("metric_deltas" in exp.deterministic_context or "before_metrics" in exp.deterministic_context)
            ):
                remat = materialize_candidate_features(
                    operation=exp.operation,
                    deterministic_context=exp.deterministic_context,
                    temporal_context=exp.temporal_context,
                    case_context=exp.case_context,
                    hard_gate_status=exp.hard_gate_status,
                    pareto_state=exp.pareto_state,
                    source_kind=session.source_kind,
                )
                if remat != feat_dict:
                    has_fp_mismatch = True
                    break

            # Check exact feature key set: exactly 43 keys matching FEATURE_NAMES
            if set(feat_dict.keys()) != set(FEATURE_NAMES):
                has_schema_error = True
                break

            # Check all values finite (no NaN, Inf)
            for v in feat_dict.values():
                if not isinstance(v, (int, float)) or not math.isfinite(v):
                    has_invalid_val = True
                    break
            if has_invalid_val:
                break

            exp_feat_dicts[exp.candidate_id] = feat_dict

        if has_schema_error:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="FEATURE_SCHEMA_VERSION_MISMATCH",
                )
            )
            continue

        if has_invalid_val:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="INVALID_FEATURE_VALUE",
                )
            )
            continue

        if has_fp_mismatch:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="FEATURE_FINGERPRINT_MISMATCH",
                )
            )
            continue

        is_none_acceptable = session.review_id in none_acceptable_reviews
        manual_fb = manual_correction_feedbacks.get(session.review_id)
        matching_manual_cand_id: str | None = None
        if manual_fb is not None:
            mc = manual_fb.manual_correction
            if mc is not None:
                for exp in exps:
                    exp_delta = exp.deterministic_context.get("partition_delta") or exp.deterministic_context.get("delta")
                    if exp.operation == mc.operation and exp_delta == mc.partition_delta:
                        matching_manual_cand_id = exp.candidate_id
                        break
            elif manual_fb.candidate_id:
                matching_manual_cand_id = manual_fb.candidate_id

        group_candidates: list[dict[str, Any]] = []
        group_truth_tiers: list[TruthTier] = []

        # Sort exposures by original_rank ascending so candidates maintain deterministic order
        sorted_exps = sorted(exps, key=lambda e: e.original_rank)

        for exp in sorted_exps:
            # Enforce candidate eligibility: must pass hard gates
            hg_status = str(exp.hard_gate_status).upper()
            det_elig = str(exp.deterministic_eligibility).upper()
            if hg_status != "PASSED" or det_elig in {"HARD_GATE_REJECTED", "INELIGIBLE", "FALSE"}:
                continue

            fb = active_feedbacks.get((session.review_id, exp.candidate_id))

            relevance: int | None = None
            truth_tier = TruthTier.PO_ASSERTED

            if is_none_acceptable and fb is None:
                # Group-level NONE_ACCEPTABLE: candidates without explicit approval are 0
                relevance = 0
            elif manual_fb is not None:
                if matching_manual_cand_id and exp.candidate_id == matching_manual_cand_id:
                    relevance = resolve_candidate_relevance(ReviewDecision.APPROVE, manual_fb.truth_tier)
                    truth_tier = manual_fb.truth_tier
                else:
                    relevance = 0
                    truth_tier = manual_fb.truth_tier
            elif fb is not None:
                relevance = resolve_candidate_relevance(fb.decision, fb.truth_tier)
                truth_tier = fb.truth_tier
            else:
                # Unreviewed candidate: must NOT be assigned negative label
                relevance = None

            if relevance is not None:
                feat_dict = exp_feat_dicts.get(exp.candidate_id) or {}
                feat_vec = features_to_vector(feat_dict)
                group_candidates.append(
                    {
                        "candidate_id": exp.candidate_id,
                        "candidate_fingerprint": exp.candidate_fingerprint,
                        "original_rank": exp.original_rank,
                        "relevance": relevance,
                        "features": feat_vec,
                        "operation": exp.operation,
                    }
                )
                group_truth_tiers.append(truth_tier)

        # Candidate count check
        if len(group_candidates) < 2:
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason="INSUFFICIENT_LABELED_CANDIDATES",
                    details={"labeled_count": len(group_candidates)},
                )
            )
            continue

        # Preference gradient check: min(y) != max(y)
        rels = [c["relevance"] for c in group_candidates]
        if min(rels) == max(rels):
            if is_none_acceptable:
                reason_str = "NONE_ACCEPTABLE_NO_POSITIVE"
            elif manual_fb is not None and not matching_manual_cand_id:
                reason_str = "MANUAL_CORRECTION_NO_PROPOSED_MATCH"
            else:
                reason_str = "NO_PREFERENCE_GRADIENT"
            excluded_groups.append(
                ExcludedGroup(
                    review_id=session.review_id,
                    reason=reason_str,
                    details={"relevances": rels},
                )
            )
            continue

        group_weight = resolve_group_weight(group_truth_tiers)

        valid_groups.append(
            {
                "review_id": session.review_id,
                "review_time": session_time,
                "lineage_component_id": lin,
                "source_kind": session.source_kind,
                "candidates": group_candidates,
                "group_weight": group_weight,
                "truth_tiers": [t.value for t in group_truth_tiers],
            }
        )

    # 4. Sort chronologically by review_time
    valid_groups.sort(key=lambda g: g["review_time"])

    # 5. Strict Lineage-First Chronological Splitting
    total_valid = len(valid_groups)
    if total_valid == 0:
        empty = _build_dataset_from_groups([])
        return RankingCorpus(
            corpus_fingerprint=canonical_fingerprint([]),
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            label_policy_version=LABEL_POLICY_VERSION,
            cutoff=cutoff_str,
            train=empty,
            val=empty,
            test=empty,
            excluded_groups=excluded_groups,
        )

    # Group valid review groups by lineage_component_id
    lineage_groups: dict[str, list[dict[str, Any]]] = {}
    for g in valid_groups:
        lin_id = g["lineage_component_id"]
        lineage_groups.setdefault(lin_id, []).append(g)

    # Sort groups within each lineage chronologically
    for lin_id, grps in lineage_groups.items():
        grps.sort(key=lambda item: _parse_iso(item["review_time"]))

    # Sort unique lineages chronologically by their earliest review_time
    sorted_lineages = sorted(
        lineage_groups.keys(),
        key=lambda l_id: (_parse_iso(lineage_groups[l_id][0]["review_time"]), l_id),
    )

    num_lineages = len(sorted_lineages)
    final_train: list[dict[str, Any]] = []
    final_val: list[dict[str, Any]] = []
    final_test: list[dict[str, Any]] = []

    if total_valid < 5 or num_lineages < 3:
        if num_lineages == 1:
            final_train = list(valid_groups)
        elif num_lineages == 2:
            final_train = list(lineage_groups[sorted_lineages[0]])
            final_val = list(lineage_groups[sorted_lineages[1]])
        else:
            final_train = list(valid_groups)
    elif strict_temporal_holdout:
        target_test = max(1, int(total_valid * test_ratio))
        target_val = max(1, int(total_valid * val_ratio))
        target_train = total_valid - target_val - target_test

        t_train_val = _parse_iso(valid_groups[target_train - 1]["review_time"])
        t_val_test = _parse_iso(valid_groups[target_train + target_val - 1]["review_time"])

        for l_id in sorted_lineages:
            grps = lineage_groups[l_id]
            min_t = min(_parse_iso(g["review_time"]) for g in grps)
            max_t = max(_parse_iso(g["review_time"]) for g in grps)

            straddles_train_val = (min_t <= t_train_val < max_t)
            straddles_val_test = (min_t <= t_val_test < max_t)

            if straddles_train_val or straddles_val_test:
                for g in grps:
                    excluded_groups.append(
                        ExcludedGroup(
                            review_id=g["review_id"],
                            reason="STRADDLING_LINEAGE_EMBARGO",
                            details={
                                "lineage_component_id": l_id,
                                "min_time": min_t.isoformat(),
                                "max_time": max_t.isoformat(),
                                "train_val_cutoff": t_train_val.isoformat(),
                                "val_test_cutoff": t_val_test.isoformat(),
                            },
                        )
                    )
            elif max_t <= t_train_val:
                final_train.extend(grps)
            elif min_t > t_train_val and max_t <= t_val_test:
                final_val.extend(grps)
            elif min_t > t_val_test:
                final_test.extend(grps)
            else:
                final_train.extend(grps)
    else:
        target_test = max(1, int(total_valid * test_ratio))
        target_val = max(1, int(total_valid * val_ratio))
        target_train = total_valid - target_val - target_test

        train_lins: set[str] = set()
        val_lins: set[str] = set()
        test_lins: set[str] = set()

        idx = 0
        # Accumulate lineages into train, reserving at least 1 lineage for val and 1 for test
        while idx < num_lineages and (len(train_lins) < num_lineages - 2 and len(final_train) < target_train):
            l_id = sorted_lineages[idx]
            final_train.extend(lineage_groups[l_id])
            train_lins.add(l_id)
            idx += 1

        # Accumulate lineages into val, reserving at least 1 lineage for test
        while idx < num_lineages and (len(train_lins) + len(val_lins) < num_lineages - 1 and len(final_val) < target_val):
            l_id = sorted_lineages[idx]
            final_val.extend(lineage_groups[l_id])
            val_lins.add(l_id)
            idx += 1

        # Remaining lineages all go to test
        while idx < num_lineages:
            l_id = sorted_lineages[idx]
            final_test.extend(lineage_groups[l_id])
            test_lins.add(l_id)
            idx += 1

    train_ds = _build_dataset_from_groups(final_train)
    val_ds = _build_dataset_from_groups(final_val)
    test_ds = _build_dataset_from_groups(final_test)

    # Exhaustive Corpus fingerprint: MUST hash X, y, candidate IDs, weights, lineages, review times, source kinds, truth tiers, and split assignments
    fingerprint_meta = {
        "cutoff": cutoff_str,
        "feature_schema": FEATURE_SCHEMA_VERSION,
        "label_policy": LABEL_POLICY_VERSION,
        "train": {
            "qids": train_ds.qids,
            "cand_ids": train_ds.candidate_ids,
            "y": train_ds.y,
            "weights": train_ds.group_weights,
            "lineages": train_ds.lineages,
            "review_times": train_ds.review_times,
            "source_kinds": train_ds.source_kinds,
            "truth_tiers": train_ds.group_truth_tiers,
            "X": train_ds.X,
        },
        "val": {
            "qids": val_ds.qids,
            "cand_ids": val_ds.candidate_ids,
            "y": val_ds.y,
            "weights": val_ds.group_weights,
            "lineages": val_ds.lineages,
            "review_times": val_ds.review_times,
            "source_kinds": val_ds.source_kinds,
            "truth_tiers": val_ds.group_truth_tiers,
            "X": val_ds.X,
        },
        "test": {
            "qids": test_ds.qids,
            "cand_ids": test_ds.candidate_ids,
            "y": test_ds.y,
            "weights": test_ds.group_weights,
            "lineages": test_ds.lineages,
            "review_times": test_ds.review_times,
            "source_kinds": test_ds.source_kinds,
            "truth_tiers": test_ds.group_truth_tiers,
            "X": test_ds.X,
        },
        "excluded_groups": [(eg.review_id, eg.reason) for eg in excluded_groups],
    }
    corpus_fp = canonical_fingerprint(fingerprint_meta)

    return RankingCorpus(
        corpus_fingerprint=corpus_fp,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        label_policy_version=LABEL_POLICY_VERSION,
        cutoff=cutoff_str,
        train=train_ds,
        val=val_ds,
        test=test_ds,
        excluded_groups=excluded_groups,
    )


def materialize_training_corpus_from_repository_groups(
    groups: Sequence[dict[str, Any]],
    cutoff: str | datetime.datetime,
    val_ratio: float = 0.2,
    test_ratio: float = 0.2,
    protected_mode: bool = False,
    strict_temporal_holdout: bool = False,
) -> RankingCorpus:
    """Adapter reading directly from repository.training_review_groups_before()."""
    from dataclasses import replace

    sessions: list[ReviewSession] = []
    exposures: list[CandidateExposure] = []
    feedbacks: list[ReviewFeedback] = []

    for g in groups:
        sess = g.get("review_session")
        if sess:
            sessions.append(sess)
        exps = g.get("candidate_exposures") or []
        exposures.extend(exps)
        fbs = g.get("active_feedbacks") or []
        corrections = g.get("manual_corrections") or []
        mc_map = {mc.feedback_id: mc for mc in corrections}
        for fb in fbs:
            if fb.manual_correction is None and fb.feedback_id in mc_map:
                feedbacks.append(replace(fb, manual_correction=mc_map[fb.feedback_id]))
            else:
                feedbacks.append(fb)

    return materialize_training_corpus(
        sessions=sessions,
        exposures=exposures,
        feedbacks=feedbacks,
        cutoff=cutoff,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
        protected_mode=protected_mode,
        strict_temporal_holdout=strict_temporal_holdout,
    )

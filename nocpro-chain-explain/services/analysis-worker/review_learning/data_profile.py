"""Data profile and audit reporter for the review-learning training corpus.

Computes exhaustive metrics over materialized ranking groups:
  - review group count (train, val, test, excluded)
  - candidate count
  - positive vs negative distribution
  - operation coverage (REMOVE, SPLIT, MOVE, MERGE)
  - source kind mix
  - truth tier distribution
  - time span
  - lineage overlap check (train vs val/test)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from .contracts import ReviewSession
from .materializer import RankingCorpus


@dataclass(frozen=True)
class SplitProfile:
    group_count: int
    candidate_count: int
    positive_count: int
    negative_count: int
    relevance_distribution: dict[int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_count": self.group_count,
            "candidate_count": self.candidate_count,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "relevance_distribution": self.relevance_distribution,
        }


@dataclass(frozen=True)
class DataProfileReport:
    corpus_fingerprint: str
    cutoff: str
    feature_schema_version: str
    label_policy_version: str
    splits: dict[str, SplitProfile]
    total_groups: int
    total_candidates: int
    total_positives: int
    total_negatives: int
    operation_coverage: dict[str, int]
    source_kind_distribution: dict[str, int]
    truth_tier_distribution: dict[str, int]
    time_span: dict[str, str]
    lineage_overlap_detected: bool
    lineage_overlap_count: int
    excluded_groups_count: int
    excluded_reasons: dict[str, int]
    temporal_inversion_detected: bool = False
    excluded_straddling_lineages: list[str] = field(default_factory=list)

    @property
    def data_profile_fingerprint(self) -> str:
        from .contracts import canonical_fingerprint
        return canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_fingerprint": self.corpus_fingerprint,
            "cutoff": self.cutoff,
            "feature_schema_version": self.feature_schema_version,
            "label_policy_version": self.label_policy_version,
            "splits": {k: v.to_dict() for k, v in self.splits.items()},
            "total_groups": self.total_groups,
            "total_candidates": self.total_candidates,
            "total_positives": self.total_positives,
            "total_negatives": self.total_negatives,
            "operation_coverage": self.operation_coverage,
            "source_kind_distribution": self.source_kind_distribution,
            "truth_tier_distribution": self.truth_tier_distribution,
            "time_span": self.time_span,
            "lineage_overlap_detected": self.lineage_overlap_detected,
            "lineage_overlap_count": self.lineage_overlap_count,
            "excluded_groups_count": self.excluded_groups_count,
            "excluded_reasons": self.excluded_reasons,
            "excluded_straddling_lineages": self.excluded_straddling_lineages,
            "temporal_inversion_detected": self.temporal_inversion_detected,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Training Corpus Data Profile",
            f"- **Corpus Fingerprint:** `{self.corpus_fingerprint[:16]}...`",
            f"- **Cutoff:** `{self.cutoff}`",
            f"- **Feature Schema:** `{self.feature_schema_version}`",
            f"- **Label Policy:** `{self.label_policy_version}`",
            f"- **Lineage Overlap Detected:** `{'YES (CRITICAL LEAKAGE)' if self.lineage_overlap_detected else 'NO (VERIFIED)'}`",
            f"- **Temporal Inversion Detected:** `{'YES (CRITICAL INVERSION)' if self.temporal_inversion_detected else 'NO (VERIFIED)'}`",
        ]
        val_sp = self.splits.get("val")
        test_sp = self.splits.get("test")
        if (val_sp and val_sp.group_count == 0) or (test_sp and test_sp.group_count == 0):
            lines.append("")
            lines.append("> [!WARNING]")
            lines.append("> Split starvation detected! Val or Test split contains 0 review groups.")

        lines.extend([
            "",
            "## Summary by Split",
            "| Split | Review Groups | Candidates | Positive (y >= 1) | Negative (y == 0) |",
            "|---|---|---|---|---|",
        ])
        for name, sp in self.splits.items():
            lines.append(
                f"| {name.capitalize()} | {sp.group_count} | {sp.candidate_count} | {sp.positive_count} | {sp.negative_count} |"
            )
        lines.extend([
            f"| **Total** | **{self.total_groups}** | **{self.total_candidates}** | **{self.total_positives}** | **{self.total_negatives}** |",
            "",
            "## Operation Coverage",
            "| Operation | Candidates |",
            "|---|---|",
        ])
        for op, count in self.operation_coverage.items():
            lines.append(f"| {op} | {count} |")

        lines.extend([
            "",
            "## Truth Tier Distribution",
            "| Truth Tier | Count |",
            "|---|---|",
        ])
        for tier, count in self.truth_tier_distribution.items():
            lines.append(f"| {tier} | {count} |")

        lines.extend([
            "",
            "## Excluded Groups",
            f"Total Excluded: {self.excluded_groups_count}",
        ])
        for reason, count in self.excluded_reasons.items():
            lines.append(f"- `{reason}`: {count}")

        return "\n".join(lines)


def build_data_profile(
    corpus: RankingCorpus,
    raw_sessions: Sequence[ReviewSession] | None = None,
) -> DataProfileReport:
    """Analyze a materialized RankingCorpus and produce an audit data profile."""
    session_map = {s.review_id: s for s in (raw_sessions or [])}

    splits_data: dict[str, SplitProfile] = {}
    total_pos = 0
    total_neg = 0
    op_counts: dict[str, int] = {
        "REMOVE_MEMBER": 0,
        "SPLIT_CHAIN": 0,
        "MOVE_MEMBER": 0,
        "MERGE_CHAINS": 0,
    }
    source_kinds: dict[str, int] = {}
    truth_tiers: dict[str, int] = {}

    split_lineages: dict[str, set[str]] = {"train": set(), "val": set(), "test": set()}

    time_values: list[str] = []

    for name, ds in [("train", corpus.train), ("val", corpus.val), ("test", corpus.test)]:
        pos = sum(1 for label in ds.y if label >= 1)
        neg = sum(1 for label in ds.y if label == 0)
        total_pos += pos
        total_neg += neg

        dist: dict[int, int] = {}
        for l in ds.y:
            dist[l] = dist.get(l, 0) + 1

        splits_data[name] = SplitProfile(
            group_count=ds.num_groups,
            candidate_count=ds.num_candidates,
            positive_count=pos,
            negative_count=neg,
            relevance_distribution=dist,
        )

        # Count truth tiers from group_truth_tiers or sessions
        for tier_list in getattr(ds, "group_truth_tiers", []):
            for t in tier_list:
                t_str = t.value if hasattr(t, "value") else str(t)
                truth_tiers[t_str] = truth_tiers.get(t_str, 0) + 1

        for idx, rid in enumerate(ds.review_ids):
            lin = ds.lineages[idx] if idx < len(ds.lineages) and ds.lineages[idx] else None
            sk = ds.source_kinds[idx] if idx < len(ds.source_kinds) and ds.source_kinds[idx] else None
            rt = ds.review_times[idx] if idx < len(ds.review_times) and ds.review_times[idx] else None

            sess = session_map.get(rid)
            if sess:
                lin = lin or sess.lineage_component_id or sess.chain_id
                sk = sk or sess.source_kind
                rt = rt or sess.review_time
                if not getattr(ds, "group_truth_tiers", None) and getattr(sess, "truth_tier", None):
                    t_str = sess.truth_tier.value if hasattr(sess.truth_tier, "value") else str(sess.truth_tier)
                    truth_tiers[t_str] = truth_tiers.get(t_str, 0) + 1

            if lin:
                split_lineages[name].add(lin)
            if sk:
                source_kinds[sk] = source_kinds.get(sk, 0) + 1
            if rt:
                time_values.append(str(rt))

        # Count operations based on one-hot features
        # In FEATURE_NAMES: 0: op__remove, 1: op__split, 2: op__move, 3: op__merge
        for row in ds.X:
            if len(row) >= 4:
                if row[0] == 1.0:
                    op_counts["REMOVE_MEMBER"] += 1
                elif row[1] == 1.0:
                    op_counts["SPLIT_CHAIN"] += 1
                elif row[2] == 1.0:
                    op_counts["MOVE_MEMBER"] += 1
                elif row[3] == 1.0:
                    op_counts["MERGE_CHAINS"] += 1

    # Check lineage leakage
    train_lineages = split_lineages["train"]
    val_lineages = split_lineages["val"]
    test_lineages = split_lineages["test"]

    overlap_train_val = train_lineages.intersection(val_lineages)
    overlap_train_test = train_lineages.intersection(test_lineages)
    overlap_val_test = val_lineages.intersection(test_lineages)

    total_overlap = len(overlap_train_val) + len(overlap_train_test) + len(overlap_val_test)
    leakage_detected = total_overlap > 0

    # Check temporal inversion using UTC datetimes to prevent lexical comparison anomalies
    def _parse_to_utc_datetime(t: Any) -> datetime | None:
        if isinstance(t, datetime):
            return t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)
        if isinstance(t, str) and t.strip():
            try:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        return None

    train_dts = [dt for t in corpus.train.review_times if (dt := _parse_to_utc_datetime(t)) is not None]
    val_dts = [dt for t in corpus.val.review_times if (dt := _parse_to_utc_datetime(t)) is not None]
    test_dts = [dt for t in corpus.test.review_times if (dt := _parse_to_utc_datetime(t)) is not None]

    temporal_inversion = False
    if train_dts and val_dts and max(train_dts) > min(val_dts):
        temporal_inversion = True
    if train_dts and test_dts and max(train_dts) > min(test_dts):
        temporal_inversion = True
    if val_dts and test_dts and max(val_dts) > min(test_dts):
        temporal_inversion = True

    # Excluded reasons
    excluded_reasons: dict[str, int] = {}
    excluded_straddlers: list[str] = []
    for exc in corpus.excluded_groups:
        excluded_reasons[exc.reason] = excluded_reasons.get(exc.reason, 0) + 1
        if exc.reason == "STRADDLING_LINEAGE" and exc.details and "lineage" in exc.details:
            excluded_straddlers.append(str(exc.details["lineage"]))

    time_span = {
        "min": min(time_values) if time_values else "N/A",
        "max": max(time_values) if time_values else "N/A",
    }

    return DataProfileReport(
        corpus_fingerprint=corpus.corpus_fingerprint,
        cutoff=corpus.cutoff,
        feature_schema_version=corpus.feature_schema_version,
        label_policy_version=corpus.label_policy_version,
        splits=splits_data,
        total_groups=corpus.train.num_groups + corpus.val.num_groups + corpus.test.num_groups,
        total_candidates=corpus.train.num_candidates + corpus.val.num_candidates + corpus.test.num_candidates,
        total_positives=total_pos,
        total_negatives=total_neg,
        operation_coverage=op_counts,
        source_kind_distribution=source_kinds,
        truth_tier_distribution=truth_tiers,
        time_span=time_span,
        lineage_overlap_detected=leakage_detected,
        lineage_overlap_count=total_overlap,
        excluded_groups_count=len(corpus.excluded_groups),
        excluded_reasons=excluded_reasons,
        temporal_inversion_detected=temporal_inversion,
        excluded_straddling_lineages=sorted(set(excluded_straddlers)),
    )

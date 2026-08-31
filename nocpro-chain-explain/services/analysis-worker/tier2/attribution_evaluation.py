"""Exact deterministic deletion evaluation for ADR-0031 attribution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import sqrt

from configuration import (
    ATTRIBUTION_RANDOMIZATION_ALGORITHM,
    AttributionEvaluationConfig,
)
from groups import IndexedChainStatistics

from .evidence_attribution import (
    AttributionMode,
    AttributionStatus,
    EvidenceCoverageAttributionResult,
    ExactAttributionSupport,
    build_exact_attribution_support,
)


RANDOMIZATION_ALGORITHM = ATTRIBUTION_RANDOMIZATION_ALGORITHM
_UINT64_MASK = (1 << 64) - 1
_UINT64_RANGE = 1 << 64


class AttributionEvaluationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AttributionEvaluationMode(str, Enum):
    EXACT = "EXACT"
    UNAVAILABLE = "UNAVAILABLE"


class AttributionEvaluationReason(str, Enum):
    ATTRIBUTION_UNAVAILABLE = "ATTRIBUTION_UNAVAILABLE"
    ATTRIBUTION_EVALUATION_CONFIG_INCOMPLETE = (
        "ATTRIBUTION_EVALUATION_CONFIG_INCOMPLETE"
    )
    NO_ELIGIBLE_GROUPS = "NO_ELIGIBLE_GROUPS"


@dataclass(frozen=True)
class DeletionCurve:
    ordering: tuple[str, ...] = ()
    coverage_curve: tuple[float, ...] = ()
    auc: float | None = None


@dataclass(frozen=True)
class RandomDeletionBaseline:
    algorithm: str = RANDOMIZATION_ALGORITHM
    seed: int | None = None
    repetitions: int | None = None
    repetitions_executed: int = 0
    mean_curve: tuple[float, ...] = ()
    std_curve: tuple[float, ...] = ()
    mean_auc: float | None = None
    std_auc: float | None = None


@dataclass(frozen=True)
class AttributionDeletionEvaluationResult:
    status: AttributionEvaluationStatus
    mode: AttributionEvaluationMode
    reason: AttributionEvaluationReason | None
    group_count: int
    primary: DeletionCurve = DeletionCurve()
    reverse: DeletionCurve = DeletionCurve()
    random: RandomDeletionBaseline = RandomDeletionBaseline()
    delta_vs_random_auc: float | None = None
    delta_vs_reverse_auc: float | None = None


class _SplitMix64:
    """Unsigned SplitMix64 stream used only by the frozen shuffle contract."""

    def __init__(self, seed: int) -> None:
        self._state = seed & _UINT64_MASK

    def next_uint64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _UINT64_MASK
        value = self._state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _UINT64_MASK
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _UINT64_MASK
        return (value ^ (value >> 31)) & _UINT64_MASK

    def bounded(self, bound: int) -> int:
        if bound <= 0:
            raise ValueError("bound must be positive")
        limit = _UINT64_RANGE - (_UINT64_RANGE % bound)
        while True:
            value = self.next_uint64()
            if value < limit:
                return value % bound


def _shuffle_in_place(values: list[str], rng: _SplitMix64) -> None:
    for index in range(len(values) - 1, 0, -1):
        selected = rng.bounded(index + 1)
        values[index], values[selected] = values[selected], values[index]


def _curve(
    support: ExactAttributionSupport,
    ordering: tuple[str, ...],
) -> DeletionCurve:
    group_index = {group.group_id: index for index, group in enumerate(support.groups)}
    group_count = len(ordering)
    removal_step_by_group = [0] * group_count
    for position, group_id in enumerate(ordering):
        removal_step_by_group[group_index[group_id]] = position + 1

    # A pair stays covered until the last group in its support signature is
    # deleted. Process each signature once, then derive every curve point from
    # the exact removal histogram instead of rescanning all signatures G times.
    removed_pair_counts = [0] * (group_count + 1)
    covered = 0
    for signature, pair_count in support.signature_pair_counts:
        covered += pair_count
        last_removal_step = 0
        remaining_groups = signature
        while remaining_groups:
            group_bit = remaining_groups & -remaining_groups
            index = group_bit.bit_length() - 1
            last_removal_step = max(
                last_removal_step,
                removal_step_by_group[index],
            )
            remaining_groups ^= group_bit
        removed_pair_counts[last_removal_step] += pair_count

    values = [covered / support.total_pair_count]
    for removal_step in range(1, group_count + 1):
        covered -= removed_pair_counts[removal_step]
        values.append(covered / support.total_pair_count)
    auc = sum(
        (values[index] + values[index + 1]) / 2
        for index in range(group_count)
    ) / group_count
    return DeletionCurve(ordering=ordering, coverage_curve=tuple(values), auc=auc)


def _population_mean_std(values: tuple[float, ...]) -> tuple[float, float]:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, sqrt(variance)


def _valid_config(config: AttributionEvaluationConfig | None) -> tuple[int, int] | None:
    if config is None or config.randomization_algorithm != RANDOMIZATION_ALGORITHM:
        return None
    seed = config.random_seed.value
    repetitions = config.random_repetitions.value
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or seed < 0
        or isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or repetitions <= 0
    ):
        return None
    return seed, repetitions


def evaluate_attribution_deletion(
    attribution: EvidenceCoverageAttributionResult,
    members: tuple[str, ...] | list[str],
    statistics: IndexedChainStatistics | None,
    *,
    config: AttributionEvaluationConfig | None,
    exact_support: ExactAttributionSupport | None = None,
) -> AttributionDeletionEvaluationResult:
    """Evaluate exact remaining-group union coverage after deterministic deletion."""
    group_count = len(attribution.contributions)
    if (
        attribution.status is not AttributionStatus.AVAILABLE
        or attribution.mode is not AttributionMode.EXACT
    ):
        return AttributionDeletionEvaluationResult(
            status=AttributionEvaluationStatus.UNAVAILABLE,
            mode=AttributionEvaluationMode.UNAVAILABLE,
            reason=AttributionEvaluationReason.ATTRIBUTION_UNAVAILABLE,
            group_count=group_count,
        )
    if group_count == 0:
        return AttributionDeletionEvaluationResult(
            status=AttributionEvaluationStatus.NOT_APPLICABLE,
            mode=AttributionEvaluationMode.UNAVAILABLE,
            reason=AttributionEvaluationReason.NO_ELIGIBLE_GROUPS,
            group_count=0,
            random=RandomDeletionBaseline(repetitions_executed=0),
        )
    configured = _valid_config(config)
    if configured is None:
        return AttributionDeletionEvaluationResult(
            status=AttributionEvaluationStatus.UNAVAILABLE,
            mode=AttributionEvaluationMode.UNAVAILABLE,
            reason=(
                AttributionEvaluationReason.ATTRIBUTION_EVALUATION_CONFIG_INCOMPLETE
            ),
            group_count=group_count,
        )
    support = exact_support or build_exact_attribution_support(members, statistics)
    expected_group_ids = {item.group_id for item in attribution.contributions}
    support_group_ids = (
        {group.group_id for group in support.groups} if support is not None else set()
    )
    if (
        support is None
        or support.members != tuple(members)
        or support.total_pair_count != attribution.total_pair_count
        or support_group_ids != expected_group_ids
    ):
        return AttributionDeletionEvaluationResult(
            status=AttributionEvaluationStatus.UNAVAILABLE,
            mode=AttributionEvaluationMode.UNAVAILABLE,
            reason=AttributionEvaluationReason.ATTRIBUTION_UNAVAILABLE,
            group_count=group_count,
        )

    primary_order = tuple(
        item.group_id
        for item in sorted(
            attribution.contributions,
            key=lambda item: (-item.attribution, item.group_id),
        )
    )
    reverse_order = tuple(
        item.group_id
        for item in sorted(
            attribution.contributions,
            key=lambda item: (item.attribution, item.group_id),
        )
    )
    primary = _curve(support, primary_order)
    reverse = _curve(support, reverse_order)

    seed, repetitions = configured
    rng = _SplitMix64(seed)
    stable_group_ids = sorted(item.group_id for item in attribution.contributions)
    random_curves: list[DeletionCurve] = []
    for _ in range(repetitions):
        ordering = list(stable_group_ids)
        _shuffle_in_place(ordering, rng)
        random_curves.append(_curve(support, tuple(ordering)))
    curve_points = tuple(
        _population_mean_std(
            tuple(curve.coverage_curve[index] for curve in random_curves)
        )
        for index in range(group_count + 1)
    )
    mean_auc, std_auc = _population_mean_std(
        tuple(curve.auc for curve in random_curves if curve.auc is not None)
    )
    random = RandomDeletionBaseline(
        algorithm=RANDOMIZATION_ALGORITHM,
        seed=seed,
        repetitions=repetitions,
        repetitions_executed=repetitions,
        mean_curve=tuple(point[0] for point in curve_points),
        std_curve=tuple(point[1] for point in curve_points),
        mean_auc=mean_auc,
        std_auc=std_auc,
    )
    return AttributionDeletionEvaluationResult(
        status=AttributionEvaluationStatus.AVAILABLE,
        mode=AttributionEvaluationMode.EXACT,
        reason=None,
        group_count=group_count,
        primary=primary,
        reverse=reverse,
        random=random,
        delta_vs_random_auc=mean_auc - primary.auc,
        delta_vs_reverse_auc=reverse.auc - primary.auc,
    )

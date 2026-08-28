"""Balanced conductance and calibration (§6, ADR-0019).

    Phi(S) = sum_{i in S, j not in S} w*_audit(i,j) / min(Vol(S), Vol(complement S))
    constraint: min(|S|, |C\\S|) >= max(rho * |C|, 5)

Small-chain policy: ``|C| < 10`` makes the two-sided >=5 constraint infeasible,
so the balanced over-merge test is **skipped**, not scored as "no cut found =
stable". Those are different claims.

Calibration falls back through three levels rather than ever reporting a
threshold with false precision from a handful of samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .graph import AuditGraph

#: Balance ratio for the two-sided size constraint.
DEFAULT_RHO = 0.2
#: Absolute floor for each side, independent of chain size.
MIN_SIDE_SIZE = 5
#: Chains smaller than this cannot satisfy the balance constraint at all.
SMALL_CHAIN_THRESHOLD = 10

#: Minimum samples per calibration bin before it is trusted.
DEFAULT_N_MIN = 20
DEFAULT_QUANTILE = 0.05


class AuditVerdict(str, Enum):
    #: A genuinely low-conductance balanced cut exists.
    CANDIDATE_SPLIT = "CANDIDATE_SPLIT"
    #: No balanced cut with low enough conductance was found.
    NO_LOW_CONDUCTANCE_CUT = "NO_LOW_CONDUCTANCE_CUT"
    #: The chain is too small for the balance constraint to be meaningful.
    SKIPPED_SMALL_CHAIN = "SKIPPED_SMALL_CHAIN"


@dataclass(frozen=True)
class ConductanceResult:
    """Conductance of one candidate cut."""

    label: str
    size_s: int
    size_complement: int
    phi: float | None
    #: False when the two-sided size constraint could not be met.
    feasible: bool
    reason: str | None = None


def min_side_requirement(chain_size: int, *, rho: float = DEFAULT_RHO) -> int:
    return max(int(rho * chain_size), MIN_SIDE_SIZE)


def is_chain_too_small_for_audit(chain_size: int) -> bool:
    """``|C| < 10``: skip, do not silently score as stable."""
    return chain_size < SMALL_CHAIN_THRESHOLD


def conductance(graph: AuditGraph, members: frozenset[str], *, label: str) -> ConductanceResult:
    """Compute balanced conductance for one candidate cut ``S``.

    Feasibility (the two-sided size constraint) is checked by the caller via
    :func:`score_candidates`, which is where the small-chain skip is applied
    consistently across every candidate.
    """
    all_members = set(graph.members)
    complement = all_members - members

    if not members or not complement:
        return ConductanceResult(
            label=label,
            size_s=len(members),
            size_complement=len(complement),
            phi=None,
            feasible=False,
            reason="candidate is the whole chain or empty",
        )

    cut_weight = 0.0
    for node in members:
        for neighbour, weight in graph.neighbours(node).items():
            if neighbour in complement:
                cut_weight += weight

    volume_s = graph.volume(members)
    volume_complement = graph.volume(complement)
    denominator = min(volume_s, volume_complement)

    if denominator <= 0:
        # No audit-eligible edges touch one side: conductance is undefined,
        # not zero. Zero would read as a perfect cut.
        return ConductanceResult(
            label=label,
            size_s=len(members),
            size_complement=len(complement),
            phi=None,
            feasible=True,
            reason="no audit-eligible edge volume on at least one side",
        )

    return ConductanceResult(
        label=label,
        size_s=len(members),
        size_complement=len(complement),
        phi=cut_weight / denominator,
        feasible=True,
    )


@dataclass(frozen=True)
class CalibrationBin:
    """One historical calibration bucket."""

    size_bin: str
    density_bin: str | None
    coverage_bin: str | None
    samples: tuple[float, ...]

    @property
    def key(self) -> tuple[str, str | None, str | None]:
        return (self.size_bin, self.density_bin, self.coverage_bin)


@dataclass(frozen=True)
class CalibratedThreshold:
    """``epsilon_Phi`` plus how it was derived."""

    epsilon: float
    #: FULL: size x density x coverage. COARSE: size only. GLOBAL: weak baseline.
    level: str
    sample_count: int
    low_confidence: bool


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("cannot take a quantile of an empty sample")
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def calibrate_epsilon(
    full_bin: list[float] | None,
    coarse_bin: list[float] | None,
    *,
    n_min: int = DEFAULT_N_MIN,
    quantile: float = DEFAULT_QUANTILE,
    global_weak_baseline: float = 0.3,
) -> CalibratedThreshold:
    """Three-level fallback so a handful of samples never produces false precision.

    A few hundred historical chains split three ways yields 3-5 samples per bin,
    where a P5 estimate is meaningless.
    """
    if full_bin is not None and len(full_bin) >= n_min:
        return CalibratedThreshold(
            epsilon=_quantile(full_bin, quantile),
            level="FULL",
            sample_count=len(full_bin),
            low_confidence=False,
        )
    if coarse_bin is not None and len(coarse_bin) >= n_min:
        return CalibratedThreshold(
            epsilon=_quantile(coarse_bin, quantile),
            level="COARSE",
            sample_count=len(coarse_bin),
            low_confidence=False,
        )
    # Explicitly low confidence: this is a weak baseline, not a calibrated cut.
    return CalibratedThreshold(
        epsilon=global_weak_baseline,
        level="GLOBAL",
        sample_count=len(coarse_bin or full_bin or []),
        low_confidence=True,
    )

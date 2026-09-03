"""Membership role classification (§4B, ADR-0028).

Gate (prerequisite for any verdict):

    AvailabilityCoverage >= c_min
    AND >= 2 DISTINCT COMPUTABLE ROLE_ELIGIBLE DERIVATION GROUPS
    AND non-supporting groups must be NEUTRAL, not UNAVAILABLE

Then:

    CORE  <=> support >= S_min AND rank in top quantile
              AND Representativeness >= r_min AND Margin_common > 0
    WEAK  <=> gate passes AND support in bottom band AND Margin_common <= 0
    PERIPHERAL = remaining (gate passes)
    gate fails => INSUFFICIENT DATA

``|C| < 8``: drop the quantile and use the absolute floors only.

The gate exists so that missing evidence yields INSUFFICIENT DATA. Calling that
WEAK would turn absence of information into a negative finding.
"""

from __future__ import annotations

from dataclasses import dataclass

from graybox.singleton import MembershipVerdict

from .fit import MembershipSupport

#: Minimum distinct computable role-eligible derivation groups.
MIN_COMPUTABLE_GROUPS = 2

#: Chains smaller than this skip quantile logic and use floors only.
SMALL_CHAIN_THRESHOLD = 8


@dataclass(frozen=True)
class RoleThresholds:
    """Versioned thresholds (§4A threshold policy, ADR-0025)."""

    config_version: str
    #: Absolute CORE floor, guards against "best of a bad chain".
    s_min: float = 0.6
    #: Upper bound of the WEAK band.
    s_weak: float = 0.3
    #: Minimum availability coverage.
    c_min: float = 0.5
    #: Minimum representativeness for CORE.
    r_min: float = 0.5
    #: Top quantile for CORE on chains at or above SMALL_CHAIN_THRESHOLD.
    core_quantile: float = 0.5
    #: Frozen minimum number of distinct computable role groups.
    min_computable_groups: int = MIN_COMPUTABLE_GROUPS
    #: Chains below this size use absolute floors without quantiles.
    small_chain_threshold: int = SMALL_CHAIN_THRESHOLD


@dataclass(frozen=True)
class GateResult:
    """Outcome of the prerequisite gate, with the reason retained."""

    passed: bool
    availability_coverage: float
    computable_groups: int
    reason: str | None = None


def availability_coverage(support: MembershipSupport) -> float:
    """Computable role-eligible groups divided by possible role-eligible groups."""
    role_groups = [gf for gf in support.group_fits if gf.role_eligible]
    if not role_groups:
        return 0.0
    computable = sum(1 for gf in role_groups if not gf.is_unavailable)
    return computable / len(role_groups)


def evaluate_gate(
    support: MembershipSupport, thresholds: RoleThresholds
) -> GateResult:
    """Evaluate the membership gate."""
    coverage = availability_coverage(support)
    computable = support.computable_group_count

    if computable < thresholds.min_computable_groups:
        return GateResult(
            passed=False,
            availability_coverage=coverage,
            computable_groups=computable,
            reason=(
                f"only {computable} computable role-eligible derivation group(s); "
                f"need >= {thresholds.min_computable_groups}"
            ),
        )
    if coverage < thresholds.c_min:
        return GateResult(
            passed=False,
            availability_coverage=coverage,
            computable_groups=computable,
            reason=(
                f"availability coverage {coverage:.2f} below c_min="
                f"{thresholds.c_min}"
            ),
        )
    return GateResult(
        passed=True, availability_coverage=coverage, computable_groups=computable
    )


@dataclass(frozen=True)
class MembershipRole:
    """Membership verdict for one alarm, with its inputs retained."""

    alarm_id: str
    verdict: MembershipVerdict
    support: float | None
    gate: GateResult
    representativeness: float | None = None
    margin_common: float | None = None
    config_version: str | None = None
    reason: str | None = None

    @property
    def is_core(self) -> bool:
        return self.verdict is MembershipVerdict.CORE

    @property
    def is_weak(self) -> bool:
        return self.verdict is MembershipVerdict.WEAK


def classify_membership(
    support: MembershipSupport,
    *,
    thresholds: RoleThresholds,
    chain_size: int,
    support_rank_quantile: float | None = None,
    representativeness: float | None = None,
    margin_common: float | None = None,
) -> MembershipRole:
    """Classify one member.

    ``support_rank_quantile`` is the member's position within the chain (0 = best).
    It is ignored for chains below :data:`SMALL_CHAIN_THRESHOLD`.
    """
    gate = evaluate_gate(support, thresholds)
    if not gate.passed:
        # Absence of evidence, not weak evidence.
        return MembershipRole(
            alarm_id=support.alarm_id,
            verdict=MembershipVerdict.INSUFFICIENT_DATA,
            support=support.support,
            gate=gate,
            representativeness=representativeness,
            margin_common=margin_common,
            config_version=thresholds.config_version,
            reason=gate.reason,
        )

    value = support.support
    if value is None:
        return MembershipRole(
            alarm_id=support.alarm_id,
            verdict=MembershipVerdict.INSUFFICIENT_DATA,
            support=None,
            gate=gate,
            config_version=thresholds.config_version,
            reason="no computable MembershipSupport",
        )

    small_chain = chain_size < thresholds.small_chain_threshold
    in_top_quantile = (
        True
        if small_chain or support_rank_quantile is None
        else support_rank_quantile <= thresholds.core_quantile
    )

    core_conditions = (
        value >= thresholds.s_min
        and in_top_quantile
        and representativeness is not None
        and representativeness >= thresholds.r_min
        and margin_common is not None
        and margin_common > 0
    )
    if core_conditions:
        return MembershipRole(
            alarm_id=support.alarm_id,
            verdict=MembershipVerdict.CORE,
            support=value,
            gate=gate,
            representativeness=representativeness,
            margin_common=margin_common,
            config_version=thresholds.config_version,
            reason=f"support {value:.2f} >= S_min {thresholds.s_min}",
        )

    # WEAK needs both a low band and a non-positive contrastive margin, so a
    # merely middling member is PERIPHERAL rather than WEAK.
    if (
        value <= thresholds.s_weak
        and margin_common is not None
        and margin_common <= 0
    ):
        return MembershipRole(
            alarm_id=support.alarm_id,
            verdict=MembershipVerdict.WEAK,
            support=value,
            gate=gate,
            representativeness=representativeness,
            margin_common=margin_common,
            config_version=thresholds.config_version,
            reason=(
                f"support {value:.2f} <= S_weak {thresholds.s_weak} with "
                "non-positive contrastive margin"
            ),
        )

    return MembershipRole(
        alarm_id=support.alarm_id,
        verdict=MembershipVerdict.PERIPHERAL,
        support=value,
        gate=gate,
        representativeness=representativeness,
        margin_common=margin_common,
        config_version=thresholds.config_version,
        reason="gate passed; neither CORE nor WEAK conditions met",
    )

"""Chain fit and membership support (§4B).

    D_k(x,C)  = { y in C\\{x} : availability_k(x,y) = 1 }
    Fit_k(x,C) = |{ y in D_k : s_k+(x,y) >= theta_k }| / |D_k|
    |D_k| = 0  => Fit_k = ⊥;  all Fit_k = ⊥ => INSUFFICIENT DATA

    Fit_g(x,C) = max{ Fit_k(x,C) : k in g, Fit_k != ⊥ }
    G_role(x,C) = groups with role_eligible=true and Fit_g != ⊥
    MembershipSupport(x,C) = mean over G_role of Fit_g(x,C)

The vector ``[Fit_g]`` is always retained; the scalar exists only for
ranking/role. Aggregation happens per derivation group, so three views of one
field cannot inflate support.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.provenance import (
    DerivationGroup,
    NormalizedChannel,
    build_derivation_groups,
)

from .statistics import ChannelStatistics

#: Sentinel for ⊥ (unavailable) fit.
UNAVAILABLE_FIT: None = None


@dataclass(frozen=True)
class ChannelFit:
    """``Fit_k(x,C)`` for one channel."""

    channel_id: str
    derivation_tag: str
    #: ``None`` means ⊥: no available partner to compare against.
    fit: float | None
    #: ``|D_k(x,C)|``
    domain_size: int
    supporting: int

    @property
    def is_unavailable(self) -> bool:
        return self.fit is None


def channel_fit(
    alarm_id: str,
    channel_id: str,
    statistics: ChannelStatistics,
) -> ChannelFit:
    """Compute ``Fit_k(x,C)`` from exact statistics.

    Reads accumulated counts rather than a pair list, so the result cannot depend
    on how much pair detail was retained for display.
    """
    counts = statistics.counts_for(alarm_id, channel_id)
    meta = statistics.channel_meta.get(channel_id)
    derivation_tag = counts.derivation_tag or (
        meta.derivation_tag if meta else channel_id
    )
    # counts.fit is None exactly when |D_k| = 0, i.e. ⊥.
    return ChannelFit(
        channel_id=channel_id,
        derivation_tag=derivation_tag,
        fit=counts.fit,
        domain_size=counts.domain_size,
        supporting=counts.supporting,
    )


@dataclass(frozen=True)
class GroupFit:
    """``Fit_g(x,C)`` for one effective derivation group."""

    group: DerivationGroup
    fit: float | None
    channel_fits: tuple[ChannelFit, ...]

    @property
    def derivation_tag(self) -> str:
        return self.group.key.derivation_tag

    @property
    def is_unavailable(self) -> bool:
        return self.fit is None

    @property
    def role_eligible(self) -> bool:
        return self.group.role_eligible


def _representative_channels(
    statistics: ChannelStatistics,
) -> dict[str, NormalizedChannel]:
    """One representative NormalizedChannel per channel id, for grouping.

    Grouping needs provenance and eligibility, which are channel properties, not
    per-pair properties. Availability is resolved separately from ``Fit_k``.
    """
    return {
        channel_id: NormalizedChannel(
            channel_id=value.channel_id,
            derivation_tag=value.derivation_tag,
            provenance_class=value.provenance_class,
            provenance_subtype=value.provenance_subtype,
        )
        for channel_id, value in statistics.channel_meta.items()
    }


def group_fits(alarm_id: str, statistics: ChannelStatistics) -> list[GroupFit]:
    """Compute ``Fit_g`` for every effective derivation group."""
    representatives = _representative_channels(statistics)
    groups = build_derivation_groups(list(representatives.values()))

    results: list[GroupFit] = []
    for group in groups:
        fits = tuple(
            channel_fit(alarm_id, channel.channel_id, statistics)
            for channel in group.channels
        )
        available = [f.fit for f in fits if f.fit is not None]
        # Fit_g = max over channels whose Fit_k is not ⊥.
        results.append(
            GroupFit(
                group=group,
                fit=max(available) if available else None,
                channel_fits=fits,
            )
        )
    return results


@dataclass(frozen=True)
class MembershipSupport:
    """Scalar support plus the retained per-group vector."""

    alarm_id: str
    #: ``None`` when no role-eligible group is computable.
    support: float | None
    group_fits: tuple[GroupFit, ...]

    @property
    def role_group_fits(self) -> tuple[GroupFit, ...]:
        """``G_role(x,C)``: role-eligible groups with ``Fit_g != ⊥``."""
        return tuple(
            gf for gf in self.group_fits if gf.role_eligible and not gf.is_unavailable
        )

    @property
    def computable_group_count(self) -> int:
        return len(self.role_group_fits)

    @property
    def all_unavailable(self) -> bool:
        """Every ``Fit_k`` is ⊥ => INSUFFICIENT DATA."""
        return all(gf.is_unavailable for gf in self.group_fits)


def membership_support(
    alarm_id: str, statistics: ChannelStatistics
) -> MembershipSupport:
    """Compute ``MembershipSupport(x,C)`` as the mean ``Fit_g`` over ``G_role``.

    Derived from exact statistics, so it is independent of the pair-detail cap.
    """
    fits = tuple(group_fits(alarm_id, statistics))
    role_fits = [gf.fit for gf in fits if gf.role_eligible and gf.fit is not None]
    support = sum(role_fits) / len(role_fits) if role_fits else None
    return MembershipSupport(alarm_id=alarm_id, support=support, group_fits=fits)

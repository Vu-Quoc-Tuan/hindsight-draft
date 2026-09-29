"""Fit_g / MembershipSupport from indexed statistics (execution contract v2).

Adapts :class:`IndexedChainStatistics` into the same :class:`GroupFit` /
:class:`MembershipSupport` shapes the role classifier and Tier-1B orchestrator
already consume. The algebra is identical to ``fit.py``; only the data source
changes (indexed counts instead of a streamed pair matrix). ``Fit_g`` is the
unweighted maximum of computable channel fits in a group, and MembershipSupport
is the unweighted arithmetic mean across computable role-eligible groups. The
per-channel domain size is not used as a cross-group weight, and no sampling
uncertainty correction is applied.

This avoids modifying the existing ``fit.py`` code (which still serves as the
reference implementation for correctness checks on small chains).
"""

from __future__ import annotations

from libs.provenance import (
    NormalizedChannel,
    build_derivation_groups,
)

from .fit import ChannelFit, GroupFit, MembershipSupport
from .indexed_statistics import IndexedChainStatistics


def channel_fit_from_index(
    alarm_id: str, channel_id: str, stats: IndexedChainStatistics
) -> ChannelFit:
    """Convert an indexed Fit into the standard ChannelFit shape."""
    entry = stats.fit_of(alarm_id, channel_id)
    meta = stats.channel_meta.get(channel_id)
    derivation_tag = meta[0] if meta else channel_id
    if entry is None:
        return ChannelFit(
            channel_id=channel_id,
            derivation_tag=derivation_tag,
            fit=None,
            domain_size=0,
            supporting=0,
        )
    return ChannelFit(
        channel_id=entry.channel_id,
        derivation_tag=entry.derivation_tag,
        fit=entry.fit,
        domain_size=entry.domain_size,
        supporting=entry.supporting,
        unavailable_reason=entry.unavailable_reason,
    )


def group_fits_from_index(
    alarm_id: str, stats: IndexedChainStatistics
) -> list[GroupFit]:
    """Compute ``Fit_g`` per effective derivation group from indexed statistics."""
    representatives = [
        NormalizedChannel(
            channel_id=channel_id,
            derivation_tag=meta[0],
            provenance_class=meta[1],
            provenance_subtype=meta[2],
        )
        for channel_id, meta in stats.channel_meta.items()
    ]
    groups = build_derivation_groups(representatives)

    results: list[GroupFit] = []
    for group in groups:
        fits = tuple(
            channel_fit_from_index(alarm_id, channel.channel_id, stats)
            for channel in group.channels
        )
        available = [f.fit for f in fits if f.fit is not None]
        results.append(
            GroupFit(
                group=group,
                fit=max(available) if available else None,
                channel_fits=fits,
            )
        )
    return results


def membership_support_from_index(
    alarm_id: str, stats: IndexedChainStatistics
) -> MembershipSupport:
    """Compute ``MembershipSupport(x, C)`` from indexed statistics.

    Identical formula to ``fit.py``'s version; only the data source differs.
    """
    fits = tuple(group_fits_from_index(alarm_id, stats))
    role_fits = [gf.fit for gf in fits if gf.role_eligible and gf.fit is not None]
    # Equal-weight arithmetic mean; domain_size does not weight groups here.
    support = sum(role_fits) / len(role_fits) if role_fits else None
    return MembershipSupport(alarm_id=alarm_id, support=support, group_fits=fits)

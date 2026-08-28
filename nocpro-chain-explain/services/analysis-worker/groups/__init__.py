"""Derivation-group fit, membership support and role classification."""

from .fit import (
    ChannelFit,
    GroupFit,
    MembershipSupport,
    channel_fit,
    group_fits,
    membership_support,
)
from .statistics import (
    EXACT_STATISTICS_MAX_MEMBERS,
    ChannelCounts,
    ChannelStatistics,
    ChannelVerdict,
    pair_iterator,
    statistics_are_exact,
)
from .roles import (
    MIN_COMPUTABLE_GROUPS,
    SMALL_CHAIN_THRESHOLD,
    GateResult,
    MembershipRole,
    RoleThresholds,
    availability_coverage,
    classify_membership,
    evaluate_gate,
)

__all__ = [
    "EXACT_STATISTICS_MAX_MEMBERS",
    "MIN_COMPUTABLE_GROUPS",
    "SMALL_CHAIN_THRESHOLD",
    "ChannelCounts",
    "ChannelFit",
    "ChannelStatistics",
    "ChannelVerdict",
    "GateResult",
    "GroupFit",
    "MembershipRole",
    "MembershipSupport",
    "RoleThresholds",
    "availability_coverage",
    "channel_fit",
    "classify_membership",
    "evaluate_gate",
    "group_fits",
    "membership_support",
    "pair_iterator",
    "statistics_are_exact",
]

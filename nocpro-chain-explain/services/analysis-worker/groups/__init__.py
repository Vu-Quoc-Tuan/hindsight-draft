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
from .fit_from_index import (
    channel_fit_from_index,
    group_fits_from_index,
    membership_support_from_index,
)
from .indexed_statistics import (
    AuditGraphMode,
    ChannelFitFromIndex,
    IndexedChainStatistics,
    PairMaterializationMode,
    StatisticsMode,
)

__all__ = [
    "EXACT_STATISTICS_MAX_MEMBERS",
    "MIN_COMPUTABLE_GROUPS",
    "SMALL_CHAIN_THRESHOLD",
    "ChannelCounts",
    "ChannelFit",
    "ChannelFitFromIndex",
    "ChannelStatistics",
    "ChannelVerdict",
    "GateResult",
    "GroupFit",
    "MembershipRole",
    "MembershipSupport",
    "IndexedChainStatistics",
    "StatisticsMode",
    "AuditGraphMode",
    "PairMaterializationMode",
    "RoleThresholds",
    "availability_coverage",
    "channel_fit",
    "channel_fit_from_index",
    "classify_membership",
    "evaluate_gate",
    "group_fits",
    "group_fits_from_index",
    "membership_support",
    "membership_support_from_index",
    "pair_iterator",
    "statistics_are_exact",
]

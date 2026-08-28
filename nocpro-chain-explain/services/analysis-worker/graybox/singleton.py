"""Singleton chain path (``|C| = 1``) — first-class, MVP (§14, ADR-0029).

Singletons are the common case, not an edge case: 2,072 of 2,824 observed chains
(73.37%) in the real export have exactly one member.

Rules:
- chain overview, System Fact, descriptors and evolution still run;
- pair WHY, pair-based Fit, connector analysis and over-merge return
  ``NOT_APPLICABLE`` — not ``ERROR``, and not a false ``stable`` verdict;
- a singleton is never labeled ``WEAK`` just because pair evidence is
  unavailable. ``UNAVAILABLE`` is not evidence of weakness.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from libs.contracts.loader import IngestedChain, IngestedPackage


class OperationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    #: Structurally meaningless for this chain, e.g. pair WHY on one member.
    NOT_APPLICABLE = "NOT_APPLICABLE"
    #: Meaningful but the required input is missing (⊥).
    UNAVAILABLE = "UNAVAILABLE"


class MembershipVerdict(str, Enum):
    """Membership roles (§4B) plus the two non-verdict outcomes."""

    CORE = "CORE"
    PERIPHERAL = "PERIPHERAL"
    #: Genuinely weak: computable evidence exists and is poor.
    WEAK = "WEAK"
    #: Not enough computable groups to judge; explicitly not WEAK.
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    #: Structurally meaningless, e.g. membership role of a singleton.
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: Operations that require at least two members to mean anything.
PAIR_DEPENDENT_OPERATIONS = frozenset(
    {
        "PAIR_WHY",
        "PAIR_FIT",
        "CONNECTOR_ANALYSIS",
        "OVER_MERGE",
        "STRUCTURAL_AUDIT",
        "CONTRASTIVE_PAIR",
    }
)

#: Operations that remain available for a singleton chain.
SINGLETON_SUPPORTED_OPERATIONS = frozenset(
    {
        "CHAIN_OVERVIEW",
        "SYSTEM_FACT",
        "DESCRIPTOR",
        "EVOLUTION",
    }
)


@dataclass(frozen=True)
class OperationResult:
    """Outcome of one analysis operation, with an explicit reason."""

    operation: str
    status: OperationStatus
    reason: str | None = None

    @property
    def is_error(self) -> bool:
        """NOT_APPLICABLE and UNAVAILABLE are valid answers, never errors."""
        return False


def operation_status(operation: str, chain: IngestedChain) -> OperationResult:
    """Resolve whether an operation applies to this chain."""
    if chain.is_singleton and operation in PAIR_DEPENDENT_OPERATIONS:
        return OperationResult(
            operation=operation,
            status=OperationStatus.NOT_APPLICABLE,
            reason=(
                f"chain has {chain.member_count} member; {operation} requires at "
                "least two members"
            ),
        )
    return OperationResult(operation=operation, status=OperationStatus.AVAILABLE)


def singleton_membership_verdict(chain: IngestedChain) -> MembershipVerdict:
    """Membership verdict for a singleton.

    Returns ``NOT_APPLICABLE``: with one member there is no pair evidence to
    compute Fit from, and absence of pair evidence must not become ``WEAK``.
    """
    if not chain.is_singleton:
        raise ValueError("singleton_membership_verdict applies to |C|=1 only")
    return MembershipVerdict.NOT_APPLICABLE


@dataclass(frozen=True)
class SingletonReport:
    """What a singleton chain can and cannot answer."""

    chain_id: str
    member_count: int
    supported: tuple[OperationResult, ...]
    not_applicable: tuple[OperationResult, ...]
    membership_verdict: MembershipVerdict

    @property
    def is_weak(self) -> bool:
        return self.membership_verdict is MembershipVerdict.WEAK


def build_singleton_report(
    package: IngestedPackage, chain_id: str
) -> SingletonReport:
    """Build the singleton report for a one-member chain."""
    chain = package.chains.get(chain_id)
    if chain is None:
        raise KeyError(f"unknown chain_id {chain_id!r}")
    if not chain.is_singleton:
        raise ValueError(
            f"chain {chain_id!r} has {chain.member_count} members; not a singleton"
        )

    supported = tuple(
        operation_status(op, chain) for op in sorted(SINGLETON_SUPPORTED_OPERATIONS)
    )
    not_applicable = tuple(
        operation_status(op, chain) for op in sorted(PAIR_DEPENDENT_OPERATIONS)
    )
    return SingletonReport(
        chain_id=chain_id,
        member_count=chain.member_count,
        supported=supported,
        not_applicable=not_applicable,
        membership_verdict=singleton_membership_verdict(chain),
    )

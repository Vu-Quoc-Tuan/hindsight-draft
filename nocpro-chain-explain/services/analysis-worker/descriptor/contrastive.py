"""Contrastive analysis: ``U_local``, CONTRASTIVE descriptors, ``Margin_common`` (§4B/§5).

    U_local(C)              top-k competing chains from the blocking index
    G_common(x; C, C')      groups available for both chains
    Margin_common(x)        mean over G_common of [Fit_g(x,C) - Fit_g(x,C')]
    |G_common| < g_min      => INSUFFICIENT CONTRASTIVE EVIDENCE

``U_local`` has a hard definition: the top-k competing chains from the blocking
index, which is exactly the contrastive candidate set. It is not "everything
else", because a global complement would make local precision meaningless.

``Margin_common`` is only averaged over groups computable in **both** chains.
Comparing a group available in C against ⊥ in C' would compare evidence with
absence.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedPackage

from groups.fit import GroupFit
from groups.statistics import ChannelStatistics

#: Default number of competing chains in U_local.
DEFAULT_U_LOCAL_K = 5

#: Minimum shared groups for a contrastive verdict.
DEFAULT_G_MIN = 2


@dataclass(frozen=True)
class BlockingCandidate:
    """One competing chain plus the blocking key that surfaced it."""

    chain_id: str
    shared_key: str
    shared_value: str
    overlap: int


def blocking_candidates(
    package: IngestedPackage,
    chain_id: str,
    *,
    blocking_fields: tuple[str, ...] = ("location_code", "network_class_name", "alarm_name"),
    k: int = DEFAULT_U_LOCAL_K,
) -> list[BlockingCandidate]:
    """Find the top-k competing chains via a blocking index.

    Competing means "shares a blocking attribute value with the target chain",
    which keeps ``U_local`` to plausible alternatives rather than the whole
    snapshot.
    """
    from descriptor.predicates import read_field

    members = set(package.members_of(chain_id))
    if not members:
        return []

    target_values: dict[str, set[str]] = {}
    for alarm_id in members:
        alarm = package.alarms[alarm_id]
        for field in blocking_fields:
            value = read_field(alarm, field)
            if value:
                target_values.setdefault(field, set()).add(value)

    scores: dict[tuple[str, str, str], int] = {}
    for other_chain, other_members in package.memberships.items():
        if other_chain == chain_id:
            continue
        for alarm_id in other_members:
            alarm = package.alarms.get(alarm_id)
            if alarm is None:
                continue
            for field in blocking_fields:
                value = read_field(alarm, field)
                if value and value in target_values.get(field, ()):
                    key = (other_chain, field, value)
                    scores[key] = scores.get(key, 0) + 1

    best: dict[str, BlockingCandidate] = {}
    for (other_chain, field, value), overlap in scores.items():
        current = best.get(other_chain)
        if current is None or overlap > current.overlap:
            best[other_chain] = BlockingCandidate(
                chain_id=other_chain,
                shared_key=field,
                shared_value=value,
                overlap=overlap,
            )

    ranked = sorted(
        best.values(), key=lambda c: (-c.overlap, c.chain_id)
    )
    return ranked[:k]


def local_universe_bitmap(
    package: IngestedPackage,
    candidates: list[BlockingCandidate],
    index,
    *,
    target_chain_id: str,
) -> int:
    """``U_local`` bitmap: the target chain plus its top-k competitors.

    The target chain **must** be included. ``Precision_local`` asks "of the
    alarms in this local neighbourhood that match the rule, how many are in C?",
    so excluding C would force TP to zero and make every local precision 0.0.

    This is the frame that makes "globally common, locally discriminative" work:
    DIAMETER has 8% global precision but 95% precision inside ``U_local``.
    """
    from descriptor.predicates import bitmap_of_members

    member_ids: set[str] = set(package.members_of(target_chain_id))
    for candidate in candidates:
        member_ids.update(package.members_of(candidate.chain_id))
    return bitmap_of_members(index, member_ids)


@dataclass(frozen=True)
class MarginResult:
    """``Margin_common(x)`` plus the evidence behind it."""

    alarm_id: str
    #: ``None`` when there is insufficient contrastive evidence.
    margin: float | None
    shared_groups: int
    compared_chain_id: str | None
    insufficient: bool
    reason: str | None = None


def _role_fits(group_fits: tuple[GroupFit, ...]) -> dict[str, float]:
    """Computable role-eligible fits, keyed by derivation tag."""
    return {
        gf.derivation_tag: gf.fit
        for gf in group_fits
        if gf.role_eligible and gf.fit is not None
    }


def margin_common(
    alarm_id: str,
    own_fits: tuple[GroupFit, ...],
    rival_fits: tuple[GroupFit, ...],
    *,
    compared_chain_id: str | None,
    g_min: int = DEFAULT_G_MIN,
) -> MarginResult:
    """Compute ``Margin_common`` over groups available in both chains."""
    own = _role_fits(own_fits)
    rival = _role_fits(rival_fits)
    shared = sorted(set(own) & set(rival))

    if len(shared) < g_min:
        return MarginResult(
            alarm_id=alarm_id,
            margin=None,
            shared_groups=len(shared),
            compared_chain_id=compared_chain_id,
            insufficient=True,
            reason=(
                f"only {len(shared)} shared computable group(s); need >= {g_min}"
            ),
        )

    differences = [own[tag] - rival[tag] for tag in shared]
    return MarginResult(
        alarm_id=alarm_id,
        margin=sum(differences) / len(differences),
        shared_groups=len(shared),
        compared_chain_id=compared_chain_id,
        insufficient=False,
    )


def hypothetical_fits(
    alarm_id: str, rival_statistics: ChannelStatistics
) -> tuple[GroupFit, ...]:
    """``Fit_g(x, C')``: how well ``x`` would fit a competing chain.

    ``rival_statistics`` must have been accumulated with ``x`` compared against
    the rival's members.
    """
    from groups.fit import group_fits

    return tuple(group_fits(alarm_id, rival_statistics))

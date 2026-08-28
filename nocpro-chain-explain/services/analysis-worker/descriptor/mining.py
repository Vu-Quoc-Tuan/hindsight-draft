"""Bounded descriptor mining (§5, P0).

Two objectives on one bitmap engine, deliberately not merged:

    IDENTITY     maximize Coverage  s.t.  Precision_global >= p_min
                 tie-break: shorter rule, then higher Precision_local
    CONTRASTIVE  maximize Coverage  s.t.  Precision_local  >= p_local  (on U_local)

A single global floor would kill the "globally common, locally discriminative"
rule that the spec calls out: DIAMETER has 8% global precision, which fails a
global floor, yet 95% precision inside ``U_local`` and is exactly the answer to
"why C1 rather than C2".

Beam search with depth 2-3 and width K. Redundancy filter: two rules whose
extents have Jaccard >= 0.9 collapse to the higher-scoring rule. Full gFIM is
explicitly out of scope for Tier-1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .metrics import DescriptorMetrics, evaluate_extent
from .predicates import Predicate, PredicateIndex

#: Beam search defaults.
DEFAULT_MAX_DEPTH = 3
DEFAULT_BEAM_WIDTH = 8
DEFAULT_TOP_K = 10

#: Precision floors.
DEFAULT_PRECISION_GLOBAL_MIN = 0.5
DEFAULT_PRECISION_LOCAL_MIN = 0.7

#: Extent Jaccard at or above this is considered redundant.
REDUNDANCY_JACCARD = 0.9


class DescriptorKind(str, Enum):
    IDENTITY = "IDENTITY"
    CONTRASTIVE = "CONTRASTIVE"


@dataclass(frozen=True)
class Descriptor:
    """One conjunctive rule plus its metrics."""

    kind: DescriptorKind
    predicates: tuple[Predicate, ...]
    extent: int
    metrics: DescriptorMetrics
    #: Precision restricted to U_local; ``None`` when no local universe was given.
    precision_local: float | None = None

    @property
    def depth(self) -> int:
        return len(self.predicates)

    @property
    def label(self) -> str:
        return " AND ".join(str(p) for p in self.predicates)

    @property
    def derivation_tags(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(p.derivation_tag for p in self.predicates))

    def matches_alarm_bit(self, position: int) -> bool:
        return bool(self.extent >> position & 1)


@dataclass
class MiningConfig:
    """Versioned mining configuration (ADR-0025)."""

    config_version: str
    max_depth: int = DEFAULT_MAX_DEPTH
    beam_width: int = DEFAULT_BEAM_WIDTH
    top_k: int = DEFAULT_TOP_K
    precision_global_min: float = DEFAULT_PRECISION_GLOBAL_MIN
    precision_local_min: float = DEFAULT_PRECISION_LOCAL_MIN
    redundancy_jaccard: float = REDUNDANCY_JACCARD


def jaccard(left: int, right: int) -> float:
    """Extent overlap."""
    union = (left | right).bit_count()
    if union == 0:
        return 0.0
    return (left & right).bit_count() / union


def filter_redundant(
    descriptors: list[Descriptor], *, threshold: float = REDUNDANCY_JACCARD
) -> list[Descriptor]:
    """Drop rules whose extent nearly duplicates a higher-scoring rule.

    Input must already be sorted best-first; the first occurrence wins.
    """
    kept: list[Descriptor] = []
    for candidate in descriptors:
        if any(jaccard(candidate.extent, k.extent) >= threshold for k in kept):
            continue
        kept.append(candidate)
    return kept


def _identity_sort_key(descriptor: Descriptor) -> tuple:
    """Maximize coverage; tie-break shorter rule, then higher local precision."""
    return (
        -descriptor.metrics.coverage,
        descriptor.depth,
        -(descriptor.precision_local or 0.0),
        -descriptor.metrics.precision,
        descriptor.label,
    )


def _contrastive_sort_key(descriptor: Descriptor) -> tuple:
    return (
        -descriptor.metrics.coverage,
        -(descriptor.precision_local or 0.0),
        descriptor.depth,
        descriptor.label,
    )


def mine_descriptors(
    index: PredicateIndex,
    target: int,
    *,
    config: MiningConfig,
    kind: DescriptorKind = DescriptorKind.IDENTITY,
    local_universe: int | None = None,
) -> list[Descriptor]:
    """Mine descriptors for ``target`` by bounded beam search.

    ``local_universe`` is the ``U_local`` bitmap. IDENTITY mining uses it only to
    report ``precision_local``; CONTRASTIVE mining constrains on it.
    """
    universe_size = index.size
    target_size = target.bit_count()
    if target_size == 0 or universe_size == 0:
        return []

    if kind is DescriptorKind.CONTRASTIVE and local_universe is None:
        raise ValueError(
            "CONTRASTIVE mining requires a local_universe (U_local); a global "
            "floor cannot express local discrimination"
        )

    def build(predicates: tuple[Predicate, ...], extent: int) -> Descriptor:
        metrics = evaluate_extent(
            extent, target, universe_size=universe_size, target_size=target_size
        )
        local_precision: float | None = None
        if local_universe is not None:
            local_extent = extent & local_universe
            local_total = local_extent.bit_count()
            if local_total:
                local_precision = (local_extent & target).bit_count() / local_total
            else:
                local_precision = 0.0
        return Descriptor(
            kind=kind,
            predicates=predicates,
            extent=extent,
            metrics=metrics,
            precision_local=local_precision,
        )

    def admissible(descriptor: Descriptor) -> bool:
        if descriptor.metrics.true_positives == 0:
            return False
        if kind is DescriptorKind.IDENTITY:
            return descriptor.metrics.precision >= config.precision_global_min
        return (descriptor.precision_local or 0.0) >= config.precision_local_min

    sort_key = (
        _identity_sort_key
        if kind is DescriptorKind.IDENTITY
        else _contrastive_sort_key
    )

    all_predicates = index.predicates()
    accepted: list[Descriptor] = []

    # Depth 1 seeds.
    beam: list[Descriptor] = []
    for predicate in all_predicates:
        extent = index.bitmap(predicate)
        if not extent & target:
            # A predicate covering no member cannot describe the chain.
            continue
        descriptor = build((predicate,), extent)
        beam.append(descriptor)
        if admissible(descriptor):
            accepted.append(descriptor)

    beam.sort(key=sort_key)
    beam = beam[: config.beam_width]

    # Deepen by conjunction.
    for _ in range(2, config.max_depth + 1):
        next_beam: list[Descriptor] = []
        seen: set[tuple[Predicate, ...]] = set()
        for base in beam:
            for predicate in all_predicates:
                if predicate in base.predicates:
                    continue
                # One field per rule: field=A AND field=B is unsatisfiable.
                if any(p.field == predicate.field for p in base.predicates):
                    continue
                predicates = tuple(sorted(
                    base.predicates + (predicate,), key=lambda p: (p.field, p.value)
                ))
                if predicates in seen:
                    continue
                seen.add(predicates)
                extent = base.extent & index.bitmap(predicate)
                if not extent & target:
                    continue
                descriptor = build(predicates, extent)
                next_beam.append(descriptor)
                if admissible(descriptor):
                    accepted.append(descriptor)
        if not next_beam:
            break
        next_beam.sort(key=sort_key)
        beam = next_beam[: config.beam_width]

    accepted.sort(key=sort_key)
    return filter_redundant(accepted, threshold=config.redundancy_jaccard)[
        : config.top_k
    ]


@dataclass
class DescriptorSet:
    """Mined descriptors for one chain."""

    chain_id: str
    identity: tuple[Descriptor, ...] = ()
    contrastive: tuple[Descriptor, ...] = ()
    config_version: str | None = None
    #: Set when no rule met the precision floor.
    identity_insufficient: bool = False

    @property
    def top_identity(self) -> Descriptor | None:
        return self.identity[0] if self.identity else None

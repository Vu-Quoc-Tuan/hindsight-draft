"""Structural audit run and the multi-evidence over-merge verdict (§6).

Over-merge is a **multi-evidence verdict**, never a single number:

    StructuralSeparation   balanced low-Phi cut exists
    CrossEvidenceAgreement  agreement across derivation groups
    DescriptorSeparation    block A/B have distinct IDENTITY patterns
    SensitivityStability    the cut survives across a threshold range

The conclusion names which channel/group drives it and says "should review",
never "NocPro is wrong" (ADR-0018, docs 11).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from descriptor import DescriptorKind, MiningConfig, PredicateIndex, mine_descriptors
from descriptor.predicates import bitmap_of_members

from .candidates import Candidate
from .conductance import (
    DEFAULT_RHO,
    MIN_SIDE_SIZE,
    SMALL_CHAIN_THRESHOLD,
    AuditVerdict,
    ConductanceResult,
    conductance,
    is_chain_too_small_for_audit,
    min_side_requirement,
)
from .graph import AuditGraph


@dataclass(frozen=True)
class ScoredCandidate:
    """One candidate cut with its conductance score."""

    candidate: Candidate
    conductance: ConductanceResult


@dataclass(frozen=True)
class StructuralAuditResult:
    """Structural audit output for one chain."""

    chain_id: str
    verdict: AuditVerdict
    best_cut: ScoredCandidate | None
    scored_candidates: tuple[ScoredCandidate, ...]
    epsilon: float | None
    reason: str


def score_candidates(
    graph: AuditGraph,
    candidates: list[Candidate],
    *,
    chain_size: int,
    rho: float = DEFAULT_RHO,
    min_side_size: int = MIN_SIDE_SIZE,
) -> list[ScoredCandidate]:
    """Score every candidate, applying the two-sided balance constraint."""
    requirement = min_side_requirement(
        chain_size, rho=rho, min_side_size=min_side_size
    )
    scored: list[ScoredCandidate] = []
    for candidate in candidates:
        result = conductance(graph, candidate.members, label=candidate.label)
        complement_size = len(graph.members) - len(candidate.members)
        if min(len(candidate.members), complement_size) < requirement:
            result = ConductanceResult(
                label=candidate.label,
                size_s=len(candidate.members),
                size_complement=complement_size,
                phi=None,
                feasible=False,
                reason=f"one side below the balance floor ({requirement})",
            )
        scored.append(ScoredCandidate(candidate=candidate, conductance=result))
    return scored


def run_structural_audit(
    chain_id: str,
    graph: AuditGraph,
    candidates: list[Candidate],
    *,
    epsilon: float,
    rho: float = DEFAULT_RHO,
    min_side_size: int = MIN_SIDE_SIZE,
    small_chain_threshold: int = SMALL_CHAIN_THRESHOLD,
) -> StructuralAuditResult:
    """Run the balanced-conductance structural audit for one chain.

    ``|C| < 10`` is skipped outright: "no cut found" and "chain too small to
    test" are different claims and must not be collapsed.
    """
    chain_size = len(graph.members)
    if is_chain_too_small_for_audit(
        chain_size, small_chain_threshold=small_chain_threshold
    ):
        return StructuralAuditResult(
            chain_id=chain_id,
            verdict=AuditVerdict.SKIPPED_SMALL_CHAIN,
            best_cut=None,
            scored_candidates=(),
            epsilon=None,
            reason=(
                f"chain has {chain_size} members; balanced over-merge test "
                f"requires >= {small_chain_threshold}"
            ),
        )

    scored = score_candidates(
        graph,
        candidates,
        chain_size=chain_size,
        rho=rho,
        min_side_size=min_side_size,
    )
    feasible = [s for s in scored if s.conductance.feasible and s.conductance.phi is not None]

    if not feasible:
        return StructuralAuditResult(
            chain_id=chain_id,
            verdict=AuditVerdict.NO_LOW_CONDUCTANCE_CUT,
            best_cut=None,
            scored_candidates=tuple(scored),
            epsilon=epsilon,
            reason="no candidate satisfied the balance constraint or had scorable volume",
        )

    best = min(feasible, key=lambda s: s.conductance.phi)
    if best.conductance.phi <= epsilon:
        return StructuralAuditResult(
            chain_id=chain_id,
            verdict=AuditVerdict.CANDIDATE_SPLIT,
            best_cut=best,
            scored_candidates=tuple(scored),
            epsilon=epsilon,
            reason=(
                f"{best.candidate.label}: Phi={best.conductance.phi:.4f} <= "
                f"epsilon={epsilon:.4f}"
            ),
        )

    return StructuralAuditResult(
        chain_id=chain_id,
        verdict=AuditVerdict.NO_LOW_CONDUCTANCE_CUT,
        best_cut=best,
        scored_candidates=tuple(scored),
        epsilon=epsilon,
        reason=(
            f"best candidate {best.candidate.label}: Phi={best.conductance.phi:.4f} "
            f"> epsilon={epsilon:.4f}"
        ),
    )


class OverMergeStrength(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    NONE = "NONE"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


@dataclass(frozen=True)
class OverMergeVerdict:
    """Multi-evidence over-merge verdict. Never a single-signal claim."""

    chain_id: str
    structural_separation: bool
    cross_evidence_agreement: bool
    descriptor_separation: bool
    sensitivity_stability: bool
    strength: OverMergeStrength
    driving_evidence: tuple[str, ...]
    narrative: str

    @property
    def evidence_count(self) -> int:
        return sum(
            [
                self.structural_separation,
                self.cross_evidence_agreement,
                self.descriptor_separation,
                self.sensitivity_stability,
            ]
        )


def descriptor_separation(
    block_a: frozenset[str],
    block_b: frozenset[str],
    index: PredicateIndex,
    mining_config: MiningConfig,
) -> bool:
    """True when each block has its own distinct IDENTITY pattern.

    Each block is tested as the mining target against the whole universe; both
    must clear the precision floor with a *different* top predicate for the
    blocks to be considered separated.
    """
    target_a = bitmap_of_members(index, set(block_a))
    target_b = bitmap_of_members(index, set(block_b))
    descriptors_a = mine_descriptors(
        index, target_a, config=mining_config, kind=DescriptorKind.IDENTITY
    )
    descriptors_b = mine_descriptors(
        index, target_b, config=mining_config, kind=DescriptorKind.IDENTITY
    )
    if not descriptors_a or not descriptors_b:
        return False
    return descriptors_a[0].label != descriptors_b[0].label


def sensitivity_stability(
    graph: AuditGraph,
    members: frozenset[str],
    *,
    epsilon: float,
    chain_size: int,
    epsilon_range: tuple[float, ...] = (0.8, 0.9, 1.0, 1.1, 1.2),
) -> bool:
    """True when the same cut stays below threshold across a range of epsilon.

    A cut that only clears one exact threshold value is not a stable structural
    feature; scaling epsilon by the given factors checks robustness.
    """
    result = conductance(graph, members, label="sensitivity-check")
    if result.phi is None:
        return False
    return all(result.phi <= epsilon * factor for factor in epsilon_range)


def assess_over_merge(
    audit: StructuralAuditResult,
    graph: AuditGraph,
    *,
    index: PredicateIndex,
    mining_config: MiningConfig,
    cross_block_negative_evidence: bool = False,
) -> OverMergeVerdict:
    """Combine the four evidence lines into one verdict.

    Conclusion wording says which evidence drove it and recommends review; it
    never asserts that NocPro is wrong (ADR-0018).
    """
    if audit.best_cut is None or audit.verdict is not AuditVerdict.CANDIDATE_SPLIT:
        return OverMergeVerdict(
            chain_id=audit.chain_id,
            structural_separation=False,
            cross_evidence_agreement=False,
            descriptor_separation=False,
            sensitivity_stability=False,
            strength=OverMergeStrength.NONE,
            driving_evidence=(),
            narrative=f"Chain {audit.chain_id}: {audit.reason}",
        )

    block_a = audit.best_cut.candidate.members
    block_b = frozenset(graph.members) - block_a

    has_descriptor_separation = descriptor_separation(
        block_a, block_b, index, mining_config
    )
    is_stable = sensitivity_stability(
        graph, block_a, epsilon=audit.epsilon, chain_size=len(graph.members)
    )

    driving = [audit.best_cut.candidate.source.value]
    evidence_count = 1  # structural separation, always true at this point
    if cross_block_negative_evidence:
        evidence_count += 1
        driving.append("CROSS_BLOCK_CONTRADICTION")
    if has_descriptor_separation:
        evidence_count += 1
        driving.append("DESCRIPTOR_SEPARATION")
    if is_stable:
        evidence_count += 1
        driving.append("SENSITIVITY_STABILITY")

    strength = (
        OverMergeStrength.WEAK
        if evidence_count == 1
        else OverMergeStrength.MODERATE
        if evidence_count == 2
        else OverMergeStrength.STRONG
    )

    return OverMergeVerdict(
        chain_id=audit.chain_id,
        structural_separation=True,
        cross_evidence_agreement=cross_block_negative_evidence,
        descriptor_separation=has_descriptor_separation,
        sensitivity_stability=is_stable,
        strength=strength,
        driving_evidence=tuple(driving),
        narrative=(
            f"Chain {audit.chain_id}: {audit.best_cut.candidate.label} shows a "
            f"balanced low-conductance cut (Phi={audit.best_cut.conductance.phi:.4f}), "
            f"backed by {evidence_count} evidence line(s) ({', '.join(driving)}). "
            "This chain should be reviewed for a possible over-merge; it is not a "
            "claim that NocPro is wrong."
        ),
    )

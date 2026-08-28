"""Synthetic system pair metadata generator (docs 07 §7, P0.5).

Exercises Gray-box adapter typing: raw score ``2.0``, TimeWindow veto
``-999999999``, EVALUATED / NOT_EVALUATED / UNKNOWN, and
FULL_PAIR_SPACE vs BOUNDED_COMPARISON.

Two declaration modes, both materializing the *same* canonical ``M_pair``
records so downstream cannot tell which was used:

1. ``pairs:`` — explicit list. Preferred for correctness fixtures: a hand-listed
   pair is reviewable, whereas a distribution can pass by luck.
2. ``generator:`` — deterministic pattern for scale/stress tests only.

Typing rules:
- veto keeps the raw sentinel plus ``system_semantic=VETO``; a null score would
  discard the raw SYSTEM_FACT value;
- NOT_EVALUATED / UNKNOWN carry ``raw_score=null`` and no semantic;
- ``coverage_scope`` is declared once on the batch, never per pair;
- every result carries ``attribute_ref`` so a raw score is interpretable.
"""

from __future__ import annotations

from ..contract import (
    TIMEWINDOW_VETO_SENTINEL,
    AttributeConfig,
    CoverageScope,
    GenerationMetadata,
    PairMetadata,
    PairMetadataBatch,
    ProvenanceClass,
    SystemPairStatus,
    SystemSemantic,
)
from .schema import ScenarioDefinition, ScenarioError, require_synthetic_identifiers

GENERATOR_TYPE_DETERMINISTIC = "DETERMINISTIC_PAIR_PATTERN"
SCORING_RULE_SAME_REFERENCE = "SAME_SYNTHETIC_REFERENCE"


def _parse_status(raw: str, label: str) -> SystemPairStatus:
    try:
        return SystemPairStatus(raw)
    except ValueError as exc:
        raise ScenarioError(f"{label}: unknown system_pair_status {raw!r}") from exc


def _parse_semantic(raw: str | None, label: str) -> SystemSemantic | None:
    if raw is None:
        return None
    try:
        return SystemSemantic(raw)
    except ValueError as exc:
        raise ScenarioError(f"{label}: unknown system_semantic {raw!r}") from exc


def _validate_pair_typing(
    *,
    label: str,
    status: SystemPairStatus,
    raw_score: float | None,
    semantic: SystemSemantic | None,
) -> None:
    """Reject contradictory declarations at scenario-load time."""
    if status is not SystemPairStatus.EVALUATED:
        if raw_score is not None:
            raise ScenarioError(
                f"{label}: system_pair_status={status.value} must have raw_score=null"
            )
        if semantic is not None:
            raise ScenarioError(
                f"{label}: system_pair_status={status.value} must have no system_semantic"
            )
        return

    if semantic is SystemSemantic.VETO and raw_score != TIMEWINDOW_VETO_SENTINEL:
        raise ScenarioError(
            f"{label}: system_semantic=VETO must preserve "
            f"raw_score={TIMEWINDOW_VETO_SENTINEL}, got {raw_score!r}"
        )
    if raw_score == TIMEWINDOW_VETO_SENTINEL and semantic is not SystemSemantic.VETO:
        raise ScenarioError(
            f"{label}: raw_score={TIMEWINDOW_VETO_SENTINEL} is the veto sentinel and "
            "must declare system_semantic=VETO"
        )


def generate_system_pair_metadata(
    scenario: ScenarioDefinition, *, generator_version: str, chain_id: str
) -> tuple[
    tuple[PairMetadata, ...], tuple[PairMetadataBatch, ...], tuple[AttributeConfig, ...]
]:
    """Materialize canonical ``M_pair`` records plus their batch metadata."""
    block = scenario.require_block("system_pair_metadata")

    attribute_ref = block.get("attribute_ref")
    if not attribute_ref:
        raise ScenarioError(
            f"scenario {scenario.scenario_id!r}: system_pair_metadata requires "
            "attribute_ref so a raw score is interpretable"
        )
    attribute_ref = str(attribute_ref)
    require_synthetic_identifiers([attribute_ref], context=scenario.scenario_id)

    raw_scope = str(block.get("coverage_scope", CoverageScope.UNKNOWN.value))
    try:
        coverage_scope = CoverageScope(raw_scope)
    except ValueError as exc:
        raise ScenarioError(f"unknown coverage_scope {raw_scope!r}") from exc

    generation = GenerationMetadata(
        scenario_id=scenario.scenario_id,
        seed=scenario.seed,
        generator_version=generator_version,
        generation_rule="explicit synthetic system pair metadata",
        base_fixture_id=scenario.base_fixture,
    )

    explicit = block.get("pairs")
    generator_spec = block.get("generator")
    if explicit and generator_spec:
        raise ScenarioError(
            f"scenario {scenario.scenario_id!r}: declare either 'pairs' or "
            "'generator', not both"
        )

    if explicit:
        pairs = _build_explicit(
            explicit,
            scenario=scenario,
            chain_id=chain_id,
            attribute_ref=attribute_ref,
        )
        max_compare = None
    elif generator_spec:
        pairs, max_compare, generation = _build_generated(
            generator_spec,
            scenario=scenario,
            chain_id=chain_id,
            attribute_ref=attribute_ref,
            generator_version=generator_version,
        )
    else:
        raise ScenarioError(
            f"scenario {scenario.scenario_id!r}: system_pair_metadata needs "
            "'pairs' or 'generator'"
        )

    batch = PairMetadataBatch(
        batch_id=f"{scenario.scenario_id}:{attribute_ref}",
        coverage_scope=coverage_scope,
        attribute_ref=attribute_ref,
        chain_id=chain_id,
        pair_count=len(pairs),
        max_compare_per_alarm=max_compare,
        provenance_class=ProvenanceClass.SYSTEM_FACT,
        generation=generation,
    )

    # Emit the referenced AttributeConfig so attribute_ref always resolves.
    declared = block.get("attribute_config") or {}
    attribute_config = AttributeConfig(
        attribute_type=int(declared.get("attribute_type", 3)),
        attribute_ref=attribute_ref,
        content=declared.get("content"),
        algorithm_type=declared.get("algorithm_type"),
        filter_name=declared.get("filter_name"),
        weight=(float(declared["weight"]) if declared.get("weight") is not None else None),
        provenance_class=ProvenanceClass.SYSTEM_FACT,
    )

    return pairs, (batch,), (attribute_config,)


def _build_explicit(
    entries: list[dict],
    *,
    scenario: ScenarioDefinition,
    chain_id: str,
    attribute_ref: str,
) -> tuple[PairMetadata, ...]:
    results: list[PairMetadata] = []
    seen: set[tuple[str, str]] = set()

    for entry in entries:
        a = str(entry.get("alarm_id_a") or "")
        b = str(entry.get("alarm_id_b") or "")
        if not a or not b:
            raise ScenarioError(
                f"scenario {scenario.scenario_id!r}: pair needs alarm_id_a and alarm_id_b"
            )
        if a == b:
            raise ScenarioError(f"pair {a!r} references the same alarm twice")

        label = f"pair {a}/{b}"
        require_synthetic_identifiers([a, b], context=label)

        # Undirected pair identity: (A,B) and (B,A) are the same record.
        key = tuple(sorted((a, b)))
        if key in seen:
            raise ScenarioError(f"{label}: duplicate pair declaration")
        seen.add(key)

        status = _parse_status(str(entry.get("system_pair_status") or ""), label)
        raw_score = entry.get("raw_score")
        score = float(raw_score) if raw_score is not None else None
        semantic = _parse_semantic(entry.get("system_semantic"), label)
        _validate_pair_typing(
            label=label, status=status, raw_score=score, semantic=semantic
        )

        results.append(
            PairMetadata(
                chain_id=chain_id,
                alarm_id_a=a,
                alarm_id_b=b,
                system_pair_status=status,
                attribute_ref=attribute_ref,
                raw_score=score,
                system_semantic=semantic,
                # Redundant with the enum but kept when the sentinel is present.
                veto=True if semantic is SystemSemantic.VETO else None,
                provenance_class=ProvenanceClass.SYSTEM_FACT,
            )
        )

    return tuple(results)


def _build_generated(
    spec: dict,
    *,
    scenario: ScenarioDefinition,
    chain_id: str,
    attribute_ref: str,
    generator_version: str,
) -> tuple[tuple[PairMetadata, ...], int | None, GenerationMetadata]:
    """Deterministic pattern for scale tests.

    Bounded by ``max_compare_per_alarm`` so it cannot materialize ``C(N,2)``,
    mirroring NocPro's own ``maxComparePerAlarm`` and honouring ADR-0015.
    """
    generator_type = str(spec.get("type") or "")
    if generator_type != GENERATOR_TYPE_DETERMINISTIC:
        raise ScenarioError(
            f"unknown pair generator type {generator_type!r}; "
            f"expected {GENERATOR_TYPE_DETERMINISTIC}"
        )

    scoring_rule = str(spec.get("scoring_rule") or SCORING_RULE_SAME_REFERENCE)
    if scoring_rule != SCORING_RULE_SAME_REFERENCE:
        raise ScenarioError(f"unknown scoring_rule {scoring_rule!r}")

    alarm_count = int(spec.get("alarm_count", 0))
    if alarm_count < 2:
        raise ScenarioError("pair generator needs alarm_count >= 2")
    max_compare = int(spec.get("max_compare_per_alarm", 0))
    if max_compare < 1:
        raise ScenarioError("pair generator needs max_compare_per_alarm >= 1")

    seed = int(spec.get("seed", scenario.seed))

    # Deterministic and seed-dependent without random(): a fixed stride derived
    # from the seed keeps output reproducible and reviewable.
    stride = 1 + (seed % max(1, alarm_count - 1))
    results: list[PairMetadata] = []
    seen: set[tuple[str, str]] = set()

    for index in range(alarm_count):
        for step in range(1, max_compare + 1):
            partner = (index + step * stride) % alarm_count
            if partner == index:
                continue
            a = f"SYN-A-{min(index, partner):06d}"
            b = f"SYN-A-{max(index, partner):06d}"
            key = (a, b)
            if key in seen:
                continue
            seen.add(key)
            # Same synthetic reference block => SUPPORT, else NEUTRAL.
            same_block = (index % 2) == (partner % 2)
            results.append(
                PairMetadata(
                    chain_id=chain_id,
                    alarm_id_a=a,
                    alarm_id_b=b,
                    system_pair_status=SystemPairStatus.EVALUATED,
                    attribute_ref=attribute_ref,
                    raw_score=1.0 if same_block else 0.0,
                    system_semantic=(
                        SystemSemantic.SUPPORT if same_block else SystemSemantic.NEUTRAL
                    ),
                    provenance_class=ProvenanceClass.SYSTEM_FACT,
                )
            )

    generation = GenerationMetadata(
        scenario_id=scenario.scenario_id,
        seed=seed,
        generator_version=generator_version,
        generation_rule=(
            f"{GENERATOR_TYPE_DETERMINISTIC}/{scoring_rule}: alarm_count={alarm_count}, "
            f"max_compare_per_alarm={max_compare}, stride={stride}"
        ),
        base_fixture_id=scenario.base_fixture,
    )
    # Sorted so output does not depend on insertion order.
    ordered = tuple(sorted(results, key=lambda p: (p.alarm_id_a, p.alarm_id_b)))
    return ordered, max_compare, generation

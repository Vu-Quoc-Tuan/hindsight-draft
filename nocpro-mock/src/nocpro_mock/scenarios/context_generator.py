"""Synthetic operational context generator (docs 07/08, P0.5).

Emits maintenance / ticket / operator-label / fault-injection context so the
downstream EXTERNAL_OPERATIONAL code paths can be exercised.

Explicit non-goal (docs 08): synthetic context is never real operational
validation. The scenario fixture states this as
``validation.eligible_as_real_operational_validation: false``; this generator
refuses to run if a scenario claims otherwise, and the ADR-0010 source-kind gate
blocks it regardless.
"""

from __future__ import annotations

from ..contract import (
    ChainingUsage,
    ChainingUsageAssessment,
    ContextType,
    GenerationMetadata,
    OperationalContext,
    ProvenanceClass,
    ProvenanceSubtype,
    QualityStatus,
    SourceKind,
)
from .schema import ScenarioDefinition, ScenarioError, require_synthetic_identifiers

#: Context type -> provenance subtype. Both dimensions are recorded because
#: ADR-0007 keeps subtype refinement separate from the top-level class.
_SUBTYPE_BY_TYPE = {
    ContextType.MAINTENANCE: ProvenanceSubtype.MAINTENANCE,
    ContextType.TICKET: ProvenanceSubtype.TICKET,
    ContextType.OPERATOR_LABEL: ProvenanceSubtype.OPERATOR_LABEL,
    ContextType.FAULT_INJECTION: ProvenanceSubtype.FAULT_INJECTION,
}


def generate_operational_context(
    scenario: ScenarioDefinition, *, generator_version: str
) -> tuple[OperationalContext, ...]:
    """Build synthetic context entries from a scenario definition."""
    entries = scenario.require_block("context")
    if not entries:
        raise ScenarioError(
            f"scenario {scenario.scenario_id!r} declares no context entries"
        )

    if scenario.validation.get("eligible_as_real_operational_validation"):
        raise ScenarioError(
            f"scenario {scenario.scenario_id!r} claims synthetic context is "
            "eligible as real operational validation; refused (ADR-0010, docs 08)"
        )

    generation = GenerationMetadata(
        scenario_id=scenario.scenario_id,
        seed=scenario.seed,
        generator_version=generator_version,
        generation_rule="explicit synthetic operational context entries",
        base_fixture_id=scenario.base_fixture,
    )

    results: list[OperationalContext] = []
    for entry in entries:
        context_id = str(entry.get("context_id") or "")
        raw_type = str(entry.get("type") or "")
        resources = [str(r) for r in (entry.get("affected_resources") or [])]
        if not context_id:
            raise ScenarioError("context entry needs a context_id")
        try:
            context_type = ContextType(raw_type)
        except ValueError as exc:
            raise ScenarioError(
                f"unknown context type {raw_type!r} for {context_id!r}"
            ) from exc
        if not resources:
            raise ScenarioError(f"context {context_id!r} affects no resources")
        if len(set(resources)) != len(resources):
            raise ScenarioError(f"context {context_id!r} repeats a resource")

        require_synthetic_identifiers([context_id, *resources], context=context_id)

        results.append(
            OperationalContext(
                context_id=context_id,
                context_type=context_type,
                affected_resources=tuple(resources),
                source_kind=SourceKind.SYNTHETIC_TEST,
                provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
                provenance_subtype=_SUBTYPE_BY_TYPE[context_type],
                start_time=(
                    str(entry["start_time"]) if entry.get("start_time") else None
                ),
                end_time=(str(entry["end_time"]) if entry.get("end_time") else None),
                # Synthetic context did not exist during any chaining run.
                chaining_usage=ChainingUsageAssessment(
                    source_id=scenario.scenario_id,
                    source_version=None,
                    chaining_config_version=None,
                    usage=ChainingUsage.CONFIRMED_NOT_USED.value,
                    run_context="synthetic scenario; data absent from any chaining run",
                ),
                quality_status=QualityStatus.UNKNOWN,
                generation=generation,
            )
        )

    return tuple(results)

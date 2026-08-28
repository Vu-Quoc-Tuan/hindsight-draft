"""Normalized-evidence eligibility signature (V2.3.1 §4B, ADR-0010).

An eligibility signature is the triple ``(explain_eligible, role_eligible,
audit_eligible)`` computed from a channel's provenance class and subtype under a
versioned config. It is deliberately separate from ``source_kind`` and
``chaining_usage``, which constrain Validate only.
"""

from __future__ import annotations

from dataclasses import dataclass

from .classes import ProvenanceClass, ProvenanceSubtype


@dataclass(frozen=True)
class EligibilitySignature:
    """Which masks a normalized channel may participate in."""

    explain_eligible: bool
    role_eligible: bool
    audit_eligible: bool

    def as_tuple(self) -> tuple[bool, bool, bool]:
        return (self.explain_eligible, self.role_eligible, self.audit_eligible)


#: Baseline methodology defaults from the V2.3.1 §4B eligibility table.
#: SYSTEM_FACT is displayed separately; BEHAVIORAL explains with a label only.
#: Positive-graph subtypes (ticket/maintenance/operator/fault-injection) may
#: explain and may contradict, but never add a positive structural audit edge.
_BASELINE: dict[tuple[ProvenanceClass, ProvenanceSubtype | None], EligibilitySignature] = {
    (ProvenanceClass.POST_HOC, None): EligibilitySignature(True, True, True),
    (ProvenanceClass.EXTERNAL_OPERATIONAL, ProvenanceSubtype.TOPOLOGY_EXTERNAL): (
        EligibilitySignature(True, True, True)
    ),
    (ProvenanceClass.EXTERNAL_OPERATIONAL, ProvenanceSubtype.TICKET): (
        EligibilitySignature(True, False, False)
    ),
    (ProvenanceClass.EXTERNAL_OPERATIONAL, ProvenanceSubtype.MAINTENANCE): (
        EligibilitySignature(True, False, False)
    ),
    (ProvenanceClass.EXTERNAL_OPERATIONAL, ProvenanceSubtype.OPERATOR_LABEL): (
        EligibilitySignature(True, False, False)
    ),
    (ProvenanceClass.EXTERNAL_OPERATIONAL, ProvenanceSubtype.FAULT_INJECTION): (
        EligibilitySignature(True, False, False)
    ),
    (ProvenanceClass.SYSTEM_FACT, None): EligibilitySignature(False, False, False),
    (ProvenanceClass.BEHAVIORAL, None): EligibilitySignature(True, False, False),
}


def baseline_eligibility(
    provenance_class: ProvenanceClass,
    subtype: ProvenanceSubtype | None = None,
) -> EligibilitySignature:
    """Resolve the baseline eligibility signature.

    Fails closed: an unrecognized combination is not eligible for anything
    rather than defaulting to permissive.
    """
    if (provenance_class, subtype) in _BASELINE:
        return _BASELINE[(provenance_class, subtype)]
    if (provenance_class, None) in _BASELINE:
        return _BASELINE[(provenance_class, None)]
    return EligibilitySignature(False, False, False)

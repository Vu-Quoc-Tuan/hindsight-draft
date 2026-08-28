"""Provenance vocabulary for the analysis core (ADR-0007).

Re-declared here rather than imported from ``contracts/v1`` because the contract
is the *integration* schema while this is the internal analysis model. ADR-0002
keeps the two concerns separate; the values are identical by design and the
contract remains the wire authority.
"""

from __future__ import annotations

from enum import Enum


class ProvenanceClass(str, Enum):
    """Exactly four top-level classes. Not extensible."""

    SYSTEM_FACT = "SYSTEM_FACT"
    POST_HOC = "POST_HOC"
    BEHAVIORAL = "BEHAVIORAL"
    EXTERNAL_OPERATIONAL = "EXTERNAL_OPERATIONAL"


class ProvenanceSubtype(str, Enum):
    """Refines, never replaces, :class:`ProvenanceClass`."""

    TOPOLOGY_EXTERNAL = "TOPOLOGY_EXTERNAL"
    TICKET = "TICKET"
    MAINTENANCE = "MAINTENANCE"
    OPERATOR_LABEL = "OPERATOR_LABEL"
    FAULT_INJECTION = "FAULT_INJECTION"

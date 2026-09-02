"""Provenance, eligibility and derivation grouping for the analysis core."""

from .classes import ProvenanceClass, ProvenanceSubtype
from .derivation import (
    DerivationGroup,
    EffectiveGroupKey,
    NormalizedChannel,
    audit_groups,
    build_derivation_groups,
    normalize_pair_channels,
    role_groups,
)
from .eligibility import EligibilitySignature, baseline_eligibility

__all__ = [
    "DerivationGroup",
    "EffectiveGroupKey",
    "EligibilitySignature",
    "NormalizedChannel",
    "ProvenanceClass",
    "ProvenanceSubtype",
    "audit_groups",
    "baseline_eligibility",
    "build_derivation_groups",
    "normalize_pair_channels",
    "role_groups",
]

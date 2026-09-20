"""Canonical Input Contract v1 — enum vocabulary.

Owned by ``nocpro-chain-explain`` per ADR-0002. ``nocpro-mock`` consumes this
as a read-only artifact and MUST NOT define a divergent canonical contract.

Frozen by ADR-0002 / ADR-0007 / ADR-0010. Consumers MUST reject unknown values
rather than coercing them (fail closed).
"""

from __future__ import annotations

from enum import Enum

SCHEMA_VERSION = "v1"


class SourceKind(str, Enum):
    """Origin dimension.

    ``BACKFILL`` means bootstrap/training/backfill state. Old-but-real
    observations replayed for evaluation use ``REAL_EXPORT_REPLAY``, not
    ``BACKFILL`` merely because they are old (ADR-0002, ADR-0007).
    """

    REAL_LIVE = "REAL_LIVE"
    REAL_EXPORT_REPLAY = "REAL_EXPORT_REPLAY"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"
    BACKFILL = "BACKFILL"


class ProvenanceClass(str, Enum):
    """Exactly four top-level classes (ADR-0007). Not extensible."""

    SYSTEM_FACT = "SYSTEM_FACT"
    POST_HOC = "POST_HOC"
    BEHAVIORAL = "BEHAVIORAL"
    EXTERNAL_OPERATIONAL = "EXTERNAL_OPERATIONAL"


class ProvenanceSubtype(str, Enum):
    """Refines, never replaces, ``ProvenanceClass``."""

    TOPOLOGY_EXTERNAL = "TOPOLOGY_EXTERNAL"
    TICKET = "TICKET"
    MAINTENANCE = "MAINTENANCE"
    OPERATOR_LABEL = "OPERATOR_LABEL"
    FAULT_INJECTION = "FAULT_INJECTION"


class ChainingUsage(str, Enum):
    """Constrains Validate only, never Explain/Role/Audit (ADR-0010)."""

    CONFIRMED_USED = "CONFIRMED_USED"
    CONFIRMED_NOT_USED = "CONFIRMED_NOT_USED"
    UNKNOWN = "UNKNOWN"


class QualityStatus(str, Enum):
    """Eligibility result computed under a versioned config, not a provenance class."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class SystemPairStatus(str, Enum):
    """Missing record defaults to UNKNOWN, never NEUTRAL (ADR-0002)."""

    EVALUATED = "EVALUATED"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


class CoverageScope(str, Enum):
    """Per characteristic/attribute export, not a blanket property of a chain.

    Coverage describes a batch/export evaluation scope, so it belongs on the
    batch that produced a set of pair records, never duplicated onto every pair.
    """

    FULL_PAIR_SPACE = "FULL_PAIR_SPACE"
    BOUNDED_COMPARISON = "BOUNDED_COMPARISON"
    UNKNOWN = "UNKNOWN"


class SystemSemantic(str, Enum):
    """Documented interpretation of a raw system score.

    An enum rather than a boolean ``veto`` flag because it is extensible and
    keeps the interpretation explicit. The raw value is always preserved
    alongside it: a TimeWindow veto is emitted as ``raw_score=-999999999`` plus
    ``system_semantic=VETO``, never as a null score.
    """

    SUPPORT = "SUPPORT"
    NEUTRAL = "NEUTRAL"
    VETO = "VETO"
    UNKNOWN = "UNKNOWN"


#: NocPro TimeWindow veto sentinel. Preserved verbatim as a SYSTEM_FACT and never
#: normalized into evidence.
TIMEWINDOW_VETO_SENTINEL = -999999999


class MappingStatus(str, Enum):
    EXACT = "EXACT"
    VERIFIED_ALIAS = "VERIFIED_ALIAS"
    STRUCTURED_FIELD_UNIQUE = "STRUCTURED_FIELD_UNIQUE"
    TEXT_MATCH_CANDIDATE = "TEXT_MATCH_CANDIDATE"
    UNMAPPED = "UNMAPPED"
    AMBIGUOUS = "AMBIGUOUS"


class MappingMethod(str, Enum):
    """Fuzzy/prefix matching is deliberately absent: forbidden by ADR-MOCK-0005."""

    EXACT_IDENTITY = "EXACT_IDENTITY"
    VERIFIED_ALIAS_TABLE = "VERIFIED_ALIAS_TABLE"
    RAW_TEXT_EXACT_TOKEN = "RAW_TEXT_EXACT_TOKEN"
    STRUCTURED_FIELD_EXACT = "STRUCTURED_FIELD_EXACT"
    NONE = "NONE"


class RelationType(str, Enum):
    """Only what a source actually supports.

    ``IP_ADJACENCY`` is undirected: it must never be renamed to
    ``LOGICAL_DEPENDENCY`` because endpoints look hierarchical (ADR-MOCK-0005).
    """

    IP_ADJACENCY = "IP_ADJACENCY"
    LOGICAL_DEPENDENCY = "LOGICAL_DEPENDENCY"
    SERVICE_DEPENDS_ON = "SERVICE_DEPENDS_ON"


class QualityFlag(str, Enum):
    """Dirty-data markers. Flags are recorded; values are never silently repaired."""

    MULTILINE_CONTENT = "MULTILINE_CONTENT"
    TIMESTAMP_FUTURE_OUTLIER = "TIMESTAMP_FUTURE_OUTLIER"
    END_BEFORE_START = "END_BEFORE_START"
    UNPARSEABLE_TIMESTAMP = "UNPARSEABLE_TIMESTAMP"
    MISSING_REQUIRED_ID = "MISSING_REQUIRED_ID"
    MISSING_DEVICE_CODE = "MISSING_DEVICE_CODE"
    MISSING_NODE_REFERENCE = "MISSING_NODE_REFERENCE"


class SnapshotStatus(str, Enum):
    """Tier-1A may only run on COMPLETE snapshots (ADR-0005)."""

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class FailureDomainType(str, Enum):
    SRLG = "SRLG"
    POWER = "POWER"
    RACK = "RACK"
    SERVICE_INSTANCE = "SERVICE_INSTANCE"


class ContextType(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    TICKET = "TICKET"
    OPERATOR_LABEL = "OPERATOR_LABEL"
    FAULT_INJECTION = "FAULT_INJECTION"


#: Source kinds permitted past the ADR-0010 stage-1 source-kind gate.
VALIDATION_ELIGIBLE_SOURCE_KINDS = frozenset(
    {SourceKind.REAL_LIVE, SourceKind.REAL_EXPORT_REPLAY}
)

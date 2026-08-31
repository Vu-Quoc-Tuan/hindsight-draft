"""Canonical Input Contract v1 — record definitions.

Owned by ``nocpro-chain-explain`` per ADR-0002; ``nocpro-mock`` validates its
output against this artifact. Plain dataclasses are used so the contract has no
third-party dependency and can be vendored read-only for CI.

Structure follows ``MockSnapshotPackage`` in nocpro-mock docs
``04-canonical-output-model.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import (
    ContextType,
    CoverageScope,
    FailureDomainType,
    MappingMethod,
    MappingStatus,
    ProvenanceClass,
    ProvenanceSubtype,
    QualityStatus,
    RelationType,
    SnapshotStatus,
    SourceKind,
    SystemPairStatus,
)


@dataclass(frozen=True)
class ChainingUsageAssessment:
    """Resolved in context; never one global flag for a whole store (ADR-0010)."""

    source_id: str
    usage: str
    source_version: str | None = None
    chaining_config_version: str | None = None
    executed_rule_set: tuple[str, ...] | None = None
    executed_attribute_set: tuple[str, ...] | None = None
    run_context: str | None = None


@dataclass(frozen=True)
class GenerationMetadata:
    """Required on every SYNTHETIC_TEST object (ADR-0026, ADR-MOCK-0004)."""

    scenario_id: str
    seed: int
    generator_version: str
    generation_rule: str
    base_fixture_id: str | None = None


@dataclass(frozen=True)
class Snapshot:
    """Primary processing boundary (ADR-0005)."""

    snapshot_id: str
    snapshot_version: str
    snapshot_time: str
    status: SnapshotStatus
    source: str
    source_kind: SourceKind
    produced_at: str
    schema_version: str = "v1"
    config_version: str | None = None
    topology_version: str | None = None


@dataclass(frozen=True)
class Alarm:
    """Raw values preserved alongside canonical values (ADR-MOCK-0002).

    ``raw`` holds every original column verbatim so a dirty row is always
    reconstructible. Canonical fields are additive, never replacements.
    """

    alarm_id: str
    snapshot_id: str
    source_kind: SourceKind
    provenance_class: ProvenanceClass
    raw: dict[str, str]
    raw_start_time: str | None = None
    raw_end_time: str | None = None
    canonical_start_time: str | None = None
    canonical_end_time: str | None = None
    alarm_name: str | None = None
    device_code: str | None = None
    node_reference: str | None = None
    severity_name: str | None = None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Chain:
    """Chain IDs are snapshot-scoped identifiers, not incident identities (ADR-0005)."""

    chain_id: str
    snapshot_id: str
    member_count: int
    source_kind: SourceKind
    provenance_class: ProvenanceClass
    chain_name: str | None = None
    event_span_seconds: int | None = None


@dataclass(frozen=True)
class ChainMembership:
    chain_id: str
    alarm_id: str
    snapshot_id: str
    source_kind: SourceKind


@dataclass(frozen=True)
class ChainRule:
    """``M_chain_rule``: replayed rule/connector/extender/merge metadata."""

    chain_id: str
    rule_name: str
    member_count: int
    connector_count: int | None = None
    extender_count: int | None = None
    merge_strategy: str | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.SYSTEM_FACT


@dataclass(frozen=True)
class ChainCharacteristic:
    """``M_chain_characteristic``: aggregate counts only.

    An aggregate pair_count MUST NOT be expanded into concrete pair edges.
    ``coverage_scope`` is per characteristic, not per chain.
    """

    chain_id: str
    name: str
    pair_count: int
    coverage_scope: CoverageScope
    value: str | None = None
    threshold_seconds: int | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.SYSTEM_FACT


@dataclass(frozen=True)
class AttributeConfig:
    """``M_attribute_config``: type/content/algorithm/filter/weight only.

    Raw pair scores MUST NEVER be placed here (docs 03). ``attribute_ref`` is the
    identity that :class:`PairMetadata` points back to, so a raw score is always
    interpretable: ``2.0`` is meaningless without knowing which Attribute
    produced it.
    """

    attribute_type: int
    attribute_ref: str | None = None
    content: str | None = None
    algorithm_type: str | None = None
    filter_name: str | None = None
    weight: float | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.SYSTEM_FACT


@dataclass(frozen=True)
class PairMetadata:
    """``M_pair``: exact raw system score/veto/status for one pair.

    Raw scores are kept raw: out-of-range values such as ``2.0`` and the
    TimeWindow veto ``-999999999`` are never normalized into evidence.

    ``attribute_ref`` traces the result back to its :class:`AttributeConfig`. A
    per-attribute record is the canonical unit; if a full ``simiDict`` vector
    becomes available it is flattened into one record per attribute, which leaves
    these semantics unchanged.

    ``coverage_scope`` is deliberately absent: it describes the batch/export that
    produced these records and lives on :class:`PairMetadataBatch`.
    """

    chain_id: str
    alarm_id_a: str
    alarm_id_b: str
    system_pair_status: SystemPairStatus
    attribute_ref: str | None = None
    raw_score: float | None = None
    system_semantic: SystemSemantic | None = None
    veto: bool | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.SYSTEM_FACT


@dataclass(frozen=True)
class PairMetadataBatch:
    """Batch/export-level metadata for a set of ``M_pair`` records.

    Exists so ``coverage_scope`` is stated once per export rather than copied
    onto every pair. Explain needs it to interpret a *missing* pair: under
    ``BOUNDED_COMPARISON`` absence means "not compared", which is not the same as
    "compared and found unrelated".
    """

    batch_id: str
    coverage_scope: CoverageScope
    attribute_ref: str | None = None
    chain_id: str | None = None
    pair_count: int | None = None
    max_compare_per_alarm: int | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.SYSTEM_FACT
    generation: GenerationMetadata | None = None


@dataclass(frozen=True)
class SystemMetadata:
    chain_rules: tuple[ChainRule, ...] = ()
    chain_characteristics: tuple[ChainCharacteristic, ...] = ()
    attribute_configs: tuple[AttributeConfig, ...] = ()
    pair_metadata: tuple[PairMetadata, ...] = ()
    pair_metadata_batches: tuple[PairMetadataBatch, ...] = ()


@dataclass(frozen=True)
class TopologyNode:
    resource_id: str
    source_id: str
    source_kind: SourceKind
    topology_layer: str | None = None
    network_class: str | None = None
    source_version: str | None = None
    generation: GenerationMetadata | None = None


@dataclass(frozen=True)
class TopologyEdge:
    """``directed`` must reflect the source.

    A generic directed edge MUST NOT be emitted when the source only provides
    undirected adjacency (docs 04, ADR-MOCK-0005).
    """

    edge_id: str
    source_resource_id: str
    target_resource_id: str
    relation_type: RelationType
    directed: bool
    source_id: str
    source_kind: SourceKind
    source_version: str | None = None
    freshness: str | None = None
    freshness_age_seconds: int | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.EXTERNAL_OPERATIONAL
    provenance_subtype: ProvenanceSubtype | None = ProvenanceSubtype.TOPOLOGY_EXTERNAL
    chaining_usage: ChainingUsageAssessment | None = None
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    generation: GenerationMetadata | None = None


@dataclass(frozen=True)
class FailureDomain:
    """Hyperedge / member set. MUST NOT be clique-projected into pair edges (ADR-0011)."""

    failure_domain_id: str
    domain_type: FailureDomainType
    members: tuple[str, ...]
    source_id: str
    source_kind: SourceKind
    source_version: str | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.EXTERNAL_OPERATIONAL
    provenance_subtype: ProvenanceSubtype | None = ProvenanceSubtype.TOPOLOGY_EXTERNAL
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    generation: GenerationMetadata | None = None


@dataclass(frozen=True)
class ActivePath:
    """Explicit first-class path data; never inferred from adjacency (ADR-MOCK-0005)."""

    path_id: str
    resource_id: str
    nodes: tuple[str, ...]
    source_id: str
    source_kind: SourceKind
    source_version: str | None = None
    generation: GenerationMetadata | None = None


@dataclass(frozen=True)
class AlarmResourceMapping:
    """Fuzzy prefix match is not a mapping method (docs 04/06)."""

    alarm_id: str
    resource_id: str | None
    mapping_status: MappingStatus
    mapping_method: MappingMethod
    mapping_confidence: float | None = None
    topology_layer: str | None = None
    source_version: str | None = None


@dataclass(frozen=True)
class Topology:
    nodes: tuple[TopologyNode, ...] = ()
    edges: tuple[TopologyEdge, ...] = ()
    failure_domains: tuple[FailureDomain, ...] = ()
    active_paths: tuple[ActivePath, ...] = ()
    mappings: tuple[AlarmResourceMapping, ...] = ()


@dataclass(frozen=True)
class OperationalContext:
    context_id: str
    context_type: ContextType
    affected_resources: tuple[str, ...]
    source_kind: SourceKind
    provenance_class: ProvenanceClass = ProvenanceClass.EXTERNAL_OPERATIONAL
    provenance_subtype: ProvenanceSubtype | None = None
    start_time: str | None = None
    end_time: str | None = None
    chaining_usage: ChainingUsageAssessment | None = None
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    generation: GenerationMetadata | None = None


@dataclass(frozen=True)
class SourceRecord:
    """One upstream source contributing to the package."""

    source_id: str
    source_kind: SourceKind
    source_version: str | None = None
    file_path: str | None = None
    record_count: int | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProvenanceManifest:
    """Declares every source and unavailable capability behind the package."""

    sources: tuple[SourceRecord, ...] = ()
    config_version: str | None = None
    generator_version: str | None = None
    unavailable_capabilities: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MockSnapshotPackage:
    """Complete snapshot package; the unit the Direct Snapshot Adapter accepts."""

    snapshot: Snapshot
    alarms: tuple[Alarm, ...] = ()
    chains: tuple[Chain, ...] = ()
    memberships: tuple[ChainMembership, ...] = ()
    system_metadata: SystemMetadata = field(default_factory=SystemMetadata)
    topology: Topology = field(default_factory=Topology)
    operational_context: tuple[OperationalContext, ...] = ()
    provenance_manifest: ProvenanceManifest = field(default_factory=ProvenanceManifest)
    schema_version: str = "v1"

    def to_dict(self) -> dict[str, Any]:
        from .serialization import package_to_dict

        return package_to_dict(self)

"""Versioned HTTP response models; analysis dataclasses never leak directly."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncrementalPolicyView(ApiModel):
    mode: str
    reason: str


class SnapshotLoadedView(ApiModel):
    snapshot_id: str
    snapshot_version: str
    alarm_count: int
    chain_count: int
    incremental_snapshot: IncrementalPolicyView


class ChainSummaryView(ApiModel):
    chain_id: str
    member_count: int
    is_singleton: bool
    title: str


class ChainListView(ApiModel):
    snapshot_id: str
    snapshot_version: str
    chains: list[ChainSummaryView]


class DescriptorView(ApiModel):
    kind: str
    label: str
    coverage: float
    precision_global: float
    precision_local: float | None
    false_positive_rate: float
    lift: float | None
    f1: float


class GroupFitView(ApiModel):
    derivation_tag: str
    fit: float | None
    channels: list[str]


class MarginView(ApiModel):
    compared_chain_id: str
    margin: float | None
    computable_groups: int


class MemberView(ApiModel):
    alarm_id: str
    alarm_name: str | None
    device_code: str | None
    node_reference: str | None
    canonical_start_time: str | None
    role: str
    membership_support: float | None
    availability_coverage: float
    computable_groups: int
    representativeness: float | None
    group_fits: list[GroupFitView]
    margins: list[MarginView]
    redundancy_role: str | None
    failure_domains: list[str]


class GrayBoxView(ApiModel):
    mode: str
    merge_strategy: str | None
    rules: int
    characteristics: int
    pair_facts: int
    unavailable_capabilities: list[str]


class ChainAnalysisView(ApiModel):
    chain_id: str
    title: str
    member_count: int
    singleton: bool
    statistics_mode: str
    audit_graph_mode: str
    pair_materialization: str
    config_version: str
    graybox: GrayBoxView
    descriptors: list[DescriptorView]
    members: list[MemberView]
    role_counts: dict[str, int]
    phase_durations: dict[str, float]


class PairEvidenceView(ApiModel):
    channel_family: str
    provider_id: str | None
    dependency_semantic: str | None
    state: str
    score: float | None
    threshold: float
    negative_score: float | None
    detail: str | None
    derivation_tag: str
    provenance_class: str
    provenance_subtype: str | None
    source_ref: str | None


class SystemPairFactView(ApiModel):
    status: str
    attribute_ref: str | None = None
    raw_score: float | None = None
    semantic: str | None = None


class PairWhyView(ApiModel):
    chain_id: str
    alarm_id_a: str
    alarm_id_b: str
    evidence: list[PairEvidenceView]
    system_fact: SystemPairFactView


class JobSubmissionView(ApiModel):
    job_id: str
    cache_hit: bool
    deduplicated: bool


class StructuralAuditView(ApiModel):
    verdict: str
    reason: str
    epsilon: float | None
    best_cut_label: str | None
    best_cut_phi: float | None


class DominatorView(ApiModel):
    status: str
    reason: str | None
    semantic: str | None
    witness_resource_id: str | None
    covered_resource_ids: list[str]
    source_ref: str | None
    relation_type: str | None
    provenance_class: str | None
    provenance_subtype: str | None
    source_kind: str | None


class PropagationDiagnosticsView(ApiModel):
    candidate_node_count: int
    candidate_edge_count: int
    iterations: int
    final_l1_distance: float | None
    convergence_tolerance: float | None
    restart_probability: float | None
    seed_policy: str | None
    dangling_policy: str | None
    config_version: str | None
    parameter_provenance: dict[str, str]


class PropagationNodeScoreView(ApiModel):
    alarm_id: str
    score: float


class PropagationEdgeHypothesisView(ApiModel):
    source_alarm_id: str
    target_alarm_id: str
    score: float
    transition_probability: float
    temporal_delta_seconds: float


class PropagationView(ApiModel):
    status: str
    reason: str | None
    semantic: str | None
    source_ref: str | None
    relation_type: str | None
    provenance_class: str | None
    provenance_subtype: str | None
    source_kind: str | None
    config_version: str | None
    parameter_provenance: dict[str, str]
    diagnostics: PropagationDiagnosticsView
    node_scores: list[PropagationNodeScoreView]
    hypotheses: list[PropagationEdgeHypothesisView]


class ResourceDetailsView(ApiModel):
    status: str
    reason: str | None
    missing_resources: list[str] | None
    extra_resources: list[str] | None


class DependencyScopeView(ApiModel):
    status: str
    reason: str | None
    semantic: str | None
    witness_resource_id: str | None
    source_ref: str | None
    relation_type: str | None
    provenance_class: str | None
    provenance_subtype: str | None
    source_kind: str | None
    observed_resource_count: int | None
    scope_resource_count: int | None
    intersection_count: int | None
    union_count: int | None
    observed_coverage: float | None
    scope_precision: float | None
    jaccard: float | None
    missing_resource_count: int | None
    extra_resource_count: int | None
    max_scope_resources: int | None
    max_materialized_resources: int | None
    parameter_provenance: dict[str, str]
    resource_details: ResourceDetailsView


class TopologyHypothesesView(ApiModel):
    dominator: DominatorView
    propagation: PropagationView
    dependency_scope: DependencyScopeView


class DeepDiveView(ApiModel):
    chain_id: str
    audit_graph_mode: str
    structural_audit: StructuralAuditView
    over_merge_strength: str
    over_merge_narrative: str
    similar_chains: list[dict[str, Any]]
    similarity_status: str
    similarity_unavailable_reason: str | None
    similarity_model_version: str | None
    similarity_trained_until_exclusive: str | None
    similarity_corpus_policy: str | None
    similarity_model_update_policy: str | None
    taxonomy_status: str | None
    taxonomy_reason: str | None
    active_fingerprint_blocks: list[str]
    topology_hypotheses: TopologyHypothesesView


class JobView(ApiModel):
    job_id: str
    chain_id: str
    status: str
    progress_percent: int = Field(ge=0, le=100)
    cache_hit: bool
    result: DeepDiveView | None
    error: str | None

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


class DeepDiveView(ApiModel):
    chain_id: str
    audit_graph_mode: str
    structural_audit: StructuralAuditView
    over_merge_strength: str
    over_merge_narrative: str
    similar_chains: list[dict[str, Any]]
    similarity_unavailable_reason: str | None


class JobView(ApiModel):
    job_id: str
    chain_id: str
    status: str
    progress_percent: int = Field(ge=0, le=100)
    cache_hit: bool
    result: DeepDiveView | None
    error: str | None

"""Versioned HTTP response models; analysis dataclasses never leak directly."""

from __future__ import annotations

from typing import Any, Literal

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


class SnapshotCatalogItemView(ApiModel):
    snapshot_id: str
    name: str
    profile: Literal["IP_NETWORK", "IT_SERVICES", "ALARM_ONLY"]
    alarm_count: int
    chain_count: int
    description: str
    badge: str


class SnapshotCatalogListView(ApiModel):
    active_snapshot_id: str | None = None
    active_snapshot_version: str | None = None
    snapshots: list[SnapshotCatalogItemView]


class SelectSnapshotRequest(ApiModel):
    snapshot_id: str


class ChainSummaryView(ApiModel):
    chain_id: str
    member_count: int
    is_singleton: bool
    title: str
    start_time: str | None
    end_time: str | None
    duration_seconds: float | None


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
    unavailable_reasons: dict[str, str] = Field(default_factory=dict)


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
    threshold: float | None
    negative_score: float | None
    detail: str | None
    derivation_tag: str
    provenance_class: str
    provenance_subtype: str | None
    source_ref: str | None
    source_id: str | None
    source_version: str | None
    scenario_id: str | None
    generator_version: str | None
    evidence_metadata: dict[str, Any] | None = None


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


class EvolutionNodeView(ApiModel):
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    snapshot_time: str
    lineage_component_id: str
    branch_id: str
    source_kind: str | None


class EvolutionEdgeView(ApiModel):
    parent_snapshot_id: str
    parent_snapshot_version: str
    parent_chain_id: str
    child_snapshot_id: str
    child_snapshot_version: str
    child_chain_id: str
    event_type: str
    overlap_count: int
    contain_parent: float
    contain_child: float


class EvolutionView(ApiModel):
    status: str
    reason: str | None
    source_kind: str | None
    sequence_status: str
    production_validation: str
    lineage_component_id: str | None
    branch_id: str | None
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    nodes: list[EvolutionNodeView]
    edges: list[EvolutionEdgeView]


class StructuralAuditView(ApiModel):
    verdict: str
    reason: str
    epsilon: float | None
    best_cut_label: str | None
    best_cut_phi: float | None


class AuditVisualizationNodeView(ApiModel):
    alarm_id: str
    weighted_degree: float
    cut_side: Literal["A", "B", "NONE"]
    structural_role: str | None


class AuditVisualizationEdgeView(ApiModel):
    source_alarm_id: str
    target_alarm_id: str
    weight: float
    supporting_groups: list[str]
    crosses_best_cut: bool


class AuditVisualizationView(ApiModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    reason: str | None
    projection_version: str
    selection_strategy: str
    max_nodes: int
    max_edges: int
    total_node_count: int
    shown_node_count: int
    hidden_node_count: int
    total_edge_count: int
    shown_edge_count: int
    hidden_edge_count: int
    truncated: bool
    nodes: list[AuditVisualizationNodeView]
    edges: list[AuditVisualizationEdgeView]


class AuditVisualizationArtifactView(ApiModel):
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    audit_artifact_id: str | None
    audit_artifact_fingerprint: str | None
    visualization: AuditVisualizationView


class DominatorView(ApiModel):
    status: str
    reason: str | None
    semantic: str | None
    witness_resource_id: str | None
    covered_resource_ids: list[str]
    source_ref: str | None
    source_id: str | None
    source_version: str | None
    scenario_id: str | None
    generator_version: str | None
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
    source_id: str | None
    source_version: str | None
    scenario_id: str | None
    generator_version: str | None
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
    source_id: str | None
    source_version: str | None
    scenario_id: str | None
    generator_version: str | None
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


class EvidenceCoverageContributionView(ApiModel):
    group_id: str
    derivation_tag: str
    provenance_class: str
    explain_eligible: bool
    role_eligible: bool
    audit_eligible: bool
    behavioral: bool
    supported_pair_count: int
    attribution: float


class EvidenceCoverageAttributionView(ApiModel):
    status: str
    mode: str
    reason: str | None
    detail: str | None
    chain_size: int
    exact_max_members: int
    total_pair_count: int
    covered_pair_count: int | None
    total_coverage: float | None
    contributions: list[EvidenceCoverageContributionView]


class AttributionDeletionCurveView(ApiModel):
    ordering: list[str]
    coverage_curve: list[float]
    auc: float | None


class AttributionRandomBaselineView(ApiModel):
    algorithm: str
    seed: int | None
    repetitions: int | None
    repetitions_executed: int
    mean_curve: list[float]
    std_curve: list[float]
    mean_auc: float | None
    std_auc: float | None


class AttributionDeletionEvaluationView(ApiModel):
    status: str
    mode: str
    reason: str | None
    group_count: int
    primary: AttributionDeletionCurveView
    reverse: AttributionDeletionCurveView
    random: AttributionRandomBaselineView
    delta_vs_random_auc: float | None
    delta_vs_reverse_auc: float | None


class DeepDiveView(ApiModel):
    chain_id: str
    audit_graph_mode: str
    structural_audit: StructuralAuditView
    audit_visualization: AuditVisualizationView
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
    evidence_attribution: EvidenceCoverageAttributionView
    evidence_attribution_evaluation: AttributionDeletionEvaluationView


class JobView(ApiModel):
    job_id: str
    chain_id: str
    status: str
    progress_percent: int = Field(ge=0, le=100)
    cache_hit: bool
    result: DeepDiveView | None
    error: str | None


class ReviewIdentityView(ApiModel):
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    alarm_universe_fingerprint: str
    analysis_version: str
    engine_version: str
    config_version: str
    tier1b_artifact_fingerprint: str
    structural_audit_artifact_fingerprint: str | None
    external_validation_artifact_fingerprint: str | None


class CounterfactualMetricValueView(ApiModel):
    availability: str
    value: float | int | None
    reason: str | None


class CounterfactualMetricVectorView(ApiModel):
    weak_member_count: CounterfactualMetricValueView
    minimum_membership_support: CounterfactualMetricValueView
    evidence_union_coverage: CounterfactualMetricValueView
    component_count: CounterfactualMetricValueView
    audit_conductance: CounterfactualMetricValueView
    audit_verdict_severity: CounterfactualMetricValueView
    eligible_external_contradiction_count: CounterfactualMetricValueView


class CounterfactualEditCostView(ApiModel):
    operation_count: int
    membership_reassignments: int
    affected_member_count: int


class CounterfactualPartitionView(ApiModel):
    before: list[tuple[str, list[str]]]
    after: list[tuple[str, list[str]]]


class MoveStructuralFactsView(ApiModel):
    before_structural_role: str
    after_structural_role: str
    after_is_articulation_point: bool
    after_blocks_supported: int


class CounterfactualCandidateView(ApiModel):
    candidate_id: str
    operation: str
    member_ids: list[str]
    source_chain_id: str | None
    target_chain_id: str | None
    merged_chain_ids: list[str] | None
    merge_evidence: dict[str, object] | None
    source_ref: str
    status: str
    reason: str | None
    edit_cost: CounterfactualEditCostView
    partition_delta: CounterfactualPartitionView
    before: CounterfactualMetricVectorView | None
    after: CounterfactualMetricVectorView | None
    materially_improved_metrics: list[str]
    move_structural_facts: MoveStructuralFactsView | None
    semantic_effects: list[str]


class CounterfactualOperationView(ApiModel):
    operation: str
    status: str
    reason: str | None
    search_mode: str
    discovered_candidate_count: int
    evaluated_candidate_count: int
    rejected_candidate_count: int
    candidate_limit: int | None
    candidates: list[CounterfactualCandidateView]


class CounterfactualResultView(ApiModel):
    identity: ReviewIdentityView
    status: str
    reason: str | None
    recommendation_status: str
    remove: CounterfactualOperationView
    split: CounterfactualOperationView
    move: CounterfactualOperationView
    merge: CounterfactualOperationView
    recommendations: list[CounterfactualCandidateView]
    frontier_count_before_limit: int
    frontier_truncated: bool
    parameter_provenance: dict[str, str]


class CounterfactualJobView(ApiModel):
    job_id: str
    chain_id: str
    status: str
    progress_percent: int = Field(ge=0, le=100)
    cache_hit: bool
    cache_fingerprint: str
    identity: ReviewIdentityView
    # The Counterfactual artifact owns its explicitly versioned nested schema.
    result: dict[str, object] | None
    error: str | None


class OperatorFeedbackSubmission(ApiModel):
    candidate_id: str
    decision: str
    operator_id: str = "viettel_operator"
    reason: str | None = None


class OperatorFeedbackView(ApiModel):
    feedback_id: str
    job_id: str
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    candidate_id: str
    operation: str
    decision: str
    operator_id: str
    reason: str | None = None
    partition_delta: dict[str, object]
    created_at: str


class AISuggestionView(ApiModel):
    chain_id: str
    status: str
    model: str
    narrative: str
    grounded_claims: list[str]
    disclaimer: str
    provider_status: str | None = None
    review_status: str
    review_reason: str | None = None


class CohesionNarrativeView(ApiModel):
    chain_id: str
    narrative: str
    model: str
    provider_status: str | None = None
    context: dict[str, Any]


class AssistantContextInput(ApiModel):
    snapshot_id: str = Field(min_length=1)
    snapshot_version: str = Field(min_length=1)
    page: str | None = None
    chain_id: str | None = None
    alarm_id: str | None = None
    pair_alarm_id_a: str | None = None
    pair_alarm_id_b: str | None = None
    selected_metric: str | None = None
    topology_resource_id: str | None = None
    selection: dict[str, str] | None = None
    filters: dict[str, str] = Field(default_factory=dict)


class AssistantHistoryMessageInput(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2_000)


class AssistantQueryInput(ApiModel):
    query: str = Field(max_length=500)
    context: AssistantContextInput
    history: list[AssistantHistoryMessageInput] = Field(default_factory=list, max_length=8)


class AssistantNavigationTargetView(ApiModel):
    """Identity-bound destination for a read-only assistant navigation action."""

    snapshot_id: str = Field(min_length=1)
    snapshot_version: str = Field(min_length=1)
    tab: str
    chain_id: str | None = None
    pair_alarm_id_a: str | None = None
    pair_alarm_id_b: str | None = None


class AssistantActionView(ApiModel):
    kind: Literal["NAVIGATE"]
    label: str
    target: AssistantNavigationTargetView


class AssistantResponseView(ApiModel):
    contract_version: str
    status: str
    message: str
    fact_refs: list[str]
    actions: list[AssistantActionView]
    model: str
    provider_status: str
    response_mode: Literal["LLM_PRIMARY", "DETERMINISTIC_FALLBACK"] = "DETERMINISTIC_FALLBACK"
    tools_used: list[str] = Field(default_factory=list)
    chart_data: dict[str, Any] | None = None


class ParameterItemView(ApiModel):
    path: str
    key: str
    label: str
    value: float | int
    source: str
    min: float | None = None
    max: float | None = None
    step: float | None = None
    description: str | None = None


class ConfigView(ApiModel):
    config_version: str
    status: str
    editable_parameters: dict[str, float | int]
    parameters_detail: list[ParameterItemView]


class ConfigUpdateInput(ApiModel):
    parameters: dict[str, float | int]


class ParameterCalibrationView(ApiModel):
    path: str
    previous_value: float | int
    calibrated_value: float | int
    source: str
    sample_count: int
    metric_details: dict[str, Any]


class CalibrationReportView(ApiModel):
    timestamp: str
    database_url_masked: str
    snapshots_loaded: int
    chains_evaluated: int
    alarms_evaluated: int
    calibrated_parameters: list[ParameterCalibrationView]
    output_config_path: str
    status: str

export type WhyScope = 'Chain' | 'Member' | 'Pair' | 'Group'

export type ChainSummary = {
  chain_id: string
  member_count: number
  is_singleton: boolean
  title: string
  start_time: string | null
  end_time: string | null
  duration_seconds: number | null
}

export type ChainList = {
  snapshot_id: string
  snapshot_version: string
  chains: ChainSummary[]
}

export type EvolutionNode = {
  snapshot_id: string
  snapshot_version: string
  chain_id: string
  snapshot_time: string
  lineage_component_id: string
  branch_id: string
  source_kind: string | null
}

export type EvolutionEdge = {
  parent_snapshot_id: string
  parent_snapshot_version: string
  parent_chain_id: string
  child_snapshot_id: string
  child_snapshot_version: string
  child_chain_id: string
  event_type: string
  overlap_count: number
  contain_parent: number
  contain_child: number
}

export type Evolution = {
  status: 'AVAILABLE' | 'UNAVAILABLE'
  reason: string | null
  source_kind: string | null
  sequence_status: 'VERIFIED' | 'UNAVAILABLE'
  production_validation: 'ELIGIBLE' | 'NOT_ESTABLISHED'
  lineage_component_id: string | null
  branch_id: string | null
  snapshot_id: string
  snapshot_version: string
  chain_id: string
  nodes: EvolutionNode[]
  edges: EvolutionEdge[]
}

export type Descriptor = {
  kind: string
  label: string
  coverage: number
  precision_global: number
  precision_local: number | null
  false_positive_rate: number
  lift: number | null
  f1: number
}

export type GroupFit = {
  derivation_tag: string
  fit: number | null
  channels: string[]
  unavailable_reasons: Record<string, string>
}

export type Member = {
  alarm_id: string
  alarm_name: string | null
  device_code: string | null
  node_reference: string | null
  canonical_start_time: string | null
  role: string
  membership_support: number | null
  availability_coverage: number
  computable_groups: number
  representativeness: number | null
  group_fits: GroupFit[]
  margins: Array<{
    compared_chain_id: string
    margin: number | null
    computable_groups: number
  }>
  redundancy_role: string | null
  failure_domains: string[]
}

export type ChainAnalysis = {
  chain_id: string
  title: string
  member_count: number
  singleton: boolean
  statistics_mode: string
  audit_graph_mode: string
  pair_materialization: string
  config_version: string
  graybox: {
    mode: string
    merge_strategy: string | null
    rules: number
    characteristics: number
    pair_facts: number
    unavailable_capabilities: string[]
  }
  descriptors: Descriptor[]
  members: Member[]
  role_counts: Record<string, number>
  phase_durations: Record<string, number>
}

export type PairEvidence = {
  channel_family: string
  provider_id: string | null
  dependency_semantic: string | null
  state: string
  score: number | null
  threshold: number | null
  negative_score: number | null
  detail: string | null
  derivation_tag: string
  provenance_class: string
  provenance_subtype: string | null
  source_ref: string | null
  source_id: string | null
  source_version: string | null
  scenario_id: string | null
  generator_version: string | null
  evidence_metadata: Record<string, unknown> | null
}

export type PairWhy = {
  chain_id: string
  alarm_id_a: string
  alarm_id_b: string
  evidence: PairEvidence[]
  system_fact: {
    status: string
    attribute_ref: string | null
    raw_score: number | null
    semantic: string | null
  }
}

export type DeepDive = {
  chain_id: string
  audit_graph_mode: string
  structural_audit: {
    verdict: string
    reason: string
    epsilon: number | null
    best_cut_label: string | null
    best_cut_phi: number | null
  }
  audit_visualization: AuditVisualization
  over_merge_strength: string
  over_merge_narrative: string
  similar_chains: Array<{
    chain_id: string
    similarity: number
    lineage_component_id: string | null
    compared_blocks: string[]
  }>
  similarity_status: string
  similarity_unavailable_reason: string | null
  similarity_model_version: string | null
  similarity_trained_until_exclusive: string | null
  similarity_corpus_policy: string | null
  similarity_model_update_policy: string | null
  taxonomy_status: string | null
  taxonomy_reason: string | null
  active_fingerprint_blocks: string[]
  topology_hypotheses: TopologyHypothesesResult
  evidence_attribution: EvidenceCoverageAttributionResult
  evidence_attribution_evaluation: AttributionDeletionEvaluationResult
}

export type AuditVisualization = {
  status: 'AVAILABLE' | 'UNAVAILABLE'
  reason: string | null
  projection_version: string
  selection_strategy: string
  max_nodes: number
  max_edges: number
  total_node_count: number
  shown_node_count: number
  hidden_node_count: number
  total_edge_count: number
  shown_edge_count: number
  hidden_edge_count: number
  truncated: boolean
  nodes: Array<{
    alarm_id: string
    weighted_degree: number
    cut_side: 'A' | 'B' | 'NONE'
    structural_role: string | null
  }>
  edges: Array<{
    source_alarm_id: string
    target_alarm_id: string
    weight: number
    supporting_groups: string[]
    crosses_best_cut: boolean
  }>
}

export type AuditVisualizationArtifact = {
  snapshot_id: string
  snapshot_version: string
  chain_id: string
  audit_artifact_id: string | null
  audit_artifact_fingerprint: string | null
  visualization: AuditVisualization
}

export type EvidenceCoverageAttributionResult = {
  status: 'AVAILABLE' | 'UNAVAILABLE' | 'NOT_APPLICABLE'
  mode: 'EXACT' | 'UNAVAILABLE'
  reason: string | null
  detail: string | null
  chain_size: number
  exact_max_members: number
  total_pair_count: number
  covered_pair_count: number | null
  total_coverage: number | null
  contributions: Array<{
    group_id: string
    derivation_tag: string
    provenance_class: string
    explain_eligible: boolean
    role_eligible: boolean
    audit_eligible: boolean
    behavioral: boolean
    supported_pair_count: number
    attribution: number
  }>
}

export type AttributionDeletionEvaluationResult = {
  status: 'AVAILABLE' | 'UNAVAILABLE' | 'NOT_APPLICABLE'
  mode: 'EXACT' | 'UNAVAILABLE'
  reason: string | null
  group_count: number
  primary: {
    ordering: string[]
    coverage_curve: number[]
    auc: number | null
  }
  reverse: {
    ordering: string[]
    coverage_curve: number[]
    auc: number | null
  }
  random: {
    algorithm: string
    seed: number | null
    repetitions: number | null
    repetitions_executed: number
    mean_curve: number[]
    std_curve: number[]
    mean_auc: number | null
    std_auc: number | null
  }
  delta_vs_random_auc: number | null
  delta_vs_reverse_auc: number | null
}

export type Job = {
  job_id: string
  chain_id: string
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'INTERRUPTED'
  progress_percent: number
  cache_hit: boolean
  result: DeepDive | null
  error: string | null
}

export type CounterfactualMetricValue = {
  availability: 'AVAILABLE' | 'UNAVAILABLE' | 'NOT_APPLICABLE'
  value: number | null
  reason: string | null
}

export type CounterfactualMetricVector = {
  weak_member_count: CounterfactualMetricValue
  minimum_membership_support: CounterfactualMetricValue
  evidence_union_coverage: CounterfactualMetricValue
  component_count: CounterfactualMetricValue
  audit_conductance: CounterfactualMetricValue
  audit_verdict_severity: CounterfactualMetricValue
  eligible_external_contradiction_count: CounterfactualMetricValue
}

export type DeltaHighlight = {
  metric_name: string
  label: string
  before: string
  after: string
  delta: string
  direction: 'better' | 'worse' | 'neutral'
}

export type ComparativeExplanation = {
  operation: string
  summary_action: string
  why_better: string
  comparison_points: string[]
  delta_highlights: DeltaHighlight[]
  ai_narrative?: string | null
  language?: string
}

export type CounterfactualCandidate = {
  candidate_id: string
  operation: 'REMOVE_MEMBER' | 'SPLIT_CHAIN' | 'MOVE_MEMBER' | 'MERGE_CHAINS' | 'ADD_MEMBER'
  member_ids: string[]
  source_chain_id: string | null
  target_chain_id: string | null
  merged_chain_ids: string[] | null
  merge_evidence: {
    cross_pair_count: number
    cross_available_counts_by_group: Array<{
      derivation_tag: string
      provenance_class: string
      available_count: number
      support_count: number
      cross_fit: number | null
    }>
    cross_audit_edge_count: number
    cross_audit_edge_coverage: number
    cross_supported_group_count: number
    cross_evidence_union_coverage: number
  } | null
  source_ref: string
  status: string
  reason: string | null
  edit_cost: {
    operation_count: number
    membership_reassignments: number
    affected_member_count: number
  }
  partition_delta: {
    before: Array<[string, string[]]>
    after: Array<[string, string[]]>
  }
  before: CounterfactualMetricVector | null
  after: CounterfactualMetricVector | null
  materially_improved_metrics: string[]
  move_structural_facts: {
    before_structural_role: string
    after_structural_role: string
    after_is_articulation_point: boolean
    after_blocks_supported: number
  } | null
  semantic_effects: string[]
  evaluation_status?: string
  debug_source_ref?: string
  before_metrics?: CounterfactualMetricVector | null
  after_metrics?: CounterfactualMetricVector | null
  structural_facts?: {
    before_structural_role: string
    after_structural_role: string
    after_is_articulation_point: boolean
    after_blocks_supported: number
  } | null
  operation_specific_evidence?: Record<string, unknown>
  metric_deltas?: Record<string, number>
  hard_gate_result?: { status: string; reason: string | null }
  hard_gate_passed?: boolean
  pareto_state?: string
  external_validation?: string
  comparative_explanation?: ComparativeExplanation | null
  ranking_audit?: {
    ranking_status: 'RERANKED' | 'ABSTAINED' | 'UNAVAILABLE'
    model_score?: number | null
    margin?: number | null
    abstention_threshold?: number | null
    abstention_reason?: string | null
    ranker_version?: string | null
    artifact_fingerprint?: string | null
  } | null
  displayed_rank?: number | null
}

export type FeatureImportance = {
  feature: string
  importance: number
  description: string
}

export type ReviewLearningStatus = {
  loaded: boolean
  model_version: string | null
  model_family: string | null
  approval_status: string | null
  feature_schema_version: string | null
  label_policy_version: string | null
  abstention_threshold: number
  artifact_sha256: string | null
  created_at: string | null
  training_cutoff: string | null
  hyperparameters: Record<string, any>
  metrics: {
    ndcg_1?: number
    ndcg_3?: number
    ndcg_5?: number
    top1_approved_recall?: number
    top3_approved_recall?: number
    baseline_ndcg_3?: number
    ndcg_improvement?: number
    mean_regret?: number
    confidence_intervals?: Record<string, [number, number]>
    [key: string]: any
  }
  feature_importances: FeatureImportance[]
  data_profile?: {
    total_groups?: number
    total_candidates?: number
    total_positives?: number
    total_negatives?: number
    operation_coverage?: Record<string, number>
    truth_tier_distribution?: Record<string, number>
    splits?: Record<string, any>
  } | null
  feedback_summary: {
    active_feedback_count: number
    superseded_feedback_count: number
    action_counts: Record<string, number>
  }
  disclaimer: string
  training_stdout?: string
}

export type CounterfactualOperation = {
  operation: 'REMOVE_MEMBER' | 'SPLIT_CHAIN' | 'MOVE_MEMBER' | 'MERGE_CHAINS' | 'ADD_MEMBER'
  status: 'AVAILABLE' | 'UNAVAILABLE' | 'NOT_APPLICABLE' | 'BLOCKED'
  reason: string | null
  search_mode: 'BOUNDED' | 'NOT_RUN'
  discovered_candidate_count: number
  evaluated_candidate_count: number
  rejected_candidate_count: number
  candidate_limit: number | null
  candidates: CounterfactualCandidate[]
}

export type CounterfactualResult = {
  contract_version?: string
  calibration_status?: string | null
  identity: {
    snapshot_id: string
    snapshot_version: string
    chain_id: string
    alarm_universe_fingerprint: string
    analysis_version: string
    engine_version: string
    config_version: string
    tier1b_artifact_fingerprint: string
    structural_audit_artifact_fingerprint: string | null
    external_validation_artifact_fingerprint: string | null
  }
  status: 'AVAILABLE' | 'UNAVAILABLE' | 'NOT_APPLICABLE'
  reason: string | null
  recommendation_status: 'AVAILABLE' | 'UNAVAILABLE' | 'NO_CLEAR_ALTERNATIVE'
  remove: CounterfactualOperation
  split: CounterfactualOperation
  move: CounterfactualOperation
  merge: CounterfactualOperation
  recommendations: CounterfactualCandidate[]
  frontier_count_before_limit: number
  frontier_truncated: boolean
  parameter_provenance: Record<string, string>
  operation_status?: Record<string, {
    status: string
    reason: string | null
    search_mode: string
    candidate_count: number
    evaluated_count: number
    ceiling: number | null
  }>
  evaluated_candidates?: CounterfactualCandidate[]
  frontier?: { count_before_limit: number; selected_count: number; truncated: boolean }
}

export type CounterfactualJob = {
  job_id: string
  chain_id: string
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  progress_percent: number
  cache_hit: boolean
  cache_fingerprint: string
  identity: CounterfactualResult['identity']
  result: CounterfactualResult | null
  error: string | null
}

export type TopologyHypothesisStatus = 'AVAILABLE' | 'UNAVAILABLE'

type TopologyProvenance = {
  source_ref: string | null
  source_id: string | null
  source_version: string | null
  scenario_id: string | null
  generator_version: string | null
  relation_type: string | null
  provenance_class: string | null
  provenance_subtype: string | null
  source_kind: string | null
}

export type DominatorResult = TopologyProvenance & {
  status: 'AVAILABLE'
  reason: null
  semantic: string
  witness_resource_id: string | null
  covered_resource_ids: string[]
} | TopologyProvenance & {
  status: 'UNAVAILABLE'
  reason: string
  semantic: string | null
  witness_resource_id: string | null
  covered_resource_ids: string[]
}

export type PropagationNodeScore = {
  alarm_id: string
  score: number
}

export type PropagationEdgeHypothesis = {
  source_alarm_id: string
  target_alarm_id: string
  score: number
  transition_probability: number
  temporal_delta_seconds: number
}

type PropagationResultBase = TopologyProvenance & {
  config_version: string | null
  parameter_provenance: Record<string, string>
  candidate_node_count: number
  candidate_edge_count: number
  iterations: number
  final_l1_distance: number | null
  convergence_tolerance: number | null
  restart_probability: number | null
  seed_policy: string | null
  dangling_policy: string | null
  node_scores: PropagationNodeScore[]
  hypotheses: PropagationEdgeHypothesis[]
}

export type PropagationResult = PropagationResultBase & {
  status: 'AVAILABLE'
  reason: null
  semantic: string
} | PropagationResultBase & {
  status: 'UNAVAILABLE'
  reason: string
  semantic: string | null
}

export type ResourceDetails = {
  status: 'AVAILABLE'
  reason: null
  missing_resources: string[]
  extra_resources: string[]
} | {
  status: 'UNAVAILABLE'
  reason: string
  missing_resources: null
  extra_resources: null
}

type DependencyScopeResultBase = TopologyProvenance & {
  witness_resource_id: string | null
  observed_resource_count: number | null
  scope_resource_count: number | null
  intersection_count: number | null
  union_count: number | null
  observed_coverage: number | null
  scope_precision: number | null
  jaccard: number | null
  missing_resource_count: number | null
  extra_resource_count: number | null
  max_scope_resources: number | null
  max_materialized_resources: number | null
  parameter_provenance: Record<string, string>
  resource_details: ResourceDetails
}

export type DependencyScopeResult = DependencyScopeResultBase & {
  status: 'AVAILABLE'
  reason: null
  semantic: string
} | DependencyScopeResultBase & {
  status: 'UNAVAILABLE'
  reason: string
  semantic: string | null
}

export type TopologyHypothesesResult = {
  dominator: DominatorResult
  propagation: PropagationResult
  dependency_scope: DependencyScopeResult
}

export type ReviewDecision =
  | 'APPROVE'
  | 'REJECT'
  | 'DEFER'
  | 'INSUFFICIENT_EVIDENCE'
  | 'NONE_ACCEPTABLE'
  | 'MANUAL_CORRECTION'
  | 'APPROVED'
  | 'REJECTED'

export type ReviewReasonItem = {
  code: string
  label: string
  description: string
}

export type ReasonPolicy = {
  policy_version: string
  description: string
  reasons_by_decision: Record<string, ReviewReasonItem[]>
}

export type BlockScoreDetail = {
  status: 'AVAILABLE' | 'UNAVAILABLE'
  score: number | null
}

export type SimilarReviewCase = {
  case_id: string
  review_id: string
  candidate_id: string
  decision: string
  truth_tier: string
  similarity_score: number
  common_block_count: number
  block_scores: Record<string, BlockScoreDetail | number>
  lineage_component_id?: string | null
  disclaimer: string
}

export type SimilarCaseRetrievalResult = {
  retrieval_status: 'AVAILABLE' | 'UNAVAILABLE'
  min_similarity: number
  reason?: string | null
  common_block_count?: number
  required_common_block_count?: number
  cross_incident_cases: SimilarReviewCase[]
  same_lineage_history: SimilarReviewCase[]
  disclaimer: string
}

export type ManualCorrectionPayload = {
  operation: string
  partition_delta: {
    before?: [string, string[]][]
    after?: [string, string[]][]
  }
  edit_summary?: string
}

export type CandidateDisplayEventItem = {
  candidate_id: string
  displayed_rank: number
  rendered_at: string
  exposure_policy?: string
  surface?: string
  viewer_session_id?: string
  client_event_id?: string
}

export type OperatorFeedback = {
  feedback_id: string
  job_id: string
  chain_id: string
  candidate_id: string | null
  operation: string
  decision: ReviewDecision
  operator_id: string
  confidence?: number | null
  reviewer_subject?: string | null
  reviewer_role?: string | null
  domain_scope?: string[]
  truth_tier?: string
  supersedes_feedback_id?: string | null
  reason?: string | null
  reason_policy_version?: string | null
  reason_codes?: string[]
  partition_delta?: {
    before?: [string, string[]][]
    after?: [string, string[]][]
  }
  has_manual_correction?: boolean
  created_at: string
}

export type AISuggestion = {
  chain_id: string
  status: 'AVAILABLE' | 'FALLBACK' | 'ERROR'
  model: string
  narrative: string
  grounded_claims: string[]
  disclaimer: string
  provider_status?: string | null
  review_status: 'AVAILABLE' | 'NOT_AVAILABLE' | 'UNAVAILABLE'
  review_reason?: string | null
}

export type CohesionNarrativeView = {
  chain_id: string
  narrative: string
  model: string
  provider_status?: string | null
  context: {
    chain: {
      chain_id: string
      alarm_count: number
      duration_seconds: number
      is_singleton: boolean
    }
    alarm_summary: {
      top_alarm_types: [string, number][]
      network_classes: string[]
      device_types: string[]
      devices: string[]
    }
    why: {
      strong_views: string[]
      partial_views: string[]
      top_descriptors: string[]
    }
    topology: {
      mapped: number
      total: number
      resource_types: string[]
      dependency_verified: boolean
    }
    audit: {
      status: string
      candidate_cut: boolean
      conductance: number | null
    }
    recommendations: {
      split_recommended: boolean
    }
  }
}

export type AssistantAction = {
  kind: 'NAVIGATE'
  label: string
  target: {
    snapshot_id: string
    snapshot_version: string
    chain_id?: string | null
    tab: string
    pair_alarm_id_a?: string | null
    pair_alarm_id_b?: string | null
  }
}

export type AssistantResponse = {
  contract_version: 'nocpro-assistant-v1'
  status: 'AVAILABLE' | 'NO_FINDING' | 'STALE_CONTEXT' | 'UNAVAILABLE'
  message: string
  fact_refs: string[]
  actions: AssistantAction[]
  model: string
  provider_status: string
  response_mode: 'LLM_PRIMARY' | 'DETERMINISTIC_FALLBACK'
  tools_used: string[]
  chart_data?: Record<string, unknown> | null
}

export type AssistantHistoryMessage = {
  role: 'user' | 'assistant'
  content: string
}

export type AssistantSelection =
  | { kind: 'metric'; metric_id: string }
  | { kind: 'alarm'; alarm_id: string }
  | { kind: 'pair'; alarm_id_a: string; alarm_id_b: string }
  | { kind: 'topology-resource'; resource_id: string }

export type AssistantContext = {
  snapshot_id: string
  snapshot_version: string
  page: string
  chain_id?: string
  alarm_id?: string
  pair_alarm_id_a?: string
  pair_alarm_id_b?: string
  selected_metric?: string
  topology_resource_id?: string
  selection?: AssistantSelection
  filters: Record<string, string>
}

export type ParameterItem = {
  path: string
  key: string
  label: string
  value: number
  source: string
  min?: number
  max?: number
  step?: number
  description?: string
}

export type AnalysisConfigView = {
  config_version: string
  status: string
  editable_parameters: Record<string, number>
  parameters_detail: ParameterItem[]
}

export type ParameterCalibration = {
  path: string
  previous_value: number
  calibrated_value: number
  source: string
  sample_count: number
  metric_details: Record<string, any>
}

export type CalibrationReport = {
  timestamp: string
  database_url_masked: string
  snapshots_loaded: number
  chains_loaded?: number
  chains_evaluated: number
  alarms_evaluated: number
  calibrated_parameters: ParameterCalibration[]
  output_config_path: string
  status: string
  chains_skipped_large?: number
  chains_failed?: number
}

export type ProposalClarityItem = {
  candidate_id: string
  operation: string
  summary_action: string
  explanation_text: string
  clarity_score: number
  causal_grounding: number
  operational_safety: number
  clarity_rank: number
  is_top_pick: boolean
  key_strengths: string[]
}

export type HeadToHeadComparison = {
  target_candidate_id: string
  target_operation: string
  target_clarity_score: number
  top_candidate_id: string
  top_operation: string
  top_clarity_score: number
  score_advantage: number
  why_top_is_clearer: string[]
  summary_verdict: string
}

export type ProposalClarityComparison = {
  job_id: string
  proposals: ProposalClarityItem[]
  top_proposal_id: string | null
  top_proposal_operation: string | null
  head_to_head_comparisons: HeadToHeadComparison[]
  overall_recommendation_rationale: string
}

export type ThresholdSweepResult = {
  parameters: Record<string, number>
  label: string
  explanation: string
  clarity_score: number
  weak_count: number
  core_count: number
}

export type ThresholdExplainOptimization = {
  chain_id: string
  current_parameters: Record<string, number>
  optimal_parameters: Record<string, number>
  current_clarity_score: number
  optimal_clarity_score: number
  clarity_gain: number
  current_explanation: string
  optimal_explanation: string
  winner: string
  why_clearer: string[]
  summary_verdict: string
  sweep_results: ThresholdSweepResult[]
}


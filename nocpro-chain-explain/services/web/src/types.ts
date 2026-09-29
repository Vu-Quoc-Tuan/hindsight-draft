export type WhyScope = 'Chain' | 'Member' | 'Pair' | 'Group'

export type AnalysisIdentity = {
  identity_version: 'analysis-identity-v1'
  snapshot_id: string
  snapshot_version: string
  chain_id: string
  topology_version: string | null
  analysis_config_version: string
  review_config_version: string | null
  pipeline_version: string
  input_fingerprint: string
}

export type ArtifactRevision = {
  resource_kind: string
  fingerprint: string
}

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
  topology_version?: string | null
  chains: ChainSummary[]
}

export type RecurrentAlarmSnapshotRef = {
  snapshot_id: string
  snapshot_version: string
}

export type RecurrentAlarmOccurrence = {
  source_id: string
  alarm_id: string
  occurred_at: string
  snapshots: RecurrentAlarmSnapshotRef[]
}

export type RecurrentAlarmGroup = {
  device_code: string
  fault_id: string
  count: number
  first_seen: string
  last_seen: string
  occurrences: RecurrentAlarmOccurrence[]
  occurrences_truncated: boolean
}

export type RecurrentAlarmHistory = {
  snapshot_id: string
  snapshot_version: string
  chain_id: string
  profile_id: string | null
  source_id: string | null
  history_scope: 'MATCHING_PERSISTED_SNAPSHOTS' | 'ACTIVE_SNAPSHOT_ONLY'
  history_issue: string | null
  snapshot_count: number
  assumed_utc_count: number
  unmatched_chain_alarm_count: number
  duplicate_observations: number
  conflicting_event_keys: number
  skipped_observations: number
  status: 'AVAILABLE' | 'UNAVAILABLE'
  reason: string | null
  groups: RecurrentAlarmGroup[]
}

export type ChainQualitySummary = {
  snapshot_id: string
  snapshot_version: string
  total_chain_count: number
  eligible_chain_count: number
  sturdy_count: number
  review_count: number
  evaluating_count: number
  unevaluated_count: number
  unavailable_count?: number
  not_applicable_count: number
  star_counts: Record<string, number>
  attention_chains: ChainQualityAssessment[]
  chain_assessments?: ChainQualityAssessment[]
}

export type ChainQualityAssessment = {
    chain_id: string
    member_count: number
    title: string
    duration_seconds: number | null
    status: 'EVALUATED' | 'REVIEW' | 'UNAVAILABLE' | 'EVALUATING' | 'WAITING' | 'NOT_APPLICABLE'
    stars: number | null
    label: string
    reason: string | null
    readiness?: 'READY' | 'PARTIAL' | 'INSUFFICIENT' | 'NOT_APPLICABLE' | string | null
    readiness_policy_version?: string | null
    reason_codes?: string[]
    evidence_coverage?: Record<string, unknown> | null
    evidence_ids?: string[]
    reason_evidence_ids?: Record<string, string[]>
    analysis_identity?: AnalysisIdentity | null
    artifact_revision?: ArtifactRevision | null
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

export type EvolutionEndpoint = {
  snapshot_id: string
  snapshot_version: string
  chain_id: string
}

export type EvolutionPredecessorChoice = {
  parent: EvolutionEndpoint
  event_type: string
  parent_source_kind: string | null
  child_source_kind: string | null
}

export type EvolutionReceiptChoice = {
  receipt_id: string
  artifact_revision: string
  created_at: string
}

export type EvolutionChanges = {
  status: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE'
  reason_codes: string[]
  parent: EvolutionEndpoint | null
  child: EvolutionEndpoint
  event_type: string | null
  parent_source_kind: string | null
  child_source_kind: string | null
  predecessor_choices: EvolutionPredecessorChoice[]
  predecessor_choices_truncated: boolean
  parent_receipt_choices: EvolutionReceiptChoice[]
  child_receipt_choices: EvolutionReceiptChoice[]
  parent_receipt_choices_truncated: boolean
  child_receipt_choices_truncated: boolean
  membership: {
    added_count: number
    removed_count: number
    retained_count: number
    added_alarm_ids: string[]
    removed_alarm_ids: string[]
    truncated: boolean
  } | null
  context_changes: Array<{ field: string; before: string | null; after: string | null }>
  quality: {
    comparable: boolean
    reason_codes: string[]
    before_score: number | null
    after_score: number | null
    before_stars: number | null
    after_stars: number | null
    delta: number | null
    before_receipt_id: string | null
    after_receipt_id: string | null
  }
  explanations: Array<{ code: string; text: string; evidence_ids: string[] }>
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

export type EntityResolution = {
  entity_role: string
  raw_value: string
  resource_id: string | null
  status: 'EXACT' | 'VERIFIED_ALIAS' | 'STRUCTURED_FIELD_UNIQUE' | 'TEXT_MATCH_CANDIDATE' | 'AMBIGUOUS' | 'UNMAPPED'
  method: string
  source_field?: string | null
  confidence?: number | null
  topology_profile_id?: string | null
  topology_version?: string | null
  candidate_resource_ids?: string[]
  matched_text?: string | null
  resolver_version?: string
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
  raw_content?: string | null
  content?: string | null
  start_time?: string | null
  end_time?: string | null
  duration_seconds?: number | null
  cleared?: boolean | null
  severity?: string | null
  extra_fields?: Record<string, any>
  observed_resource_id?: string | null
  entity_resolutions?: EntityResolution[]
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
  evidence_availability?: Record<string, { state: string; reason: string | null }>
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

export type TopologyPath = {
  source: string
  target: string
  source_devices?: string[]
  target_devices?: string[]
  hop_count: number
  max_hops?: number
  relation_type: string
  path: string[]
  mapping_statuses?: string[]
  traversal_semantic: string
}

export type EvidencePath = {
  resource_ids: string[]
  relation_types: string[]
  hop_count: number
  traversal_semantic: string
  max_hops: number
  topology_version: string
  mapping_statuses: string[]
  analysis_truncated: boolean
  direction_policy?: string | null
}

export type EvidenceRecord = {
  evidence_id: string
  analysis_identity: AnalysisIdentity
  kind: 'MAPPING' | 'TOPOLOGY_PATH' | 'AUDIT' | 'MEMBERSHIP' | 'REVIEW'
  status: 'AVAILABLE' | 'UNAVAILABLE' | 'NOT_EVALUATED'
  statement_kind: 'OBSERVED' | 'DERIVED'
  source_artifact_id: string | null
  source_fingerprint: string | null
  summary: string
  reason_codes: string[]
  limitations: string[]
  path: EvidencePath | null
}

export type EvidenceBundle = {
  analysis_identity: AnalysisIdentity
  records: EvidenceRecord[]
  truncated: boolean
  next_cursor: string | null
}

export type PairWhy = {
  chain_id: string
  alarm_id_a: string
  alarm_id_b: string
  evidence: PairEvidence[]
  evidence_records?: EvidenceRecord[]
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
  snapshot_id: string
  snapshot_version: string
  topology_version?: string | null
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
  training_available: boolean
  training_reason: string
  artifact_source_kind_mix: Record<string, number>
  artifact_truth_tier_distribution: Record<string, number>
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
    topology_version: string | null
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
  evaluation_completed?: boolean
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
  analysis_identity?: AnalysisIdentity | null
  artifact_revision?: ArtifactRevision | null
  result: CounterfactualResult | null
  error: string | null
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

/**
 * The API stores canonical enum values (APPROVE/REJECT), while older UI
 * payloads and persisted fixtures may still contain the past-tense aliases.
 * Keep the compatibility rule in one place so a canonical APPROVE is never
 * rendered as a rejection.
 */
export function isReviewApproved(decision: ReviewDecision | string | null | undefined): boolean {
  return decision === 'APPROVE' || decision === 'APPROVED'
}

export function isReviewRejected(decision: ReviewDecision | string | null | undefined): boolean {
  return decision === 'REJECT' || decision === 'REJECTED'
}

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

export type ReviewFeedbackLifecycleStatus = 'ACTIVE' | 'SUPERSEDED' | 'RETRACTED'

export type ReviewFeedbackHistoryScope =
  | 'PERSISTED_SOURCE_PROFILE'
  | 'PERSISTED_SOURCE_PROFILE_PLUS_ACTIVE'
  | 'IN_MEMORY_ACTIVE_SNAPSHOT'

export type ReviewFeedbackHistoryItem = {
  feedback_id: string
  review_id: string
  job_id: string
  snapshot_id: string
  snapshot_version: string
  profile_id: 'IP_NETWORK' | 'IT_SERVICES' | 'ALARM_ONLY'
  chain_id: string
  candidate_id: string | null
  operation: string
  decision: ReviewDecision | string
  lifecycle_status: ReviewFeedbackLifecycleStatus
  lifecycle_at: string | null
  lifecycle_reason: string | null
  superseded_by_id: string | null
  reviewer_subject: string
  reviewer_role: string
  confidence: number | null
  reason: string | null
  reason_codes: string[]
  created_at: string
}

export type ReviewFeedbackHistoryPage = {
  snapshot_id: string
  snapshot_version: string
  profile_id: 'IP_NETWORK' | 'IT_SERVICES' | 'ALARM_ONLY'
  source_id: string
  history_scope: ReviewFeedbackHistoryScope
  items: ReviewFeedbackHistoryItem[]
  next_cursor: string | null
}

export type ReviewFeedbackHistoryFilters = {
  search?: string
  decision?: ReviewDecision | ''
  lifecycle_status?: ReviewFeedbackLifecycleStatus | ''
  reviewer?: string
  since?: string
  until?: string
  limit?: number
  cursor?: string
}

export type AnalyticalFinding = {
  finding_id: string
  kind: 'OBSERVED' | 'DERIVED' | 'HYPOTHESIS' | 'LIMITATION'
  status: 'AVAILABLE' | 'UNAVAILABLE'
  title: string
  claim: string
  evidence: string[]
  evidence_ids?: string[]
  limitations: string[]
  confidence_basis: string
  confidence?: 'HIGH' | 'MEDIUM' | 'LOW'
}

export type CohesionNarrativeView = {
  chain_id: string
  narrative: string
  model: string
  provider_status?: string | null
  context: {
    evidence_analysis_identity?: AnalysisIdentity
    chain: {
      chain_id: string
      alarm_count: number
      duration_seconds: number
      duration_desc?: string | null
      start_time?: string | null
      end_time?: string | null
      is_singleton: boolean
    }
    alarm_summary: {
      top_alarm_types: [string, number][]
      network_classes: string[]
      device_types: string[]
      devices: string[]
    }
    representative_member?: {
      status: 'AVAILABLE' | 'UNAVAILABLE' | string
      alarm_id?: string
      alarm_name?: string | null
      device_code?: string | null
      role?: 'CORE' | 'PERIPHERAL' | string
      membership_support?: number | null
      availability_coverage?: number | null
      computable_groups?: number | null
      representativeness?: number | null
      selection_semantic: string
      reason?: string
    } | null
    alarm_observation_groups?: Array<{
      device: string
      alarm_name: string
      count: number
      first_observed?: string | null
      last_observed?: string | null
      components: string[]
      locations: string[]
      remote_nodes: string[]
      severities: string[]
      ports: string[]
      peer_hints: string[]
      device_types: string[]
      network_classes: string[]
      alarm_groups: string[]
      content_examples: string[]
    }>
    why: {
      strong_views: string[]
      partial_views: string[]
      top_descriptors: string[]
    }
    topology: {
      status?: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE' | string
      mapped: number
      mapped_alarm_count?: number
      total: number
      mapped_device_count?: number
      total_device_count?: number
      device_mapping_ratio?: number | null
      resource_types: string[]
      mapped_resources?: string[]
      display_paths?: TopologyPath[]
      display_paths_truncated?: boolean
      dependency_verified: boolean
      connected_pair_count?: number
      pair_total?: number
      evaluated_pair_count?: number
      eligible_pair_count?: number
      max_path_hops?: number | null
    }
    audit: {
      status: string
      candidate_cut: boolean
      conductance: number | null
      epsilon?: number | null
      verdict?: string | null
      reason?: string | null
      best_cut_label?: string | null
      partition_summary?: {
        status: string
        cut_source?: string
        cut_label?: string | null
        side_a: {
          alarm_count: number
          resolved_alarm_count: number
          devices: Array<{ device: string; alarm_count: number }>
          alarm_types: Array<{ alarm_name: string; alarm_count: number }>
          first_observed?: { start_time: string; device: string; alarm_name: string } | null
        }
        side_b: {
          alarm_count: number
          resolved_alarm_count: number
          devices: Array<{ device: string; alarm_count: number }>
          alarm_types: Array<{ alarm_name: string; alarm_count: number }>
          first_observed?: { start_time: string; device: string; alarm_name: string } | null
        }
        linkage: {
          onset_gap_seconds?: number | null
          topology_paths: Array<{
            source_devices: string[]
            target_devices: string[]
            hop_count: number
            relation_type?: string | null
            path: string[]
            traversal_semantic?: string | null
          }>
          supporting_groups: Array<{ group: string; label_vi: string; edge_count: number }>
        }
        separation: {
          cross_edge_count: number
          internal_edge_count: number
          cross_edge_weight: number
          internal_edge_weight: number
          edge_counts_are_complete: boolean
          visualization_truncated: boolean
        }
      } | null
    }
    recommendations: {
      status?: string
      count?: number
      evaluation_completed?: boolean
      evaluated_count?: number
      rejected_count?: number
      reason?: string | null
      calibration_status?: string | null
      split_recommended: boolean
      best_alternative?: {
        candidate_id?: string | null
        operation?: string | null
        summary_action?: string | null
        why_better?: string | null
      } | null
    }
    quality_assessment?: {
      method: 'HEURISTIC_V1' | string
      status: 'EVALUATED' | 'UNAVAILABLE' | 'NOT_APPLICABLE' | string
      readiness?: 'READY' | 'PARTIAL' | 'INSUFFICIENT' | 'NOT_APPLICABLE' | string
      reason_codes?: string[]
      evidence_coverage?: Record<string, unknown>
      evidence_ids?: string[]
      reason_evidence_ids?: Record<string, string[]>
      readiness_policy_version?: string
      observed_evidence_families?: string[]
      stars: number | null
      label: string
      score?: number
      reasons: string[]
      available_dimension_count: number
    }
    cohesion_factors?: string[]
    temporal_progression?: {
      status: 'AVAILABLE' | 'UNAVAILABLE'
      t0?: {
        device: string
        start_time: string
        offset_seconds: number
        alarm_name: string
      }
      first_later_offset_seconds?: number | null
      device_onsets: Array<{
        device: string
        start_time: string
        offset_seconds: number
        alarm_name: string
      }>
      waves: Array<{
        start_time: string
        offset_seconds: number
        devices: string[]
        alarm_names: string[]
      }>
    }
    structural_insights?: Array<{
      type: string
      icon?: string
      label: string
      detail: string
      en_detail?: string
    }>
    analytical_findings?: AnalyticalFinding[]
    has_p2?: boolean
    tier2_audit?: {
      evidence_attribution?: {
        status: string
        total_coverage?: number | null
        contributions?: Array<{
          group_id: string
          derivation_tag?: string
          attribution: number
          supported_pairs: number
        }>
      } | null
      over_merge?: {
        structural_separation: boolean
        cross_evidence_agreement: boolean
        strength: string
        narrative: string
        driving_evidence: string[]
      } | null
    }
    operational_insights?: {
      primary_focus?: string
      t0_trigger?: {
        alarm_id?: string
        alarm_name: string
        device_code: string
        start_time: string
      } | null
      cohesion_verdict?: 'STRONG' | 'SEPARABLE' | 'PRELIMINARY' | string
      over_merge_alert?: boolean
      actionable_takeaway?: string
    }
  }
}

export type ChainOverviewCardContext = Partial<Pick<
  CohesionNarrativeView['context'],
  'representative_member' | 'topology' | 'quality_assessment' | 'recommendations'
>>

export type ChainOverviewCards = {
  snapshot_id: string
  snapshot_version: string
  chain_id: string
  status: 'READY' | 'PENDING' | 'UNAVAILABLE' | 'NOT_APPLICABLE'
  projection_version: string | null
  reason: string | null
  topology_version: string | null
  representative_member: ChainOverviewCardContext['representative_member']
  topology: ChainOverviewCardContext['topology'] | null
  quality_assessment: ChainOverviewCardContext['quality_assessment'] | null
  recommendations: ChainOverviewCardContext['recommendations'] | null
  analysis_identity?: AnalysisIdentity | null
  artifact_revision?: ArtifactRevision | null
  review_analysis_identity?: AnalysisIdentity | null
  review_artifact_revision?: ArtifactRevision | null
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
  response_mode: 'LLM_PRIMARY' | 'DETERMINISTIC_FALLBACK' | 'PROVIDER_UNAVAILABLE'
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
  ai_model?: string
  ai_provider_status?: string
}

export type ThresholdSweepResult = {
  parameters: Record<string, number>
  label: string
  explanation: string
  clarity_score: number
  llm_score?: number | null
  hybrid_score?: number | null
  weak_count: number
  core_count: number
  evidence_quality?: {
    insufficient_count?: number
    computable_count?: number
  } | null
}

export type ThresholdExplainOptimization = {
  chain_id: string
  current_parameters: Record<string, number>
  optimal_parameters: Record<string, number>
  current_clarity_score: number
  optimal_clarity_score: number
  current_llm_score?: number | null
  optimal_llm_score?: number | null
  current_hybrid_score?: number | null
  optimal_hybrid_score?: number | null
  clarity_gain: number
  current_explanation: string
  optimal_explanation: string
  winner: string
  why_clearer: string[]
  summary_verdict: string
  sweep_results: ThresholdSweepResult[]
  ai_model?: string
  ai_provider_status?: string
  is_already_optimal?: boolean
}

export type ChainSummary = {
  chain_id: string
  member_count: number
  is_singleton: boolean
  title: string
}

export type ChainList = {
  snapshot_id: string
  chains: ChainSummary[]
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
  threshold: number
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
}

export type Job = {
  job_id: string
  chain_id: string
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  progress_percent: number
  cache_hit: boolean
  result: DeepDive | null
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

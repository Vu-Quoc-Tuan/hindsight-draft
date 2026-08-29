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
  similar_chains: Array<Record<string, unknown>>
  similarity_status: string
  similarity_unavailable_reason: string | null
  taxonomy_status: string | null
  taxonomy_reason: string | null
  active_fingerprint_blocks: string[]
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

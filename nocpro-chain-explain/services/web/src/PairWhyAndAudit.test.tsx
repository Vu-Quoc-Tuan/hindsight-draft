import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AuditStructureView } from './views/AuditStructureView'
import { ChainDetailView } from './views/ChainDetailView'
import { PairScopeView } from './views/why/PairScopeView'
import type { ChainAnalysis, DeepDive, Job, PairWhy } from './types'

const analysis: ChainAnalysis = {
  chain_id: 'C-REAL',
  title: 'Observed chain',
  member_count: 2,
  singleton: false,
  statistics_mode: 'EXACT_INDEXED',
  audit_graph_mode: 'DEFERRED_TO_TIER2',
  pair_materialization: 'LAZY',
  config_version: 'cfg-1',
  graybox: { mode: 'STRICT', merge_strategy: null, rules: 0, characteristics: 0, pair_facts: 0, unavailable_capabilities: [] },
  descriptors: [],
  role_counts: {},
  phase_durations: {},
  members: [{
    alarm_id: 'A', alarm_name: null, device_code: null, node_reference: null,
    canonical_start_time: null, role: 'WEAK', membership_support: null,
    availability_coverage: 0, computable_groups: 0, representativeness: null,
    group_fits: [], margins: [], redundancy_role: null, failure_domains: [],
  }, {
    alarm_id: 'B', alarm_name: 'Observed B', device_code: 'NODE-B', node_reference: null,
    canonical_start_time: '2026-09-06T10:00:00Z', role: 'CORE', membership_support: 0.75,
    availability_coverage: 1, computable_groups: 2, representativeness: 0.6,
    group_fits: [], margins: [], redundancy_role: null, failure_domains: [],
  }],
}

const deepDive = {
  chain_id: 'C-REAL',
  audit_graph_mode: 'EXACT',
  structural_audit: { verdict: 'SPLIT_CANDIDATE', reason: 'LOW_CONDUCTANCE_CUT', epsilon: 0.2, best_cut_label: 'cut-real', best_cut_phi: 0.072 },
  audit_visualization: {
    status: 'AVAILABLE', reason: null, projection_version: 'audit-visualization-v1',
    selection_strategy: 'BEST_CUT_BALANCED_WEIGHTED_DEGREE_V1', max_nodes: 80, max_edges: 160,
    total_node_count: 2, shown_node_count: 2, hidden_node_count: 0,
    total_edge_count: 1, shown_edge_count: 1, hidden_edge_count: 0, truncated: false,
    nodes: [
      { alarm_id: 'A', weighted_degree: 0.8, cut_side: 'A', structural_role: 'NON_CONNECTOR' },
      { alarm_id: 'B', weighted_degree: 0.8, cut_side: 'B', structural_role: 'CONNECTOR' },
    ],
    edges: [{ source_alarm_id: 'A', target_alarm_id: 'B', weight: 0.8, supporting_groups: ['entity'], crosses_best_cut: true }],
  },
  over_merge_strength: 'MODERATE',
  over_merge_narrative: 'Observed exact cut candidate.',
  similar_chains: [], similarity_status: 'UNAVAILABLE', similarity_unavailable_reason: 'NO_MODEL',
  similarity_model_version: null, similarity_trained_until_exclusive: null, similarity_corpus_policy: null,
  similarity_model_update_policy: null, taxonomy_status: null, taxonomy_reason: null, active_fingerprint_blocks: [],
  topology_hypotheses: {} as DeepDive['topology_hypotheses'],
  evidence_attribution: {
    status: 'AVAILABLE', mode: 'EXACT', reason: null, detail: null, chain_size: 2,
    exact_max_members: 100, total_pair_count: 1, covered_pair_count: 1, total_coverage: 1, contributions: [],
  },
  evidence_attribution_evaluation: {
    status: 'AVAILABLE', mode: 'EXACT', reason: null, group_count: 2,
    primary: { ordering: ['g1'], coverage_curve: [1, 0], auc: 0.72 },
    reverse: { ordering: ['g1'], coverage_curve: [1, 0], auc: 0.81 },
    random: { algorithm: 'seeded', seed: 7, repetitions: 10, repetitions_executed: 10, mean_curve: [1, 0], std_curve: [0, 0], mean_auc: 0.77, std_auc: 0.01 },
    delta_vs_random_auc: 0.05, delta_vs_reverse_auc: 0.09,
  },
} satisfies DeepDive

describe('Pair WHY and structural Audit data truth', () => {
  it('renders the backend Dep_hop witness as structural path evidence', () => {
    const pairWhy: PairWhy = {
      chain_id: 'C-REAL',
      alarm_id_a: 'A',
      alarm_id_b: 'B',
      evidence: [{
        channel_family: 'Dep_hop',
        provider_id: 'Dep_hop',
        dependency_semantic: null,
        state: 'SUPPORT',
        score: 0.5,
        threshold: 0.25,
        negative_score: 0,
        detail: 'hop distance 1 over [\'IP_ADJACENCY\']',
        derivation_tag: 'dependency_hop',
        provenance_class: 'EXTERNAL_OPERATIONAL',
        provenance_subtype: 'TOPOLOGY_EXTERNAL',
        source_ref: 'topology.csv',
        source_id: 'topology-1',
        source_version: 'v4',
        scenario_id: null,
        generator_version: null,
        evidence_metadata: {
          topology_path: {
            nodes: ['R1', 'R2'],
            hop_count: 1,
            relation_types: ['IP_ADJACENCY'],
            traversal_semantic: 'STRUCTURAL_TOPOLOGY_PATH_NOT_CAUSAL',
          },
        },
      }],
      system_fact: { status: 'UNAVAILABLE', attribute_ref: null, raw_score: null, semantic: null },
    }
    const html = renderToStaticMarkup(
      <PairScopeView
        members={analysis.members}
        selectedMemberIds={['A', 'B']}
        setSelectedMemberIds={() => {}}
        pairWhy={pairWhy}
        pairWhyState="LOADED"
        pairWhyReason={null}
        onSwitchScope={() => {}}
      />,
    )

    expect(html).toContain('R1 → R2')
    expect(html).toContain('1 hop · IP_ADJACENCY')
    expect(html).toContain('không xác nhận quan hệ nhân quả')
  })

  it('does not show a stale topology path for an unavailable WHY channel', () => {
    const pairWhy: PairWhy = {
      chain_id: 'C-REAL', alarm_id_a: 'A', alarm_id_b: 'B',
      evidence: [{
        channel_family: 'Dep_hop', provider_id: 'Dep_hop', dependency_semantic: null,
        state: 'UNAVAILABLE', score: null, threshold: 0.25, negative_score: null,
        detail: 'no path within D_max=3', derivation_tag: 'dependency_hop',
        provenance_class: 'EXTERNAL_OPERATIONAL', provenance_subtype: 'TOPOLOGY_EXTERNAL',
        source_ref: null, source_id: null, source_version: null, scenario_id: null,
        generator_version: null,
        evidence_metadata: {
          topology_path: {
            nodes: ['R1', 'R2'], hop_count: 1, relation_types: ['IP_ADJACENCY'],
            traversal_semantic: 'STRUCTURAL_TOPOLOGY_PATH_NOT_CAUSAL',
          },
        },
      }],
      system_fact: { status: 'UNAVAILABLE', attribute_ref: null, raw_score: null, semantic: null },
    }
    const html = renderToStaticMarkup(
      <PairScopeView
        members={analysis.members}
        selectedMemberIds={['A', 'B']}
        setSelectedMemberIds={() => {}}
        pairWhy={pairWhy}
        pairWhyState="LOADED"
        pairWhyReason={null}
        onSwitchScope={() => {}}
      />,
    )

    expect(html).not.toContain('Đường topology:')
  })

  it('renders unavailable member values as N/A instead of invented values', () => {
    const html = renderToStaticMarkup(
      <ChainDetailView analysis={analysis} activeSubTab="MEMBERS" onSubTabChange={() => {}} />,
    )

    expect(html).toContain('N/A')
    expect(html).not.toContain('0.28')
    expect(html).not.toContain('0.88')
    expect(html).not.toContain('10:14:02.108')
  })

  it('does not fabricate a structural result before a Deep Dive exists', () => {
    const html = renderToStaticMarkup(
      <AuditStructureView analysis={analysis} snapshotId="s1" snapshotVersion="1" />,
    )

    expect(html).toContain('Structural Audit unavailable')
    expect(html).not.toContain('0.038')
    expect(html).not.toContain('0.0423')
  })

  it('renders exact Audit and attribution fields from the matching job result', () => {
    const job: Job = { job_id: 'J1', snapshot_id: 's1', snapshot_version: '1', chain_id: 'C-REAL', status: 'SUCCEEDED', progress_percent: 100, cache_hit: false, result: deepDive, error: null }
    const html = renderToStaticMarkup(
      <AuditStructureView analysis={analysis} snapshotId="s1" snapshotVersion="1" job={job} />,
    )

    expect(html).toContain('SPLIT_CANDIDATE')
    expect(html).toContain('cut-real')
    expect(html).toContain('0.072')
    expect(html).toContain('0.720')
    expect(html).toContain('2 / 2 nodes')
    expect(html).toContain('A')
    expect(html).toContain('B')
    expect(html).not.toContain('BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE')
  })

  it('shows the explicit persisted-artifact reason when visualization is unavailable', () => {
    const unavailable = {
      snapshot_id: 's1', snapshot_version: '1', chain_id: 'C-REAL',
      audit_artifact_id: null, audit_artifact_fingerprint: null,
      visualization: { ...deepDive.audit_visualization, status: 'UNAVAILABLE' as const, reason: 'AUDIT_ARTIFACT_NOT_AVAILABLE', shown_node_count: 0, shown_edge_count: 0, hidden_node_count: 2, hidden_edge_count: 1, truncated: true, nodes: [], edges: [] },
    }
    const html = renderToStaticMarkup(
      <AuditStructureView analysis={analysis} snapshotId="s1" snapshotVersion="1" auditVisualization={unavailable} />,
    )

    expect(html).toContain('AUDIT_ARTIFACT_NOT_AVAILABLE')
    expect(html).not.toContain('<svg')
  })

  it('rejects a completed result belonging to another chain context', () => {
    const stale: Job = { job_id: 'J2', snapshot_id: 's1', snapshot_version: '1', chain_id: 'C-OLD', status: 'SUCCEEDED', progress_percent: 100, cache_hit: false, result: { ...deepDive, chain_id: 'C-OLD' }, error: null }
    const html = renderToStaticMarkup(
      <AuditStructureView analysis={analysis} snapshotId="s1" snapshotVersion="1" job={stale} />,
    )

    expect(html).toContain('Structural Audit unavailable')
    expect(html).not.toContain('cut-real')
  })

  it('rejects a completed job from another snapshot with the same chain ID', () => {
    const stale: Job = {
      job_id: 'J3', snapshot_id: 'old-snapshot', snapshot_version: '1',
      chain_id: 'C-REAL', status: 'SUCCEEDED', progress_percent: 100,
      cache_hit: false, result: deepDive, error: null,
    }
    const html = renderToStaticMarkup(
      <AuditStructureView analysis={analysis} snapshotId="s1" snapshotVersion="1" job={stale} />,
    )

    expect(html).toContain('Structural Audit unavailable')
    expect(html).not.toContain('cut-real')
  })
})

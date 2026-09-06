import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AuditStructureView } from './views/AuditStructureView'
import { ChainDetailView } from './views/ChainDetailView'
import type { ChainAnalysis, DeepDive, Job } from './types'

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
    const html = renderToStaticMarkup(<AuditStructureView analysis={analysis} />)

    expect(html).toContain('Structural Audit unavailable')
    expect(html).not.toContain('0.038')
    expect(html).not.toContain('0.0423')
  })

  it('renders exact Audit and attribution fields from the matching job result', () => {
    const job: Job = { job_id: 'J1', chain_id: 'C-REAL', status: 'SUCCEEDED', progress_percent: 100, cache_hit: false, result: deepDive, error: null }
    const html = renderToStaticMarkup(<AuditStructureView analysis={analysis} job={job} />)

    expect(html).toContain('SPLIT_CANDIDATE')
    expect(html).toContain('cut-real')
    expect(html).toContain('0.072')
    expect(html).toContain('0.720')
    expect(html).toContain('BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE')
  })

  it('rejects a completed result belonging to another chain context', () => {
    const stale: Job = { job_id: 'J2', chain_id: 'C-OLD', status: 'SUCCEEDED', progress_percent: 100, cache_hit: false, result: { ...deepDive, chain_id: 'C-OLD' }, error: null }
    const html = renderToStaticMarkup(<AuditStructureView analysis={analysis} job={stale} />)

    expect(html).toContain('Structural Audit unavailable')
    expect(html).not.toContain('cut-real')
  })
})

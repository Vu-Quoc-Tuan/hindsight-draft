import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { CounterfactualReview } from './CounterfactualReview'
import type { CounterfactualJob, CounterfactualMetricVector } from './types'

const exactMetrics: CounterfactualMetricVector = {
  weak_member_count: { availability: 'AVAILABLE', value: 1, reason: null },
  minimum_membership_support: { availability: 'AVAILABLE', value: 0.41, reason: null },
  evidence_union_coverage: { availability: 'AVAILABLE', value: 0.8, reason: null },
  component_count: { availability: 'AVAILABLE', value: 2, reason: null },
  audit_conductance: { availability: 'AVAILABLE', value: 0.22, reason: null },
  audit_verdict_severity: { availability: 'AVAILABLE', value: 2, reason: null },
  eligible_external_contradiction_count: { availability: 'AVAILABLE', value: 0, reason: null },
}

const job: CounterfactualJob = {
  job_id: 'review-1',
  chain_id: 'C1',
  status: 'SUCCEEDED',
  progress_percent: 100,
  cache_hit: false,
  cache_fingerprint: '0123456789abcdef',
  identity: {
    snapshot_id: 's1', snapshot_version: '1', chain_id: 'C1',
    alarm_universe_fingerprint: 'alarms', analysis_version: 'analysis-v1',
    engine_version: 'counterfactual-p0-v1', config_version: 'synthetic-review-v1',
    tier1b_artifact_fingerprint: 'tier1b', structural_audit_artifact_fingerprint: null,
    external_validation_artifact_fingerprint: null,
  },
  result: {
    identity: {
      snapshot_id: 's1', snapshot_version: '1', chain_id: 'C1',
      alarm_universe_fingerprint: 'alarms', analysis_version: 'analysis-v1',
      engine_version: 'counterfactual-p0-v1', config_version: 'synthetic-review-v1',
      tier1b_artifact_fingerprint: 'tier1b', structural_audit_artifact_fingerprint: null,
      external_validation_artifact_fingerprint: null,
    },
    status: 'AVAILABLE',
    reason: null,
    recommendation_status: 'AVAILABLE',
    remove: {
      operation: 'REMOVE_MEMBER', status: 'AVAILABLE', reason: null, search_mode: 'BOUNDED',
      discovered_candidate_count: 2, evaluated_candidate_count: 1, rejected_candidate_count: 0,
      candidate_limit: 8,
      candidates: [{
        candidate_id: 'remove-X', operation: 'REMOVE_MEMBER', member_ids: ['X'],
        source_ref: 'trigger-union', status: 'BETTER_SUPPORTED', reason: null,
        edit_cost: { operation_count: 1, membership_reassignments: 1, affected_member_count: 1 },
        partition_delta: { before: [['C1', ['A', 'B', 'X']]], after: [['C1', ['A', 'B']], ['singleton:X', ['X']]] },
        before: exactMetrics,
        after: { ...exactMetrics, weak_member_count: { availability: 'AVAILABLE', value: 0, reason: null } },
        materially_improved_metrics: ['weak_member_count'],
      }],
    },
    split: {
      operation: 'SPLIT_CHAIN', status: 'UNAVAILABLE', reason: 'STRUCTURAL_AUDIT_UNAVAILABLE',
      search_mode: 'NOT_RUN', discovered_candidate_count: 0, evaluated_candidate_count: 0,
      rejected_candidate_count: 0, candidate_limit: 4, candidates: [],
    },
    recommendations: [],
    frontier_count_before_limit: 1,
    frontier_truncated: false,
    parameter_provenance: {},
  },
  error: null,
}

describe('CounterfactualReview', () => {
  it('renders partial operations and exact comparison without an apply control', () => {
    const html = renderToStaticMarkup(<CounterfactualReview chainId="C1" initialJob={job} />)

    expect(html).toContain('Counterfactual chain review')
    expect(html).toContain('REMOVE_MEMBER')
    expect(html).toContain('SPLIT_CHAIN')
    expect(html).toContain('STRUCTURAL_AUDIT_UNAVAILABLE')
    expect(html).toContain('Exact before and after metrics')
    expect(html).toContain('Proposal only')
    expect(html).toContain('NocPro was not changed')
    expect(html.toLowerCase()).not.toContain('>apply<')
  })

  it('shows an unavailable domain result without fabricating a proposal', () => {
    const unavailable: CounterfactualJob = {
      ...job,
      result: job.result ? {
        ...job.result,
        status: 'UNAVAILABLE',
        reason: 'COUNTERFACTUAL_CONFIG_INCOMPLETE',
        recommendation_status: 'UNAVAILABLE',
        remove: { ...job.result.remove, status: 'UNAVAILABLE', reason: 'COUNTERFACTUAL_CONFIG_INCOMPLETE', candidates: [] },
        split: { ...job.result.split, reason: 'COUNTERFACTUAL_CONFIG_INCOMPLETE' },
      } : null,
    }
    const html = renderToStaticMarkup(<CounterfactualReview chainId="C1" initialJob={unavailable} />)

    expect(html).toContain('COUNTERFACTUAL_CONFIG_INCOMPLETE')
    expect(html).toContain('UNAVAILABLE')
    expect(html).not.toContain('review-ledger')
  })
})

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { EvidenceAttribution } from './EvidenceAttribution'
import type { AttributionDeletionEvaluationResult, EvidenceCoverageAttributionResult } from './types'

const exact: EvidenceCoverageAttributionResult = {
  status: 'AVAILABLE',
  mode: 'EXACT',
  reason: null,
  detail: null,
  chain_size: 3,
  exact_max_members: 500,
  total_pair_count: 3,
  covered_pair_count: 3,
  total_coverage: 1,
  contributions: [
    { group_id: 'reference|POST_HOC|explain=1|role=1|audit=1', derivation_tag: 'reference', provenance_class: 'POST_HOC', explain_eligible: true, role_eligible: true, audit_eligible: true, behavioral: false, supported_pair_count: 2, attribution: 0.5 },
    { group_id: 'temporal|BEHAVIORAL|explain=1|role=0|audit=0', derivation_tag: 'temporal', provenance_class: 'BEHAVIORAL', explain_eligible: true, role_eligible: false, audit_eligible: false, behavioral: true, supported_pair_count: 2, attribution: 0.5 },
  ],
}

const evaluation: AttributionDeletionEvaluationResult = {
  status: 'AVAILABLE',
  mode: 'EXACT',
  reason: null,
  group_count: 2,
  primary: { ordering: exact.contributions.map((item) => item.group_id), coverage_curve: [1, 0.5, 0], auc: 0.5 },
  reverse: { ordering: exact.contributions.map((item) => item.group_id).reverse(), coverage_curve: [1, 1, 0], auc: 0.75 },
  random: { algorithm: 'SPLITMIX64_FISHER_YATES_V1', seed: 42, repetitions: 100, repetitions_executed: 100, mean_curve: [1, 0.75, 0], std_curve: [0, 0.25, 0], mean_auc: 0.625, std_auc: 0.125 },
  delta_vs_random_auc: 0.125,
  delta_vs_reverse_auc: 0.25,
}

function markup(
  result: EvidenceCoverageAttributionResult,
  deletionEvaluation: AttributionDeletionEvaluationResult = evaluation,
) {
  return renderToStaticMarkup(<EvidenceAttribution result={result} evaluation={deletionEvaluation} />)
}

describe('EvidenceAttribution', () => {
  it('uses exact evidence coverage wording and labels behavioral groups', () => {
    const html = markup(exact)

    expect(html).toContain('Evidence Coverage Attribution')
    expect(html).toContain('EXACT')
    expect(html).toContain('100%')
    expect(html).toContain('50%')
    expect(html).toContain('BEHAVIORAL')
    expect(html).toContain('evidence coverage')
    expect(html.toLowerCase()).not.toContain('causal importance')
    expect(html.toLowerCase()).not.toContain('cohesion')
    expect(html).toContain('lower primary AUC is better')
    expect(html).toContain('0.500')
    expect(html).toContain('0.625 ± 0.125')
    expect(html).toContain('SPLITMIX64_FISHER_YATES_V1 · seed 42 · 100 runs')
    expect(html).toContain('Evaluation AVAILABLE')
    expect(html).toContain('Evaluation EXACT')
  })

  it('renders a ceiling as a domain result without fabricated values', () => {
    const html = markup(
      {
        ...exact,
        status: 'UNAVAILABLE',
        mode: 'UNAVAILABLE',
        reason: 'ATTRIBUTION_LIMIT_EXCEEDED',
        chain_size: 1072,
        contributions: [],
        covered_pair_count: null,
        total_coverage: null,
      },
      { ...evaluation, status: 'UNAVAILABLE', mode: 'UNAVAILABLE', reason: 'ATTRIBUTION_UNAVAILABLE', group_count: 0 },
    )

    expect(html).toContain('ATTRIBUTION_LIMIT_EXCEEDED')
    expect(html).toContain('Chain size 1072; exact ceiling 500.')
    expect(html).not.toContain('attribution-value')
    expect(html).toContain('ATTRIBUTION_UNAVAILABLE')
  })

  it('renders singleton as not applicable rather than zero', () => {
    const html = markup(
      {
        ...exact,
        status: 'NOT_APPLICABLE',
        mode: 'UNAVAILABLE',
        reason: 'SINGLETON',
        detail: 'SINGLETON_CHAIN',
        chain_size: 1,
        total_pair_count: 0,
        contributions: [],
        covered_pair_count: null,
        total_coverage: null,
      },
      { ...evaluation, status: 'UNAVAILABLE', mode: 'UNAVAILABLE', reason: 'ATTRIBUTION_UNAVAILABLE', group_count: 0 },
    )

    expect(html).toContain('NOT_APPLICABLE')
    expect(html).toContain('SINGLETON_CHAIN')
    expect(html).not.toContain('0%')
    expect(html).toContain('ATTRIBUTION_UNAVAILABLE')
  })

  it('does not turn no eligible groups into a zero AUC', () => {
    const html = markup(
      { ...exact, covered_pair_count: 0, total_coverage: 0, contributions: [] },
      {
        ...evaluation,
        status: 'NOT_APPLICABLE',
        mode: 'UNAVAILABLE',
        reason: 'NO_ELIGIBLE_GROUPS',
        group_count: 0,
        primary: { ordering: [], coverage_curve: [], auc: null },
        reverse: { ordering: [], coverage_curve: [], auc: null },
        random: { algorithm: 'SPLITMIX64_FISHER_YATES_V1', seed: null, repetitions: null, repetitions_executed: 0, mean_curve: [], std_curve: [], mean_auc: null, std_auc: null },
        delta_vs_random_auc: null,
        delta_vs_reverse_auc: null,
      },
    )

    expect(html).toContain('NO_ELIGIBLE_GROUPS')
    expect(html).toContain('no deletion AUC is reported')
    expect(html).not.toContain('primary AUC</dt><dd>0')
  })
})

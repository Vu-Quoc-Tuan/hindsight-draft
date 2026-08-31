import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { EvidenceAttribution } from './EvidenceAttribution'
import type { EvidenceCoverageAttributionResult } from './types'

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

function markup(result: EvidenceCoverageAttributionResult) {
  return renderToStaticMarkup(<EvidenceAttribution result={result} />)
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
  })

  it('renders a ceiling as a domain result without fabricated values', () => {
    const html = markup({
      ...exact,
      status: 'UNAVAILABLE',
      mode: 'UNAVAILABLE',
      reason: 'ATTRIBUTION_LIMIT_EXCEEDED',
      chain_size: 1072,
      contributions: [],
      covered_pair_count: null,
      total_coverage: null,
    })

    expect(html).toContain('ATTRIBUTION_LIMIT_EXCEEDED')
    expect(html).toContain('Chain size 1072; exact ceiling 500.')
    expect(html).not.toContain('attribution-value')
  })

  it('renders singleton as not applicable rather than zero', () => {
    const html = markup({
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
    })

    expect(html).toContain('NOT_APPLICABLE')
    expect(html).toContain('SINGLETON_CHAIN')
    expect(html).not.toContain('0%')
  })
})

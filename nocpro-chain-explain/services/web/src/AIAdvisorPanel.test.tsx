import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AIAdvisorPanel } from './AIAdvisorPanel'
import type { AISuggestion } from './types'

const mockSuggestion: AISuggestion = {
  chain_id: 'CHAIN-VN-001',
  status: 'AVAILABLE',
  model: 'DETERMINISTIC_EVIDENCE',
  narrative: '### Evidence summary for chain CHAIN-VN-001\n- Analyzed members: 3.\n- Members classified WEAK: ALARM-1.\n> This is a deterministic rendering of persisted analysis facts.',
  grounded_claims: [
    'Chain CHAIN-VN-001 contains 3 analyzed members.',
    '1 member is classified WEAK: ALARM-1.',
  ],
  disclaimer: 'ADR-0024: deterministic evidence only.',
  provider_status: 'NOT_CONFIGURED',
  review_status: 'AVAILABLE',
}

describe('AIAdvisorPanel', () => {
  it('renders deterministic grounded facts with a clear fallback state', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel chainId="CHAIN-VN-001" initialSuggestion={mockSuggestion} />,
    )

    expect(html).toContain('ADR-0024 Grounded Narrative')
    expect(html).toContain('Deterministic fallback')
    expect(html).toContain('Not configured')
    expect(html).toContain('Evidence summary for chain CHAIN-VN-001')
    expect(html).toContain('Analyzed members: 3.')
    expect(html).toContain('Members classified WEAK: ALARM-1.')
    expect(html).toContain('Mệnh đề bằng chứng xác minh (Grounded Claims)')
    expect(html).toContain('Chain CHAIN-VN-001 contains 3 analyzed members.')
    expect(html).toContain('1 member is classified WEAK: ALARM-1.')
    expect(html).toContain('ADR-0024: deterministic evidence only.')
    expect(html).not.toContain('Root-cause')
    expect(html).not.toContain('Thông báo nhà cung cấp LLM')
  })

  it('shows successful server-side AI rendering without exposing credentials', () => {
    const html = renderToStaticMarkup(
      <AIAdvisorPanel
        chainId="CHAIN-VN-001"
        initialSuggestion={{
          ...mockSuggestion,
          model: 'mistral-large',
          provider_status: 'OK',
          narrative: 'Grounded AI-rendered narrative.',
        }}
      />,
    )

    expect(html).toContain('AI-assisted')
    expect(html).toContain('mistral-large')
    expect(html).toContain('Grounded AI-rendered narrative.')
    expect(html).not.toContain('AI_API_KEY')
    expect(html).not.toContain('test-secret')
  })
})

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { GroundedProviderBadge } from './GroundedProviderBadge'

describe('GroundedProviderBadge', () => {
  it('shows the grounding warning before the generic LLM_PRIMARY badge', () => {
    const html = renderToStaticMarkup(
      <GroundedProviderBadge
        model="test-model"
        providerStatus="GROUNDING_FORBIDDEN_CLAIM"
        responseMode="LLM_PRIMARY"
        hasProviderOutput
      />,
    )

    expect(html).toContain('AI raw · grounding cảnh báo')
    expect(html).not.toContain('AI hỗ trợ')
  })

  it('does not show deterministic legacy prose as an AI badge', () => {
    const html = renderToStaticMarkup(
      <GroundedProviderBadge
        model="DETERMINISTIC_EVIDENCE"
        providerStatus="GROUNDING_VIOLATION"
        responseMode="DETERMINISTIC_FALLBACK"
        hasProviderOutput={false}
      />,
    )

    expect(html).toContain('AI chưa khả dụng')
    expect(html).not.toContain('AI hỗ trợ')
  })
})

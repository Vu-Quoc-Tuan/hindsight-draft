import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { NocProAssistantPanel } from './NocProAssistantPanel'
import type { AssistantResponse } from './types'

const renderedResponse: AssistantResponse = {
  contract_version: 'nocpro-assistant-v1',
  status: 'AVAILABLE',
  message: 'Bản diễn giải đã được grounded.',
  fact_refs: ['semantic-registry:conductance'],
  actions: [],
  model: 'mistral-large',
  provider_status: 'OK',
}

describe('NocProAssistantPanel', () => {
  it('states the read-only boundary and renders deterministic quick actions', () => {
    const html = renderToStaticMarkup(
      <NocProAssistantPanel
        context={{ snapshot_id: 'S1', snapshot_version: '1', page: 'ai', chain_id: 'C1', filters: {} }}
        onNavigate={() => undefined}
        initialResponse={renderedResponse}
      />,
    )

    expect(html).toContain('NocPro Assistant')
    expect(html).toContain('Assistant không thay đổi analysis')
    expect(html).toContain('Conductance là gì?')
    expect(html).toContain('Open Pair WHY')
    expect(html).toContain('AI-assisted')
    expect(html).toContain('mistral-large')
    expect(html).toContain('Bản diễn giải đã được grounded.')
    expect(html).toContain('does not change evidence')
    expect(html).not.toContain('AI_API_KEY')
    expect(html).not.toContain('>Apply recommendation<')
  })
})

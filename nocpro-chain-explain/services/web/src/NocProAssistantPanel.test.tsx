import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { buildAssistantHistory } from './assistantHistory'
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
  response_mode: 'LLM_PRIMARY',
  tools_used: ['search_project_knowledge'],
}

describe('NocProAssistantPanel', () => {
  it('builds bounded history without welcome or error messages', () => {
    const history = buildAssistantHistory([
      { id: 'welcome', role: 'assistant', text: 'welcome' },
      { id: '1', role: 'user', text: 'first' },
      { id: '2', role: 'assistant', text: 'failed', error: 'network' },
      ...Array.from({ length: 9 }, (_, index) => ({
        id: `m-${index}`,
        role: (index % 2 ? 'assistant' : 'user') as 'assistant' | 'user',
        text: `message-${index}`,
      })),
    ])

    expect(history).toHaveLength(8)
    expect(history[0].content).toBe('message-1')
    expect(history.some(item => item.content === 'welcome' || item.content === 'failed')).toBe(false)
  })

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

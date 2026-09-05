import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { NocProAssistantPanel } from './NocProAssistantPanel'

describe('NocProAssistantPanel', () => {
  it('states the read-only boundary and renders deterministic quick actions', () => {
    const html = renderToStaticMarkup(
      <NocProAssistantPanel
        context={{ snapshot_id: 'S1', snapshot_version: '1', page: 'ai', chain_id: 'C1', filters: {} }}
        onNavigate={() => undefined}
      />,
    )

    expect(html).toContain('NocPro Assistant')
    expect(html).toContain('Assistant không thay đổi analysis')
    expect(html).toContain('Conductance là gì?')
    expect(html).toContain('Open Pair WHY')
    expect(html).toContain('does not change evidence')
    expect(html).not.toContain('>Apply recommendation<')
  })
})

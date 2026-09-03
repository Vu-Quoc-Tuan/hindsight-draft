import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { EvolutionPanel } from './EvolutionPanel'
import type { Evolution } from './types'

const artifact: Evolution = {
  status: 'AVAILABLE', reason: null, source_kind: 'SYNTHETIC_TEST', sequence_status: 'VERIFIED', production_validation: 'NOT_ESTABLISHED',
  lineage_component_id: 'lc-test', branch_id: 'lc-test:b0', snapshot_id: 's2', snapshot_version: '2', chain_id: 'C2',
  nodes: [
    { snapshot_id: 's1', snapshot_version: '1', chain_id: 'C1', snapshot_time: '2026-01-01T00:00:00Z', lineage_component_id: 'lc-test', branch_id: 'lc-test:b0', source_kind: 'SYNTHETIC_TEST' },
    { snapshot_id: 's2', snapshot_version: '2', chain_id: 'C2', snapshot_time: '2026-01-01T00:01:00Z', lineage_component_id: 'lc-test', branch_id: 'lc-test:b0', source_kind: 'SYNTHETIC_TEST' },
  ],
  edges: [{ parent_snapshot_id: 's1', parent_snapshot_version: '1', parent_chain_id: 'C1', child_snapshot_id: 's2', child_snapshot_version: '2', child_chain_id: 'C2', event_type: 'CONTINUE', overlap_count: 3, contain_parent: 1, contain_child: 1 }],
}

describe('EvolutionPanel', () => {
  it('renders only persisted lineage fields for a synthetic verified sequence', () => {
    const html = renderToStaticMarkup(<EvolutionPanel chainId="C2" initialResult={artifact} />)

    expect(html).toContain('Synthetic test sequence')
    expect(html).toContain('Production validation not established')
    expect(html).toContain('CONTINUE')
    expect(html).toContain('C1')
    expect(html).toContain('C2')
    expect(html).not.toContain('joined')
    expect(html).not.toContain('turnover')
  })
})

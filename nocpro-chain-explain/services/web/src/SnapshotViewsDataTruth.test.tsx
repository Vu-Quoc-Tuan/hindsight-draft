import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ChainsExplorerView } from './views/ChainsExplorerView'
import { MultiChainTimelineView } from './views/MultiChainTimelineView'
import { CompareChainsView } from './views/CompareChainsView'
import type { ChainList } from './types'

const chainList: ChainList = {
  snapshot_id: 'S-REAL',
  snapshot_version: 'v2',
  chains: [{
    chain_id: 'C-REAL',
    member_count: 3,
    is_singleton: false,
    title: 'Observed chain',
    start_time: '2026-09-06T10:00:00Z',
    end_time: '2026-09-06T10:02:00Z',
    duration_seconds: 120,
  }],
}

describe('snapshot views use only factual chain summary fields', () => {
  it('does not fabricate conductance, weak members or severity', () => {
    const html = renderToStaticMarkup(
      <ChainsExplorerView chainList={chainList} onSelectChain={() => {}} onCompareChains={() => {}} />,
    )

    expect(html).toContain('Audit on demand')
    expect(html).toContain('2m')
    expect(html).not.toContain('CONDUCTANCE')
    expect(html).not.toContain('Cut Candidate')
    expect(html).not.toContain('CRITICAL')
  })

  it('renders a timeline from exact returned timestamps', () => {
    const html = renderToStaticMarkup(
      <MultiChainTimelineView chains={chainList.chains} onSelectChain={() => {}} onCompareChains={() => {}} />,
    )

    expect(html).toContain('10:00:00')
    expect(html).toContain('10:02:00')
    expect(html).toContain('2m')
    expect(html).not.toContain('DEH-NODE')
    expect(html).not.toContain('a/s')
  })

  it('renders temporal data as unavailable when timestamps are absent', () => {
    const html = renderToStaticMarkup(
      <MultiChainTimelineView
        chains={[{ ...chainList.chains[0], start_time: null, end_time: null, duration_seconds: null }]}
        onSelectChain={() => {}}
        onCompareChains={() => {}}
      />,
    )

    expect(html).toContain('Temporal range unavailable')
  })

  it('compares observed fields without fabricating cross-chain causality', () => {
    const other = { ...chainList.chains[0], chain_id: 'C-OTHER', title: 'Other observed chain' }
    const html = renderToStaticMarkup(
      <CompareChainsView
        chainAId="C-REAL"
        chainBId="C-OTHER"
        chains={[chainList.chains[0], other]}
        onSelectChain={() => {}}
        onChangeSelection={() => {}}
      />,
    )

    expect(html).toContain('Observed chain')
    expect(html).toContain('Other observed chain')
    expect(html).not.toContain('root cause')
    expect(html).not.toContain('+1.82s')
    expect(html).not.toContain('CONDUCTANCE')
  })
})

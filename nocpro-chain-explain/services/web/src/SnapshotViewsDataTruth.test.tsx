import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ChainsExplorerView } from './views/ChainsExplorerView'
import { MultiChainTimelineView } from './views/MultiChainTimelineView'
import { SnapshotOverviewView } from './views/SnapshotOverviewView'
import { NocHeader } from './components/NocHeader'
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
  it('renders overview metrics only from the returned chain list', () => {
    const html = renderToStaticMarkup(
      <SnapshotOverviewView chainList={chainList} onSelectChain={() => {}} onNavigate={() => {}} />,
    )

    expect(html).toContain('S-REAL@v2')
    expect(html).toContain('Observed chain')
    expect(html).toContain('Observation Window')
    expect(html).toContain('Chain Duration Profile')
    expect(html).not.toContain('Audit on demand')
    expect(html).not.toContain('Solitary Alarms')
    expect(html).not.toContain('Multi-alarm Chains')
    expect(html).not.toContain('8,714')
    expect(html).not.toContain('Structural Findings')
    expect(html).not.toContain('Alternative Partitions')
  })

  it('renders an unavailable overview instead of a demo snapshot', () => {
    const html = renderToStaticMarkup(
      <SnapshotOverviewView chainList={null} onSelectChain={() => {}} onNavigate={() => {}} />,
    )

    expect(html).toContain('Snapshot unavailable')
    expect(html).not.toContain('C2214039')
    expect(html).not.toContain('8,714')
  })

  it('keeps topology profile selection separate from backend snapshot identity', () => {
    const html = renderToStaticMarkup(
      <NocHeader
        datasetName="IT_SERVICES"
        snapshotId="S-REAL@v2"
        currentView="snapshot-overview"
        onNavigate={() => {}}
        onOpenSettings={() => {}}
      />,
    )

    expect(html).toContain('S-REAL@v2')
    expect(html).toContain('IT Services')
    expect(html).not.toContain('real_alarm_20260801')
    expect(html).not.toContain('Gần nhất từ PostgreSQL')
  })

  it('does not fabricate conductance, weak members or severity', () => {
    const html = renderToStaticMarkup(
      <ChainsExplorerView chainList={chainList} onSelectChain={() => {}} />,
    )

    expect(html).toContain('Audit on demand')
    expect(html).toContain('2m')
    expect(html).not.toContain('CONDUCTANCE')
    expect(html).not.toContain('Cut Candidate')
    expect(html).not.toContain('CRITICAL')
  })

  it('renders sort controls and members sortable header in ChainsExplorerView', () => {
    const html = renderToStaticMarkup(
      <ChainsExplorerView chainList={chainList} onSelectChain={() => {}} />,
    )

    expect(html).toContain('Most members')
    expect(html).toContain('Fewest')
    expect(html).toContain('SORT')
    expect(html).toContain('Members')
  })

  it('renders a timeline from exact returned timestamps', () => {
    const html = renderToStaticMarkup(
      <MultiChainTimelineView chains={chainList.chains} onSelectChain={() => {}} />,
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
      />
    )

    expect(html).toContain('Temporal range unavailable')
  })



  it('renders snapshot catalog items in header without mock contamination', () => {
    const snapshots = [
      {
        snapshot_id: 'real_alarm_ip_demo',
        name: 'IP Network Replay (500 Alarms)',
        profile: 'IP_NETWORK' as const,
        alarm_count: 500,
        chain_count: 258,
        description: 'Observed IP alarms mapped to topoIP.csv router/switch adjacency graph.',
        badge: 'Real Replay',
      },
    ]
    const html = renderToStaticMarkup(
      <NocHeader
        datasetName="IP_NETWORK"
        snapshotId="real_alarm_ip_demo@1"
        currentView="snapshot-overview"
        snapshots={snapshots}
        onNavigate={() => {}}
        onOpenSettings={() => {}}
      />,
    )
    expect(html).toContain('real_alarm_ip_demo@1')
    expect(html).toContain('IP Network')
  })
})

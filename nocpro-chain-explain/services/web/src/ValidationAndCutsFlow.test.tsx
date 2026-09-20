import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { SubNavBar } from './components/SubNavBar'
import { EvolutionView } from './views/EvolutionView'
import { RecommendationsView } from './views/RecommendationsView'
import { TopologyOverlayView } from './views/TopologyOverlayView'
import { ValidationView } from './views/ValidationView'
import type { ChainAnalysis } from './types'

const analysis = {
  chain_id: 'C-REAL', title: 'Observed chain', member_count: 0, singleton: false,
  statistics_mode: 'EXACT', audit_graph_mode: 'DEFERRED', pair_materialization: 'LAZY', config_version: 'v1',
  graybox: { mode: 'STRICT', merge_strategy: null, rules: 0, characteristics: 0, pair_facts: 0, unavailable_capabilities: [] },
  descriptors: [], members: [], role_counts: {}, phase_durations: {},
} satisfies ChainAnalysis

describe('persisted Review, Evolution, topology and feedback surfaces', () => {
  it('keeps the chain navigation destinations visible', () => {
    const html = renderToStaticMarkup(<SubNavBar currentTab="chain-overview" onSelectTab={() => {}} selectedChainId="C-REAL" />)
    expect(html).toContain('Validation')
    expect(html).toContain('Topology')
    expect(html).toContain('Evolution')
    expect(html).toContain('Audit &amp; Structure')
  })

  it('does not render fabricated recommendation KPIs', () => {
    const html = renderToStaticMarkup(<RecommendationsView analysis={analysis} />)
    expect(html).toContain('Recommendations · C-REAL')
    expect(html).not.toContain('+0.142')
    expect(html).not.toContain('99.4%')
    expect(html).not.toContain('30 min')
  })

  it('uses one persisted Evolution panel without a static S100/S102 story', () => {
    const html = renderToStaticMarkup(<EvolutionView analysis={analysis} initialTab="cross_snapshot" />)
    expect(html).toContain('Loading persisted lineage artifact')
    expect(html).not.toContain('Chronological Alarm Cascade')
    expect(html).not.toContain('Snapshot S100')
    expect(html).not.toContain('42 Alarms Base')
    expect(html).not.toContain('S103 Fission')
  })

  it('renders propagation timeline exclusively when timeline tab is active without fabricated fallbacks', () => {
    const html = renderToStaticMarkup(<EvolutionView analysis={analysis} initialTab="timeline" />)
    expect(html).toContain('Chronological Alarm Cascade')
    expect(html).not.toContain('Loading persisted lineage artifact')
    expect(html).not.toContain('10:00:00')
    expect(html).not.toContain('22.4s')
    expect(html).not.toContain('T0_ALARM')
  })

  it('shows topology loading without constructing an AVAILABLE payload', () => {
    const html = renderToStaticMarkup(<TopologyOverlayView analysis={analysis} topologyPayload={null} />)
    expect(html).toContain('Loading topology projection')
    expect(html).not.toContain('netbox-v3.7-cmdb-live')
    expect(html).not.toContain('41 / 58')
    expect(html).not.toContain('CUT Phi')
  })

  it('describes Validation as persisted feedback, not Apply or consensus', () => {
    const html = renderToStaticMarkup(<ValidationView analysis={analysis} />)
    expect(html).toContain('PHÂN HOẠCH DO KỸ SƯ TỰ ĐỊNH NGHĨA')
    expect(html).not.toContain('CONSENSUS SEALED')
    expect(html).not.toContain('SHA-256')
    expect(html).not.toContain('rollback SLA')
  })
})

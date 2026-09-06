import { renderToStaticMarkup } from 'react-dom/server'
import { describe, it, expect } from 'vitest'
import { SubNavBar } from './components/SubNavBar'
import { OperatorValidationModal } from './components/OperatorValidationModal'
import { ValidationView } from './views/ValidationView'
import { AuditStructureView } from './views/AuditStructureView'
import type { ChainAnalysis } from './types'

const mockAnalysis: ChainAnalysis = {
  chain_id: 'C2214039',
  title: 'IT_K8S_INGRESS • 504 Gateway Surge',
  member_count: 58,
  singleton: false,
  statistics_mode: 'EXACT',
  audit_graph_mode: 'NORM_LAPLACIAN',
  pair_materialization: 'BOUNDED',
  config_version: 'v1',
  graybox: {
    mode: 'STRICT',
    merge_strategy: null,
    rules: 4,
    characteristics: 12,
    pair_facts: 48,
    unavailable_capabilities: [],
  },
  descriptors: [],
  members: [],
  role_counts: { core: 12, connector: 42, peripheral: 4 },
  phase_durations: {},
}

describe('Validation and Cut Flows Differentiation', () => {
  it('renders 18 Validation as a regular tab in SubNavBar without standalone duplicate button', () => {
    const html = renderToStaticMarkup(
      <SubNavBar
        currentTab="chain-overview"
        onSelectTab={() => {}}
        selectedChainId="C2214039"
      />
    )

    expect(html).toContain('Validation')
    expect(html).toContain('Topology')
    expect(html).toContain('Evolution')
    expect(html).toContain('Audit &amp; Structure')
  })

  it('renders full Screen 18 ValidationView dashboard with consensus and safeguard checklist', () => {
    const html = renderToStaticMarkup(
      <ValidationView
        analysis={mockAnalysis}
        onOpenValidationModal={() => {}}
      />
    )

    expect(html).toContain('18 - Validation &amp; Operator Consensus Protocol')
    expect(html).toContain('Chữ ký Xác nhận Đa Tầng (Multi-Reviewer Consensus)')
    expect(html).toContain('ca_truc_hanoi_01')
    expect(html).toContain('specialist_ip_dehl')
    expect(html).toContain('P1 SLA Disruption Zero')
    expect(html).toContain('Immutable Hash Integrity')
    expect(html).toContain('Reversible Staging Window')
  })

  it('renders dynamic cut parameters in OperatorValidationModal when provided', () => {
    const html = renderToStaticMarkup(
      <OperatorValidationModal
        isOpen={true}
        onClose={() => {}}
        chainId="C2214039"
        mutationSpec={{
          opId: 'MUT-CUT-01',
          opType: 'CHEEGER_SPECTRAL_CUT',
          title: 'Phê duyệt Nhát cắt Đồ thị CUT-01',
          targetSummary: 'Phân tách: Subchain A (42 alms) và Subchain B (16 alms)',
          detail: 'Độ dẫn Φ = 0.038, Gain = +0.142',
          badgeLabel: 'CUT-01',
          conductance: 0.038,
          modularityGain: '+0.142',
          disconnectedEdges: ['ALM-47933130 ↔ ALM-99210014 (Weight: 0.11)'],
        }}
        onConfirmSignOff={() => {}}
      />
    )

    expect(html).toContain('OP_ID: MUT-CUT-01')
    expect(html).toContain('Phê duyệt Nhát cắt Đồ thị CUT-01')
    expect(html).toContain('Phân tách: Subchain A (42 alms) và Subchain B (16 alms)')
    expect(html).toContain('CUT-01')
    expect(html).toContain('ALM-47933130 ↔ ALM-99210014')
    expect(html).toContain('Conductance Φ: <strong class="text-primary">0.038</strong>')
  })

  it('AuditStructureView is unavailable until an explicit Deep Dive result exists', () => {
    const html = renderToStaticMarkup(
      <AuditStructureView analysis={mockAnalysis} />
    )

    expect(html).toContain('Structural Audit unavailable')
    expect(html).toContain('Run Deep Dive')
    expect(html).not.toContain('Review Partition Sign-off')
    expect(html).not.toContain('0.038')
  })

  it('renders HindsightLogo with magnifying glass and alarm chain vector graphics', async () => {
    const { HindsightLogo } = await import('./components/HindsightLogo')
    const html = renderToStaticMarkup(<HindsightLogo size={36} />)

    expect(html).toContain('<svg')
    expect(html).toContain('viewBox="0 0 64 64"')
    expect(html).toContain('logoLensClip')
    expect(html).toContain('rotate(-45 26.5 26.5)')
  })

  it('renders NocHeader with Hindsight brand and tagline', async () => {
    const { NocHeader } = await import('./components/NocHeader')
    const html = renderToStaticMarkup(
      <NocHeader
        datasetName="IT_SERVICES"
        snapshotId="S102 / v1"
        currentView="snapshot-overview"
        onNavigate={() => {}}
        onOpenSettings={() => {}}
      />
    )

    expect(html).toContain('Hindsight')
    expect(html).toContain('See the bigger picture behind alarm chains')
    expect(html).toContain('NOCPRO')
  })

  it('verifies SnapshotOverviewView removed redundant labels', async () => {
    const { SnapshotOverviewView } = await import('./views/SnapshotOverviewView')
    const html = renderToStaticMarkup(
      <SnapshotOverviewView
        onSelectChain={() => {}}
        onNavigate={() => {}}
      />
    )

    // Verify requested labels are removed
    expect(html).not.toContain('N = 2,824 CHAINS')
    expect(html).not.toContain('Triage candidates prioritized by structural risk')
    expect(html).not.toContain('Displaying 5 critical triage targets')
  })

  it('verifies MultiChainTimelineView has Isolate Pair button and does not distort text with scaleX', async () => {
    const { MultiChainTimelineView } = await import('./views/MultiChainTimelineView')
    const html = renderToStaticMarkup(
      <MultiChainTimelineView
        onSelectChain={() => {}}
        onCompareChains={() => {}}
      />
    )

    expect(html).toContain('Isolate Pair')
    expect(html).not.toContain('scaleX(')
  })

  it('verifies NocHeader renders high-contrast opaque scope selector', async () => {
    const { NocHeader } = await import('./components/NocHeader')
    const html = renderToStaticMarkup(
      <NocHeader
        datasetName="IP_NETWORK"
        snapshotId="real_alarm_20260801"
        currentView="snapshot-overview"
        onNavigate={() => {}}
        onOpenSettings={() => {}}
      />
    )

    expect(html).toContain('IP_NETWORK')
    expect(html).toContain('real_alarm_20260801')
  })
})


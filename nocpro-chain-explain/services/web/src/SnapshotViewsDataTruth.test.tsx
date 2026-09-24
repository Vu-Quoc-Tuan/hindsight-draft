import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AllChainsView } from './views/AllChainsView'
import { SnapshotOverviewView } from './views/SnapshotOverviewView'
import { SnapshotsPortfolioView } from './views/SnapshotsPortfolioView'
import { NocHeader } from './components/NocHeader'
import type { ChainList } from './types'

const chainList: ChainList = {
  snapshot_id: 'S-REAL',
  snapshot_version: 'v2',
  chains: [
    {
      chain_id: 'C-REAL',
      member_count: 3,
      is_singleton: false,
      title: 'Observed chain',
      start_time: '2026-09-06T10:00:00Z',
      end_time: '2026-09-06T10:02:00Z',
      duration_seconds: 120,
    },
    {
      chain_id: 'C-SINGLE',
      member_count: 1,
      is_singleton: true,
      title: 'Observed singleton',
      start_time: null,
      end_time: null,
      duration_seconds: null,
    },
  ],
}

describe('snapshot views use only factual chain summary fields', () => {
  it('renders overview metrics only from the returned chain list', () => {
    const html = renderToStaticMarkup(
      <SnapshotOverviewView chainList={chainList} onSelectChain={() => {}} onNavigate={() => {}} />,
    )

    expect(html).toContain('S-REAL@v2')
    expect(html).toContain('Observed chain')
    expect(html).toContain('Observed chain-size distribution')
    expect(html).toContain('Avg Size')
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
    expect(html).toContain('All Chains')
    expect(html).not.toContain('Timeline')
    expect(html).not.toContain('real_alarm_20260801')
    expect(html).not.toContain('Gần nhất từ PostgreSQL')
  })

  it('renders every chain in a simple all-chains view', () => {
    const html = renderToStaticMarkup(
      <AllChainsView
        chainList={chainList}
        qualitySummary={{
          snapshot_id: 'S-REAL', snapshot_version: 'v2', total_chain_count: 2,
          eligible_chain_count: 1, sturdy_count: 1, review_count: 0,
          evaluating_count: 0, unevaluated_count: 0, unavailable_count: 0,
          not_applicable_count: 1, star_counts: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 0 },
          attention_chains: [],
          chain_assessments: [
            { chain_id: 'C-REAL', member_count: 3, title: 'Observed chain', duration_seconds: 120, status: 'EVALUATED', stars: 4, label: 'Vững', reason: null },
            { chain_id: 'C-SINGLE', member_count: 1, title: 'Observed singleton', duration_seconds: null, status: 'NOT_APPLICABLE', stars: null, label: 'Singleton không chấm', reason: 'Singleton không áp dụng chấm độ vững.' },
          ],
        }}
        onSelectChain={() => {}}
      />,
    )

    expect(html).toContain('All chains')
    expect(html).toContain('C-REAL')
    expect(html).toContain('C-SINGLE')
    expect(html).toContain('Tất cả (2)')
    expect(html).toContain('Multi-alarm (1)')
    expect(html).toContain('Singleton (1)')
    expect(html).toContain('★★★★☆')
    expect(html).toContain('4/5')
    expect(html).toContain('Lọc theo sao')
    expect(html).toContain('2m')
    expect(html).not.toContain('CONDUCTANCE')
    expect(html).not.toContain('Cut Candidate')
    expect(html).not.toContain('CRITICAL')
    expect(html).not.toContain('Attribute explorer')
    expect(html).not.toContain('Tìm chain ID hoặc tiêu đề')
  })

  it('separates sturdy, review, running and waiting chain quality states', () => {
    const html = renderToStaticMarkup(
      <SnapshotOverviewView
        chainList={chainList}
        qualitySummary={{
          snapshot_id: 'S-REAL',
          snapshot_version: 'v2',
          total_chain_count: 5,
          eligible_chain_count: 4,
          sturdy_count: 1,
          review_count: 1,
          evaluating_count: 1,
          unevaluated_count: 1,
          not_applicable_count: 1,
          star_counts: { '1': 0, '2': 1, '3': 0, '4': 1, '5': 0 },
          attention_chains: [{
            chain_id: 'C-REVIEW', member_count: 3, title: 'Chain cần xem', duration_seconds: 30,
            status: 'REVIEW', stars: 2, label: 'Có dấu hiệu nên tách', reason: 'Audit thấy hai cụm tách biệt.',
          }],
        }}
        onSelectChain={() => {}}
        onNavigate={() => {}}
      />,
    )
    expect(html).toContain('1 vững')
    expect(html).toContain('1 cần xem')
    expect(html).toContain('1 đang chạy')
    expect(html).toContain('1 chờ đánh giá')
    expect(html).toContain('Singleton không áp dụng')
    expect(html).toContain('Chain cần xem trước')
    expect(html).not.toContain('Tiến độ đánh giá chất lượng')
    expect(html).not.toContain('Largest observed chains')
  })

  it('renders the snapshot portfolio from catalog and persisted summaries', () => {
    const html = renderToStaticMarkup(
      <SnapshotsPortfolioView
        snapshots={[{
          snapshot_id: 'S-REAL', name: 'Snapshot thật', profile: 'IP_NETWORK',
          alarm_count: 12, chain_count: 5, description: 'Observed data', badge: 'Live',
        }]}
        summaries={[{
          snapshot_id: 'S-REAL', snapshot_version: 'v2', total_chain_count: 5,
          eligible_chain_count: 4, sturdy_count: 2, review_count: 1,
          evaluating_count: 1, unevaluated_count: 0, not_applicable_count: 1,
          star_counts: { '1': 0, '2': 0, '3': 1, '4': 1, '5': 1 },
          attention_chains: [],
        }]}
        activeSnapshotId="S-REAL"
        selectingSnapshotId={null}
        onSelectSnapshot={() => {}}
      />,
    )
    expect(html).toContain('Toàn bộ dữ liệu đã tiếp nhận')
    expect(html).toContain('Tổng quan trạng thái snapshot')
    expect(html).toContain('Cần xem')
    expect(html).toContain('100.0%')
    expect(html).toContain('2 vững')
    expect(html).toContain('1 đang chạy')
  })

  it('derives live snapshot status buckets and percentages from current summaries', () => {
    const snapshots = ['S-OK', 'S-REVIEW', 'S-RUNNING', 'S-MISSING'].map(snapshot_id => ({
      snapshot_id,
      name: snapshot_id,
      profile: 'IP_NETWORK' as const,
      alarm_count: 4,
      chain_count: 2,
      description: 'Observed data',
      badge: 'Live',
    }))
    const base = {
      snapshot_version: 'v1', total_chain_count: 2, eligible_chain_count: 2,
      evaluating_count: 0, unevaluated_count: 0, unavailable_count: 0,
      not_applicable_count: 0, star_counts: {}, attention_chains: [],
    }
    const html = renderToStaticMarkup(
      <SnapshotsPortfolioView
        snapshots={snapshots}
        summaries={[
          { ...base, snapshot_id: 'S-OK', sturdy_count: 2, review_count: 0 },
          { ...base, snapshot_id: 'S-REVIEW', sturdy_count: 1, review_count: 1 },
          { ...base, snapshot_id: 'S-RUNNING', sturdy_count: 1, review_count: 0, evaluating_count: 1 },
        ]}
        activeSnapshotId={null}
        selectingSnapshotId={null}
        onSelectSnapshot={() => {}}
      />,
    )

    expect(html).toContain('Ổn')
    expect(html).toContain('Cần xem')
    expect(html).toContain('Đang đánh giá')
    expect(html).toContain('Chưa đủ dữ liệu')
    expect(html).toContain('25.0%')
  })

  it('treats unavailable assessments as processed without giving them a score', () => {
    const html = renderToStaticMarkup(
      <SnapshotsPortfolioView
        snapshots={[{
          snapshot_id: 'S-REAL', name: 'Snapshot thật', profile: 'IP_NETWORK',
          alarm_count: 36, chain_count: 20, description: 'Observed data', badge: 'Live',
        }]}
        summaries={[{
          snapshot_id: 'S-REAL', snapshot_version: 'v2', total_chain_count: 20,
          eligible_chain_count: 20, sturdy_count: 15, review_count: 4,
          evaluating_count: 0, unevaluated_count: 0, unavailable_count: 1,
          not_applicable_count: 0,
          star_counts: { '1': 0, '2': 0, '3': 4, '4': 15, '5': 0 },
          attention_chains: [],
        }]}
        activeSnapshotId={null}
        selectingSnapshotId={null}
        onSelectSnapshot={() => {}}
      />,
    )
    expect(html).toContain('Đã xử lý')
    expect(html).toContain('20/20')
    expect(html).toContain('100%')
    expect(html).toContain('19 có điểm')
    expect(html).toContain('1 thiếu evidence')
    expect(html).toContain('width:5%')
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

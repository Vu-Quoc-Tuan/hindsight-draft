import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ManualChainSplitModal, type AlarmItem } from './ManualChainSplitModal'
import { RecommendationsView } from '../views/RecommendationsView'
import type { ChainAnalysis } from '../types'

describe('ManualChainSplitModal', () => {
  const mockAlarms: AlarmItem[] = [
    {
      alarm_id: 'alarm_001',
      alarm_name: 'Loss of Signal Optical Port 1',
      device_code: 'SW_CORE_HANOI_01',
      role: 'ROOT',
      membership_support: 0.95,
      canonical_start_time: '2026-09-14T08:00:00Z',
    },
    {
      alarm_id: 'alarm_002',
      alarm_name: 'BGP Peer Down Session 4',
      device_code: 'RT_AGG_HADONG_02',
      role: 'CORRELATED',
      membership_support: 0.88,
      canonical_start_time: '2026-09-14T08:01:00Z',
    },
    {
      alarm_id: 'alarm_003',
      alarm_name: 'High Temperature Fan Warning',
      device_code: 'BTS_SUB_03',
      role: 'WEAK',
      membership_support: 0.35,
      canonical_start_time: '2026-09-14T08:05:00Z',
    },
  ]

  it('does not render when isOpen is false', () => {
    const html = renderToStaticMarkup(
      <ManualChainSplitModal
        isOpen={false}
        onClose={() => {}}
        chainId="chain_test_01"
        alarms={mockAlarms}
      />
    )
    expect(html).toBe('')
  })

  it('renders modal with all 4 operations tabs (SPLIT, MERGE, MOVE, REMOVE)', () => {
    const html = renderToStaticMarkup(
      <ManualChainSplitModal
        isOpen={true}
        onClose={() => {}}
        chainId="chain_test_01"
        alarms={mockAlarms}
      />
    )

    // Check title and context
    expect(html).toContain('Tùy Chỉnh Phân Hoạch Chuỗi Sự Cố (Manual Partition)')
    expect(html).toContain('Chuỗi đang xem: chain_test_01')
    expect(html).toContain('Operator Partition Studio')

    // Check all 4 operation tabs are available
    expect(html).toContain('Tách Chuỗi (Split)')
    expect(html).toContain('Ghép Chuỗi (Merge)')
    expect(html).toContain('Chuyển Cảnh Báo (Move)')
    expect(html).toContain('Loại Bỏ Nhiễu (Remove)')

    // Check alarm items rendered
    expect(html).toContain('Loss of Signal Optical Port 1')
    expect(html).toContain('SW_CORE_HANOI_01')
    expect(html).toContain('BGP Peer Down Session 4')
    expect(html).toContain('High Temperature Fan Warning')
    expect(html).toContain('WEAK')

    // Check partition group badges for split
    expect(html).toContain('Nhóm 1: Giữ lại chuỗi gốc')
    expect(html).toContain('Nhóm 2: Tách sang chuỗi mới')
    expect(html).toContain('chain_test_01::partition_custom_1')

    // Check reason policy options
    expect(html).toContain('Tô-pô mạng độc lập (Manual Topology Split)')
    expect(html).toContain('Phân vùng mạng khác biệt (Manual Domain Partition)')
    expect(html).toContain('Tái phân bổ vai trò cảnh báo (Manual Core Reassignment)')

    // Check quick filter buttons
    expect(html).toContain('Chọn cảnh báo yếu (WEAK)')
    expect(html).toContain('Lưu Phương Án (SPLIT)')
  })

  it('renders merge view with target chain selector when initialOperation is MERGE', () => {
    const html = renderToStaticMarkup(
      <ManualChainSplitModal
        isOpen={true}
        onClose={() => {}}
        chainId="chain_test_01"
        alarms={mockAlarms}
        initialOperation="MERGE"
      />
    )

    expect(html).toContain('Ghép Chuỗi (Merge)')
    expect(html).toContain('Chọn Chuỗi Sự Cố Cần Ghép (Merge Target Chain)')
    expect(html).toContain('Gộp toàn bộ 2 chuỗi')
    expect(html).toContain('Lưu Phương Án (MERGE)')
  })

  it('renders trigger button in RecommendationsView header', () => {
    const mockAnalysis: ChainAnalysis = {
      chain_id: 'C-REC-01',
      title: 'Observed Alarm Chain',
      member_count: 3,
      singleton: false,
      statistics_mode: 'EXACT',
      audit_graph_mode: 'DEFERRED',
      pair_materialization: 'LAZY',
      config_version: 'v1',
      graybox: {
        mode: 'STRICT',
        merge_strategy: null,
        rules: 0,
        characteristics: 0,
        pair_facts: 0,
        unavailable_capabilities: [],
      },
      descriptors: [],
      members: mockAlarms as any,
      role_counts: {},
      phase_durations: {},
    }

    const html = renderToStaticMarkup(<RecommendationsView analysis={mockAnalysis} />)
    expect(html).toContain('✂️ Tự Tách Chuỗi Thủ Công')
  })
})

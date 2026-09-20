import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TopologyOverlayView } from './views/TopologyOverlayView'
import type { TopologySubgraphResult } from './api'
import type { ChainAnalysis } from './types'

const mockIpAnalysis: any = {
  chain_id: '6912465',
  title: 'IP Aggregation Incident',
  member_count: 2,
  singleton: false,
  statistics_mode: 'EXACT',
  audit_graph_mode: 'COMPACT',
  pair_materialization: 'DIRECT',
  config_version: 'v1',
  graybox: {
    mode: 'EVALUATION',
    merge_strategy: null,
    rules: 0,
    characteristics: 0,
    pair_facts: 0,
    unavailable_capabilities: [],
  },
  descriptors: [],
  role_counts: {},
  phase_durations: {},
  members: [
    {
      alarm_id: 'alm-1',
      device_code: 'HTY0012AGG02',
      alarm_name: 'Link Down',
      start_time: '2026-08-27T10:00:00Z',
      end_time: '2026-08-27T10:15:00Z',
      duration_seconds: 900,
      cleared: false,
      severity: 'CRITICAL',
      extra_fields: {},
      entity_resolutions: [],
    },
    {
      alarm_id: 'alm-2',
      device_code: 'HTY3985AGG01',
      alarm_name: 'BGP Peer Down',
      start_time: '2026-08-27T10:01:00Z',
      end_time: '2026-08-27T10:15:00Z',
      duration_seconds: 840,
      cleared: false,
      severity: 'MAJOR',
      extra_fields: {},
      entity_resolutions: [],
    },
  ],
}

const mockIpSubgraph: TopologySubgraphResult = {
  status: 'AVAILABLE',
  profile_id: 'IP_NETWORK',
  nodes: [
    { id: 'HTY0012AGG02', name: 'HTY0012AGG02', type: 'AGG_DISTRICT', is_seed: true },
    { id: 'HTY3985AGG01', name: 'HTY3985AGG01', type: 'AGG_DISTRICT', is_seed: true },
    { id: 'HTY0192SRT02', name: 'HTY0192SRT02', type: 'SITE_ROUTER', is_seed: false },
    { id: 'HTY0001CORE01', name: 'HTY0001CORE01', type: 'CORE_ROUTER', is_seed: false },
    { id: 'HTY0001OLT01', name: 'HTY0001OLT01', type: 'GPON_OLT', is_seed: false },
  ],
  edges: [
    {
      id: 'e1',
      source: 'HTY0001CORE01',
      target: 'HTY0012AGG02',
      relation: 'ADJACENT_TO',
      direction_kind: 'NONE',
      dependency_semantics: 'UNVERIFIED',
    },
    {
      id: 'e2',
      source: 'HTY0012AGG02',
      target: 'HTY0192SRT02',
      relation: 'IP_ADJACENCY',
      direction_kind: 'NONE',
      dependency_semantics: 'UNVERIFIED',
    },
    {
      id: 'e3',
      source: 'HTY0192SRT02',
      target: 'HTY0001OLT01',
      relation: 'PHYSICAL_ADJACENCY',
      direction_kind: 'NONE',
      dependency_semantics: 'UNVERIFIED',
    },
  ],
}

describe('TopologyOverlayView - IP Network Multi-Tier & Hop Layout', () => {
  it('renders IP Network hop toolbar buttons and physical adjacency Vietnamese labels', () => {
    const html = renderToStaticMarkup(
      <TopologyOverlayView
        analysis={mockIpAnalysis}
        subgraphData={mockIpSubgraph}
      />
    )

    // Toolbar Hop Buttons for IP Network
    expect(html).toContain('1-Hop (Láng giềng trực tiếp)')
    expect(html).toContain('2-Hop (Mở rộng láng giềng cấp 2)')
    expect(html).not.toContain('1-Hop (Lên Module &amp; Xuống Storage/DB)')

    // Physical adjacency edge label
    expect(html).toContain('KỀ VẬT LÝ (1-HOP)')

    // Telecom roles rendered in graph
    expect(html).toContain('CORE')
    expect(html).toContain('AGG')
    expect(html).toContain('SRT')
    expect(html).toContain('OLT')

    // Telecom Legend rendered
    expect(html).toContain('CHÚ THÍCH MẠNG TRUYỀN DẪN IP')
    expect(html).toContain('Core Router (Lõi)')
    expect(html).toContain('Aggregation (PE)')
    expect(html).toContain('Site Router (Trạm)')
    expect(html).toContain('GPON OLT (Quang)')
    expect(html).toContain('Thiết bị sự cố (Gốc)')
  })

  it('preserves IT Services profile with cloud stack and IT hop buttons', () => {
    const mockItAnalysis: ChainAnalysis = {
      ...mockIpAnalysis,
      members: [
        {
          ...mockIpAnalysis.members[0],
          device_code: '10.210.48.20',
          alarm_name: 'nova_compute Container Dead',
        },
      ],
    }

    const html = renderToStaticMarkup(
      <TopologyOverlayView
        analysis={mockItAnalysis}
      />
    )

    // Toolbar Hop Buttons for IT Cloud
    expect(html).toContain('1-Hop (Lên Module &amp; Xuống Storage/DB)')
    expect(html).toContain('2-Hop (Lên Service đám mây)')

    // IT Cloud Legend rendered
    expect(html).toContain('CHÚ THÍCH HẠ TẦNG CLOUD IT')
    expect(html).toContain('IT Service lõi')
    expect(html).toContain('Module Container')
    expect(html).toContain('Máy chủ / Host')
    expect(html).toContain('Lưu trữ SAN / DB')
  })
})

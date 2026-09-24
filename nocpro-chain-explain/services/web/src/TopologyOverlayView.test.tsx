import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TopologyOverlayView } from './views/TopologyOverlayView'
import { buildAlarmConnector, getFocusNodeIds, type EvidenceTopologyPath } from './topologyGraph'
import type { TopologySubgraphResult } from './api'
import type { ChainAnalysis, ChainOverviewCards } from './types'

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
  topology_version: 'ip-v1',
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
    {
      id: 'e4',
      source: 'HTY0192SRT02',
      target: 'HTY3985AGG01',
      relation: 'IP_ADJACENCY',
      direction_kind: 'NONE',
      dependency_semantics: 'UNVERIFIED',
    },
  ],
}

const mockIpPathProjection: ChainOverviewCards = {
  snapshot_id: 'snapshot-ip',
  snapshot_version: '1',
  chain_id: mockIpAnalysis.chain_id,
  status: 'READY',
  projection_version: 'CHAIN_OVERVIEW_V3',
  reason: null,
  topology_version: 'ip-v1',
  representative_member: null,
  topology: {
    mapped: 2,
    total: 2,
    mapped_device_count: 2,
    total_device_count: 2,
    device_mapping_ratio: 1,
    resource_types: ['IP'],
    mapped_resources: ['HTY0012AGG02', 'HTY3985AGG01'],
    display_paths_truncated: false,
    display_paths: [{
      source: 'HTY0012AGG02',
      target: 'HTY3985AGG01',
      source_devices: ['HTY0012AGG02'],
      target_devices: ['HTY3985AGG01'],
      hop_count: 2,
      relation_type: 'IP_ADJACENCY',
      path: ['HTY0012AGG02', 'HTY0192SRT02', 'HTY3985AGG01'],
      traversal_semantic: 'UNDIRECTED_STRUCTURAL_CONNECTIVITY',
    }],
    dependency_verified: false,
    connected_pair_count: 1,
    pair_total: 1,
    max_path_hops: 2,
  },
  quality_assessment: null,
  recommendations: null,
}

const boundedIpSubgraph: TopologySubgraphResult = {
  ...mockIpSubgraph,
  requested_seed_count: 4,
  resolved_seed_count: 4,
  retained_seed_count: 2,
  dropped_seed_count: 2,
  truncated: true,
  truncation_reasons: ['SEED_NODE_LIMIT'],
}

describe('TopologyOverlayView - IP Network Multi-Tier & Hop Layout', () => {
  it('computes a focused neighborhood from the clicked node', () => {
    const ids = getFocusNodeIds('B', [
      { sourceId: 'A', targetId: 'B' },
      { sourceId: 'B', targetId: 'C' },
      { sourceId: 'C', targetId: 'D' },
    ])

    expect(ids).toEqual(new Set(['B', 'A', 'C']))
    expect(getFocusNodeIds(null, [])).toBeNull()
  })

  it('renders a backend four-hop witness only through matching source relations', () => {
    const connector = buildAlarmConnector(
      [
        { id: 'alarm-a' },
        { id: 'router-1' },
        { id: 'router-2' },
        { id: 'router-3' },
        { id: 'alarm-b' },
        { id: 'unrelated-olt' },
      ],
      [
        { id: 'path-1', sourceId: 'alarm-a', targetId: 'router-1', relationType: 'IP_ADJACENCY' },
        { id: 'path-2', sourceId: 'router-1', targetId: 'router-2', relationType: 'IP_ADJACENCY' },
        { id: 'path-3', sourceId: 'router-2', targetId: 'router-3', relationType: 'IP_ADJACENCY' },
        { id: 'path-4', sourceId: 'router-3', targetId: 'alarm-b', relationType: 'IP_ADJACENCY' },
        { id: 'branch', sourceId: 'router-2', targetId: 'unrelated-olt', relationType: 'OTHER_RELATION' },
      ],
      ['alarm-a', 'alarm-b'],
      [{
        source: 'alarm-a',
        target: 'alarm-b',
        hop_count: 4,
        relation_type: 'IP_ADJACENCY',
        path: ['alarm-a', 'router-1', 'router-2', 'router-3', 'alarm-b'],
      }],
    )

    expect(connector.nodeIds).toEqual(new Set([
      'alarm-a', 'router-1', 'router-2', 'router-3', 'alarm-b',
    ]))
    expect(connector.edgeIds).toEqual(new Set(['path-1', 'path-2', 'path-3', 'path-4']))
    expect(connector.connections).toEqual([
      { sourceId: 'alarm-a', targetId: 'alarm-b', hops: 4, relationType: 'IP_ADJACENCY' },
    ])
    expect(connector.linkedTerminalCount).toBe(2)
    expect(connector.componentCount).toBe(1)
    expect(connector.maxConnectionHops).toBe(4)
  })

  it('does not invent a local path when a backend witness edge is absent', () => {
    const connector = buildAlarmConnector(
      [
        { id: 'alarm-a' },
        { id: 'neighbor-a' },
        { id: 'alarm-b' },
      ],
      [{ id: 'branch-a', sourceId: 'alarm-a', targetId: 'neighbor-a', relationType: 'IP_ADJACENCY' }],
      ['alarm-a', 'alarm-b'],
      [{
        source: 'alarm-a',
        target: 'alarm-b',
        hop_count: 2,
        relation_type: 'IP_ADJACENCY',
        path: ['alarm-a', 'neighbor-a', 'alarm-b'],
      }],
    )

    expect(connector.nodeIds).toEqual(new Set(['alarm-a', 'alarm-b']))
    expect(connector.edgeIds.size).toBe(0)
    expect(connector.linkedTerminalCount).toBe(0)
    expect(connector.componentCount).toBe(2)
    expect(connector.unrenderedPathCount).toBe(1)
    expect(connector.missingPathEdgeCount).toBe(1)
  })

  it('does not treat a collapsed display edge as an original topology witness', () => {
    const connector = buildAlarmConnector(
      [
        { id: 'alarm-a' },
        { id: 'collapsed-1' },
        { id: 'alarm-b' },
      ],
      [
        { id: 'collapsed-link', sourceId: 'alarm-a', targetId: 'alarm-b', relationType: null },
      ],
      ['alarm-a', 'alarm-b'],
      [{
        source: 'alarm-a',
        target: 'alarm-b',
        hop_count: 2,
        relation_type: 'SERVICE_HAS_MODULE',
        path: ['alarm-a', 'collapsed-1', 'alarm-b'],
      }],
    )

    expect(connector.connections).toEqual([])
    expect(connector.edgeIds.size).toBe(0)
    expect(connector.unrenderedPathCount).toBe(1)
    expect(connector.missingPathEdgeCount).toBe(1)
  })

  it('rejects malformed persisted path witnesses without throwing', () => {
    const connector = buildAlarmConnector(
      [{ id: 'alarm-a' }, { id: 'alarm-b' }],
      [],
      ['alarm-a', 'alarm-b'],
      [null as unknown as EvidenceTopologyPath],
    )

    expect(connector.invalidPathCount).toBe(1)
    expect(connector.unrenderedPathCount).toBe(1)
    expect(connector.connections).toEqual([])
  })

  it('renders IP Network hop toolbar buttons and physical adjacency Vietnamese labels', () => {
    const html = renderToStaticMarkup(
      <TopologyOverlayView
        analysis={mockIpAnalysis}
        subgraphData={mockIpSubgraph}
        initialPathProjection={mockIpPathProjection}
      />
    )

    // Toolbar Hop Buttons for IP Network
    expect(html).toContain('>1-Hop</button>')
    expect(html).toContain('>2-Hop</button>')
    expect(html).toContain('>3-Hop</button>')
    expect(html).toContain('>4-Hop</button>')
    expect(html).toContain('title="Mở rộng tới 1-Hop quanh từng thiết bị alarm; tổng đường nối giữa hai thiết bị có thể dài hơn"')
    expect(html).toContain('title="Mở rộng tới 2-Hop quanh từng thiết bị alarm; tổng đường nối giữa hai thiết bị có thể dài hơn"')
    expect(html).not.toContain('1-Hop (Lên Module &amp; Xuống Storage/DB)')

    // Relation metadata remains available to the hovered edge, but is not
    // rendered as a label for every edge in the default view.
    expect(html).toContain('KỀ VẬT LÝ (1-HOP)')
    expect(html).toContain('aria-label="KỀ VẬT LÝ (1-HOP)"')
    expect(html).not.toMatch(/<text[^>]*>KỀ VẬT LÝ \(1-HOP\)<\/text>/)

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
    expect(html).toContain('Đường nối alarm (đại diện)')
    expect(html).toContain('Đường evidence (3 node)')
    expect(html).toContain('Mở toàn bộ topology đã tải, gồm cả các cạnh ngoài đường bằng chứng')
    expect(html).toContain('2 node ngoài đường bằng chứng đang thu gọn')
    expect(html).toContain('Đường backend dài nhất đang hiển thị: 2 hop')
    expect(html).toContain('topology-edge-edge-HTY0012AGG02-HTY0192SRT02-1')
    expect(html).toContain('topology-edge-edge-HTY0192SRT02-HTY3985AGG01-3')
    expect(html).not.toContain('topology-edge-edge-HTY0001CORE01-HTY0012AGG02-0')
    expect(html).not.toContain('topology-edge-edge-HTY0192SRT02-HTY0001OLT01-2')
    expect(html).not.toContain('🟢 0')
  })

  it('uses full loaded topology when the Overview path projection has a different version', () => {
    const html = renderToStaticMarkup(
      <TopologyOverlayView
        analysis={mockIpAnalysis}
        subgraphData={mockIpSubgraph}
        initialPathProjection={{ ...mockIpPathProjection, topology_version: 'ip-old' }}
      />
    )

    expect(html).toContain('Topology version của graph và Overview không trùng')
    expect(html).not.toContain('Đường evidence (')
    expect(html).toContain('aria-label="KỀ VẬT LÝ (1-HOP)"')
  })

  it('does not offer hop expansion when the Overview display forest is truncated', () => {
    const truncatedProjection: ChainOverviewCards = {
      ...mockIpPathProjection,
      topology: {
        ...mockIpPathProjection.topology!,
        display_paths_truncated: true,
        display_paths: [{
          ...mockIpPathProjection.topology!.display_paths![0],
          path: ['HTY0012AGG02', 'HTY0192SRT02-MISSING', 'HTY3985AGG01'],
        }],
      },
    }
    const html = renderToStaticMarkup(
      <TopologyOverlayView
        analysis={mockIpAnalysis}
        subgraphData={mockIpSubgraph}
        initialPathProjection={truncatedProjection}
      />
    )

    expect(html).toContain('Display forest của Overview đã chạm giới hạn 100 đường đại diện')
    expect(html).not.toContain('Tải vùng 3-Hop để lấy đủ node path')
  })

  it('does not show an empty evidence-path view when Overview has no connected pair', () => {
    const noPathProjection: ChainOverviewCards = {
      ...mockIpPathProjection,
      topology: {
        ...mockIpPathProjection.topology!,
        display_paths: [],
        display_paths_truncated: false,
        connected_pair_count: 0,
        max_path_hops: null,
      },
    }
    const html = renderToStaticMarkup(
      <TopologyOverlayView
        analysis={mockIpAnalysis}
        subgraphData={mockIpSubgraph}
        initialPathProjection={noPathProjection}
      />
    )

    expect(html).toContain('Overview không ghi nhận cặp resource nào có đường transit trong giới hạn 4 hop')
    expect(html).not.toContain('Đường evidence (')
    expect(html).toContain('aria-label="KỀ VẬT LÝ (1-HOP)"')
  })

  it('preserves IT Services profile with cloud stack and IT hop buttons', () => {
    const mockItAnalysis: ChainAnalysis = {
      ...mockIpAnalysis,
      members: [
        {
          ...mockIpAnalysis.members[0],
          device_code: '10.210.48.20',
          alarm_name: 'Host connection lost',
        },
        {
          ...mockIpAnalysis.members[1],
          device_code: '10.210.48.21',
          alarm_name: 'Peer connection lost',
        },
      ],
    }

    const mockItSubgraph: TopologySubgraphResult = {
      status: 'AVAILABLE',
      profile_id: 'IT_SERVICES',
      topology_version: 'it-v1',
      nodes: [
        { id: 'svc:nova', name: 'NOVA', type: 'SERVICE', is_seed: false },
        { id: 'mod:nova-compute', name: 'nova-compute', type: 'MODULE', is_seed: false },
        { id: 'host:20', name: '10.210.48.20', type: 'INSTANCE', is_seed: true },
        { id: 'host:21', name: '10.210.48.21', type: 'INSTANCE', is_seed: true },
        { id: 'db:orders', name: 'Orders DB', type: 'DATABASE', is_seed: false },
      ],
      edges: [
        { id: 'it-e1', source: 'svc:nova', target: 'mod:nova-compute', relation: 'SERVICE_HAS_MODULE' },
        { id: 'it-e2', source: 'mod:nova-compute', target: 'host:20', relation: 'MODULE_HAS_INSTANCE' },
        { id: 'it-e4', source: 'mod:nova-compute', target: 'host:21', relation: 'MODULE_HAS_INSTANCE' },
        { id: 'it-e3', source: 'host:20', target: 'db:orders', relation: 'DATABASE_LINKS_INSTANCE' },
      ],
    }

    const html = renderToStaticMarkup(
      <TopologyOverlayView
        analysis={mockItAnalysis}
        subgraphData={mockItSubgraph}
      />
    )

    // Toolbar Hop Buttons for IT Cloud
    expect(html).toContain('>1-Hop</button>')
    expect(html).toContain('>2-Hop</button>')
    expect(html).toContain('title="Mở rộng tới 1-Hop quanh từng thiết bị alarm; tổng đường nối giữa hai thiết bị có thể dài hơn"')
    expect(html).toContain('title="Mở rộng tới 2-Hop quanh từng thiết bị alarm; tổng đường nối giữa hai thiết bị có thể dài hơn"')

    // IT Cloud Legend rendered
    expect(html).toContain('CHÚ THÍCH HẠ TẦNG CLOUD IT')
    expect(html).toContain('IT Service lõi')
    expect(html).toContain('Module Container')
    expect(html).toContain('Máy chủ / Host')
    expect(html).toContain('Lưu trữ SAN / DB')
    expect(html).toContain('Đang tải path projection của Overview; tạm hiển thị toàn bộ topology đã tải.')
    expect(html).toContain('Service–Host qua module đã thu gọn (2 hop)')
    expect(html).not.toContain('Đường evidence (')
    expect(html).toContain('>Modules (1)</button>')
  })

  it('does not invent topology nodes when no persisted subgraph is available', () => {
    const unavailableSubgraph: TopologySubgraphResult = {
      status: 'UNAVAILABLE',
      profile_id: 'IP_NETWORK',
      reason: 'TOPOLOGY_NOT_ACTIVE',
      nodes: [],
      edges: [],
    }
    const html = renderToStaticMarkup(
      <TopologyOverlayView analysis={mockIpAnalysis} subgraphData={unavailableSubgraph} />
    )

    expect(html).toContain('Chưa có dữ liệu topology')
    expect(html).not.toContain('nova-compute')
    expect(html).not.toContain('OpenStack NOVA Cloud')
    expect(html).not.toContain('VSP-G1000 SAN Storage')
    expect(html).not.toContain('<svg')
  })

  it('discloses a bounded subgraph instead of claiming complete coverage', () => {
    const html = renderToStaticMarkup(
      <TopologyOverlayView analysis={mockIpAnalysis} subgraphData={boundedIpSubgraph} />
    )

    expect(html).toContain('Topology đang được hiển thị có giới hạn')
    expect(html).toContain('2/4 seed')
    expect(html).not.toContain('bao quát toàn bộ')
  })
})

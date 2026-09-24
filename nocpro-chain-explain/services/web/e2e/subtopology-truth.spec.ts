import { expect, test, type Page, type Route } from '@playwright/test'
import type { TopologySubgraphResult } from '../src/api'

const chainList = {
  snapshot_id: 'S-TOPOLOGY',
  snapshot_version: 'v1',
  chains: [
    {
      chain_id: 'C-TOPOLOGY',
      member_count: 2,
      is_singleton: false,
      title: 'Topology fixture',
      start_time: '2026-09-21T00:00:00Z',
      end_time: '2026-09-21T00:01:00Z',
      duration_seconds: 60,
    },
  ],
}

const analysis = {
  chain_id: 'C-TOPOLOGY',
  title: 'Topology fixture',
  member_count: 2,
  singleton: false,
  statistics_mode: 'EXACT_INDEXED',
  audit_graph_mode: 'DEFERRED_TO_TIER2',
  pair_materialization: 'LAZY',
  config_version: 'cfg-topology',
  graybox: { mode: 'STRICT', merge_strategy: null, rules: 0, characteristics: 0, pair_facts: 0, unavailable_capabilities: [] },
  descriptors: [],
  members: [
    { alarm_id: 'A-1', alarm_name: 'Link down', device_code: 'SEED-A', node_reference: null, canonical_start_time: null, role: 'CORE', membership_support: null, availability_coverage: 0, computable_groups: 0, representativeness: null, group_fits: [], margins: [], redundancy_role: null, failure_domains: [], entity_resolutions: [] },
    { alarm_id: 'A-2', alarm_name: 'Peer down', device_code: 'SEED-B', node_reference: null, canonical_start_time: null, role: 'WEAK', membership_support: null, availability_coverage: 0, computable_groups: 0, representativeness: null, group_fits: [], margins: [], redundancy_role: null, failure_domains: [], entity_resolutions: [] },
  ],
  role_counts: {},
  phase_durations: {},
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function installBaseApi(
  page: Page,
  subgraph: (route: Route) => Promise<void>,
  profile: 'IP_NETWORK' | 'IT_SERVICES' = 'IP_NETWORK',
  chainAnalysis: typeof analysis = analysis,
) {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/v1/health') return fulfillJson(route, { status: 'ok' })
    if (url.pathname === '/api/v1/config') return fulfillJson(route, { config_version: 'cfg-topology' })
    if (url.pathname === '/api/v1/snapshots') return fulfillJson(route, {
      active_snapshot_id: 'S-TOPOLOGY',
      active_snapshot_version: 'v1',
      snapshots: [{
        snapshot_id: 'S-TOPOLOGY', snapshot_version: 'v1', name: 'Topology fixture',
        profile, alarm_count: chainAnalysis.members.length, chain_count: 1, description: '', badge: 'test',
      }],
    })
    if (url.pathname === '/api/v1/snapshots/quality-summaries') return fulfillJson(route, { summaries: [] })
    if (url.pathname === '/api/v1/chains') return fulfillJson(route, chainList)
    if (url.pathname === '/api/v1/chains/C-TOPOLOGY') return fulfillJson(route, chainAnalysis)
    if (url.pathname === '/api/v1/chains/C-TOPOLOGY/overview-cards') return fulfillJson(route, {
      snapshot_id: 'S-TOPOLOGY', snapshot_version: 'v1', chain_id: 'C-TOPOLOGY',
      status: 'READY', projection_version: 'topology-test', reason: null,
      representative_member: null, topology: null, quality_assessment: null, recommendations: null,
    })
    if (url.pathname === '/api/v1/chains/C-TOPOLOGY/deep-dive') return fulfillJson(route, null)
    if (url.pathname === '/api/v1/chains/C-TOPOLOGY/cohesion-narrative') return fulfillJson(route, {
      chain_id: 'C-TOPOLOGY', narrative: 'Topology test fixture.', model: 'DETERMINISTIC_EVIDENCE', provider_status: 'NOT_CONFIGURED',
      context: {
        chain: { chain_id: 'C-TOPOLOGY', alarm_count: 2, duration_seconds: 60, is_singleton: false },
        alarm_summary: { top_alarm_types: [['Link down', 1], ['Peer down', 1]], network_classes: [], device_types: [], devices: ['SEED-A', 'SEED-B'] },
        why: { strong_views: [], partial_views: [], top_descriptors: [] },
        topology: { mapped: 2, total: 2, mapped_device_count: 2, total_device_count: 2, device_mapping_ratio: 1, resource_types: [], dependency_verified: false, connected_pair_count: 1, pair_total: 1 },
        audit: { status: 'UNAVAILABLE', candidate_cut: false, conductance: null },
        recommendations: { status: 'NO_RECOMMENDATION', count: 0, split_recommended: false },
        quality_assessment: { method: 'HEURISTIC_V1', status: 'EVALUATED', stars: 3, label: 'Cần kiểm tra', reasons: [], available_dimension_count: 2 },
      },
    })
    if (url.pathname === '/api/v1/topology/projection') return fulfillJson(route, {
      status: 'AVAILABLE',
      profile,
      topology_kind: profile === 'IP_NETWORK' ? 'PHYSICAL_ADJACENCY' : 'SERVICE_DEPENDENCY',
      source_version: 'topology-v1',
      tree: null,
    })
    if (url.pathname === '/api/v1/topology/subgraph') return subgraph(route)
    return fulfillJson(route, { detail: 'NOT_AVAILABLE_IN_SUBTOPOLOGY_FIXTURE' }, 404)
  })
}

async function openTopology(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'All Chains', exact: true }).click()
  await page.getByText('C-TOPOLOGY', { exact: true }).click()
  await expect(page.getByText('C-TOPOLOGY', { exact: true })).toBeVisible()
  await page.getByTitle('Sơ đồ chiếu mạng và tương quan topo').click()
}

test('unavailable persisted topology shows no inferred graph', async ({ page }) => {
  await installBaseApi(page, route => fulfillJson(route, {
    status: 'UNAVAILABLE',
    reason: 'TOPOLOGY_NOT_ACTIVE',
    profile_id: 'IP_NETWORK',
    nodes: [],
    edges: [],
    requested_seed_count: 2,
    resolved_seed_count: 0,
    retained_seed_count: 0,
    dropped_seed_count: 0,
    truncated: false,
    truncation_reasons: [],
  }))

  await openTopology(page)

  await expect(page.getByText('Chưa có dữ liệu topology')).toBeVisible()
  await expect(page.locator('#canvas-bg svg')).toHaveCount(0)
  await expect(page.getByText('nova-compute')).toHaveCount(0)
  await expect(page.getByText('OpenStack NOVA Cloud')).toHaveCount(0)
  await expect(page.getByText('VSP-G1000 SAN Storage')).toHaveCount(0)
})

test('changing hop clears the old graph and discloses the bounded replacement', async ({ page }) => {
  let releaseOneHop!: () => void
  const oneHopReady = new Promise<void>(resolve => { releaseOneHop = resolve })

  await installBaseApi(page, async route => {
    const url = new URL(route.request().url())
    if (url.searchParams.get('hops') === '1') {
      await oneHopReady
    return fulfillJson(route, {
      status: 'AVAILABLE', profile_id: 'IP_NETWORK', topology_version: 'v2',
        nodes: [
          { id: 'NEW-NODE', name: 'NEW-NODE', type: 'DEVICE', is_seed: true },
          { id: 'NEW-NEIGHBOR', name: 'NEW-NEIGHBOR', type: 'DEVICE', is_seed: false },
        ],
        edges: [{ id: 'edge-new', source: 'NEW-NODE', target: 'NEW-NEIGHBOR', relation: 'IP_ADJACENCY' }],
        requested_seed_count: 2, resolved_seed_count: 1, retained_seed_count: 1,
        dropped_seed_count: 0, truncated: true, truncation_reasons: ['EDGE_QUERY_LIMIT'],
      })
    }
    return fulfillJson(route, {
      status: 'AVAILABLE', profile_id: 'IP_NETWORK', topology_version: 'v1',
      nodes: [
        { id: 'OLD-NODE', name: 'OLD-NODE', type: 'DEVICE', is_seed: true },
        { id: 'OLD-NEIGHBOR', name: 'OLD-NEIGHBOR', type: 'DEVICE', is_seed: false },
      ],
      edges: [{ id: 'edge-old', source: 'OLD-NODE', target: 'OLD-NEIGHBOR', relation: 'IP_ADJACENCY' }],
      requested_seed_count: 2, resolved_seed_count: 1, retained_seed_count: 1,
      dropped_seed_count: 0, truncated: false, truncation_reasons: [],
    })
  })

  await openTopology(page)
  await expect(page.getByText('OLD-NODE', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Đường nối alarm (1 node)' }).click()
  await expect(page.getByRole('button', { name: 'Toàn bộ topology (2 node)' })).toBeVisible()
  await expect(page.getByText('OLD-NEIGHBOR', { exact: true })).toBeVisible()

  await page.getByText('OLD-NEIGHBOR', { exact: true }).click()
  await expect(page.getByTestId('topology-focus-indicator')).toHaveCount(0)
  const alarmPanel = page.locator('#canvas-bg [role="dialog"]')
  await expect(alarmPanel).toBeVisible()
  await expect(alarmPanel).toContainText('1-Hop')
  await expect(alarmPanel).not.toContainText('Láng giềng')
  const canvasBox = await page.locator('#canvas-bg').boundingBox()
  const panelBox = await alarmPanel.boundingBox()
  expect(canvasBox).not.toBeNull()
  expect(panelBox).not.toBeNull()
  expect(panelBox!.y).toBeGreaterThanOrEqual(canvasBox!.y)
  expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(canvasBox!.y + canvasBox!.height)
  await alarmPanel.getByLabel('Đóng').click()
  await expect(page.getByTestId('topology-focus-indicator')).toHaveCount(0)
  await expect(alarmPanel).toHaveCount(0)

  await page.getByRole('button', { name: '1-Hop', exact: true }).click()
  await expect(page.getByText('Đang tải topology thật 1-Hop…')).toBeVisible()
  await expect(page.getByText('OLD-NODE', { exact: true })).toHaveCount(0)

  releaseOneHop()
  await expect(page.getByText('NEW-NODE', { exact: true })).toBeVisible()
  await expect(page.getByText('Topology đang được hiển thị có giới hạn.')).toBeVisible()
  await expect(page.getByText(/Đã phân giải 1\/2 seed và giữ 1\/1 seed/)).toBeVisible()
})

test('alarm connector hides dangling branches and full-topology mode restores them', async ({ page }) => {
  const consoleErrors: string[] = []
  const httpErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('response', response => {
    if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`)
  })

  await installBaseApi(page, route => fulfillJson(route, {
    status: 'AVAILABLE',
    profile_id: 'IP_NETWORK',
    topology_version: 'topology-v1',
    nodes: [
      { id: 'SEED-A', name: 'SEED-A', type: 'AGG_DISTRICT', is_seed: true },
      { id: 'SEED-B', name: 'SEED-B', type: 'AGG_DISTRICT', is_seed: true },
      { id: 'ROUTER-01', name: 'ROUTER-01', type: 'SITE_ROUTER', is_seed: false },
      { id: 'CORE-01', name: 'CORE-01', type: 'CORE_ROUTER', is_seed: false },
      { id: 'OLT-01', name: 'OLT-01', type: 'GPON_OLT', is_seed: false },
    ],
    edges: [
      { id: 'core-branch', source: 'CORE-01', target: 'SEED-A', relation: 'IP_ADJACENCY' },
      { id: 'alarm-path-a', source: 'SEED-A', target: 'ROUTER-01', relation: 'IP_ADJACENCY' },
      { id: 'olt-branch', source: 'ROUTER-01', target: 'OLT-01', relation: 'IP_ADJACENCY' },
      { id: 'alarm-path-b', source: 'ROUTER-01', target: 'SEED-B', relation: 'IP_ADJACENCY' },
    ],
    requested_seed_count: 2,
    resolved_seed_count: 2,
    retained_seed_count: 2,
    dropped_seed_count: 0,
    truncated: false,
    truncation_reasons: [],
  }))

  await openTopology(page)
  const canvas = page.locator('#canvas-bg')

  await expect(canvas.getByText('SEED-A', { exact: true })).toBeVisible()
  await expect(canvas.getByText('SEED-B', { exact: true })).toBeVisible()
  await expect(canvas.getByText('ROUTER-01', { exact: true })).toBeVisible()
  await expect(canvas.getByText('CORE-01', { exact: true })).toHaveCount(0)
  await expect(canvas.getByText('OLT-01', { exact: true })).toHaveCount(0)
  await expect(canvas.locator('[data-testid^="topology-edge-"]')).toHaveCount(2)

  await page.getByRole('button', { name: 'Đường nối alarm (3 node)' }).click()

  await expect(page.getByRole('button', { name: 'Toàn bộ topology (5 node)' })).toBeVisible()
  await expect(canvas.getByText('CORE-01', { exact: true })).toBeVisible()
  await expect(canvas.getByText('OLT-01', { exact: true })).toBeVisible()
  await expect(canvas.locator('[data-testid^="topology-edge-"]')).toHaveCount(4)

  await canvas.getByText('CORE-01', { exact: true }).click()
  await expect(canvas.locator('[role="dialog"]')).toBeVisible()
  await page.getByRole('button', { name: 'Toàn bộ topology (5 node)' }).click()
  await expect(page.getByRole('button', { name: 'Đường nối alarm (3 node)' })).toBeVisible()
  await expect(canvas.locator('[role="dialog"]')).toHaveCount(0)
  await expect(canvas.getByText('CORE-01', { exact: true })).toHaveCount(0)
  await expect(canvas.locator('[data-testid^="topology-edge-"]')).toHaveCount(2)
  expect({ consoleErrors, httpErrors }).toEqual({ consoleErrors: [], httpErrors: [] })
})

test('full IT topology restores collapsed modules and all fetched instances', async ({ page }) => {
  const hostNumbers = Array.from({ length: 15 }, (_, index) => index + 20)
  const hosts = hostNumbers.map(number => ({
    id: `host:${number}`,
    name: `10.210.48.${number}`,
    type: 'INSTANCE',
    is_seed: number === 20 || number === 34,
  }))
  const itSubgraph: TopologySubgraphResult = {
    status: 'AVAILABLE',
    profile_id: 'IT_SERVICES',
    topology_version: 'it-topology-v1',
    nodes: [
      { id: 'svc:nova', name: 'NOVA', type: 'SERVICE', is_seed: false },
      { id: 'mod:nova-compute', name: 'nova-compute', type: 'MODULE', is_seed: false },
      ...hosts,
    ],
    edges: [
      { id: 'service-module', source: 'svc:nova', target: 'mod:nova-compute', relation: 'SERVICE_HAS_MODULE' },
      ...hosts.map(host => ({
        id: `module-${host.id}`,
        source: 'mod:nova-compute',
        target: host.id,
        relation: 'MODULE_HAS_INSTANCE',
      })),
    ],
  }
  const itAnalysis = {
    ...analysis,
    members: [
      { ...analysis.members[0], device_code: '10.210.48.20', alarm_name: 'Host connection lost' },
      { ...analysis.members[1], device_code: '10.210.48.34', alarm_name: 'Peer connection lost' },
    ],
  }

  await installBaseApi(page, route => fulfillJson(route, itSubgraph), 'IT_SERVICES', itAnalysis)
  await openTopology(page)
  const canvas = page.locator('#canvas-bg')

  await expect(page.getByText('Đường nối đại diện dài nhất: 4 hop')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Đường nối alarm (3 node)' })).toBeVisible()
  await expect(canvas.getByText('10.210.48.20', { exact: true })).toBeVisible()
  await expect(canvas.getByText('10.210.48.34', { exact: true })).toBeVisible()
  await expect(canvas.getByText('nova-compute', { exact: true })).toHaveCount(0)
  await expect(canvas.getByText('10.210.48.21', { exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'Đường nối alarm (3 node)' }).click()

  await expect(page.getByRole('button', { name: 'Toàn bộ topology (17 node)' })).toBeVisible()
  await expect(canvas.getByText('nova-compute', { exact: true })).toBeVisible()
  await expect(canvas.getByText('10.210.48.21', { exact: true })).toBeVisible()
  await expect(canvas.locator('[data-testid^="topology-edge-"]')).toHaveCount(16)
  await expect(page.getByRole('button', { name: /Modules \(/ })).toHaveCount(0)
})

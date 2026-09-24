import { expect, test } from '@playwright/test'

test('Overview path witness loads a pinned four-hop graph before highlighting', async ({ page }) => {
  const subgraphRequests: URL[] = []
  const pageErrors: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))

  const snapshotId = 'snapshot-path-e2e'
  const snapshotVersion = '1'
  const chainId = 'CHAIN-PATH-E2E'
  const topologyVersion = 'ip-path-v1'

  const analysis = {
    chain_id: chainId,
    title: 'Four-hop path fixture',
    member_count: 2,
    singleton: false,
    statistics_mode: 'EXACT_INDEXED',
    audit_graph_mode: 'DEFERRED_TO_TIER2',
    pair_materialization: 'LAZY',
    config_version: 'config-e2e',
    graybox: {
      mode: 'STRICT', merge_strategy: null, rules: 0,
      characteristics: 0, pair_facts: 0, unavailable_capabilities: [],
    },
    descriptors: [],
    role_counts: {},
    phase_durations: {},
    members: ['R1', 'R2'].map((device, index) => ({
      alarm_id: `alarm-${index + 1}`,
      alarm_name: index === 0 ? 'Link Down' : 'Peer Down',
      device_code: device,
      node_reference: device,
      canonical_start_time: `2026-09-24T10:0${index}:00Z`,
      start_time: `2026-09-24T10:0${index}:00Z`,
      end_time: null,
      duration_seconds: null,
      cleared: false,
      severity: 'MAJOR',
      role: index === 0 ? 'CORE' : 'WEAK',
      membership_support: 0.8,
      availability_coverage: 1,
      computable_groups: 1,
      representativeness: 0.8,
      group_fits: [],
      margins: [],
      redundancy_role: null,
      failure_domains: [],
      entity_resolutions: [],
    })),
  }

  const overviewCards = {
    snapshot_id: snapshotId,
    snapshot_version: snapshotVersion,
    chain_id: chainId,
    status: 'READY',
    projection_version: 'CHAIN_OVERVIEW_V3',
    reason: null,
    topology_version: topologyVersion,
    representative_member: null,
    topology: {
      mapped: 2,
      total: 2,
      mapped_device_count: 2,
      total_device_count: 2,
      device_mapping_ratio: 1,
      resource_types: ['IP'],
      mapped_resources: ['R1', 'R2'],
      display_paths_truncated: false,
      display_paths: [{
        source: 'R1',
        target: 'R2',
        source_devices: ['R1'],
        target_devices: ['R2'],
        hop_count: 4,
        relation_type: 'IP_ADJACENCY',
        path: ['R1', 'X1', 'X2', 'X3', 'R2'],
        traversal_semantic: 'UNDIRECTED_STRUCTURAL_CONNECTIVITY',
      }],
      dependency_verified: false,
      connected_pair_count: 1,
      pair_total: 1,
      max_path_hops: 4,
    },
    quality_assessment: null,
    recommendations: null,
  }

  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    const { pathname, searchParams } = url
    let body: unknown = {}

    if (pathname.endsWith('/health')) {
      body = { status: 'ok' }
    } else if (pathname.endsWith('/snapshots/quality-summaries')) {
      body = { summaries: [{
        snapshot_id: snapshotId,
        snapshot_version: snapshotVersion,
        total_chain_count: 1,
        eligible_chain_count: 1,
        sturdy_count: 0,
        review_count: 0,
        evaluating_count: 0,
        unevaluated_count: 1,
        unavailable_count: 0,
        not_applicable_count: 0,
        star_counts: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
        attention_chains: [{
          chain_id: chainId,
          member_count: 2,
          title: 'Four-hop path fixture',
          duration_seconds: 60,
          status: 'WAITING',
          stars: null,
          label: 'Đang chờ đánh giá',
          reason: null,
        }],
      }] }
    } else if (pathname.endsWith('/snapshots')) {
      body = {
        active_snapshot_id: snapshotId,
        active_snapshot_version: snapshotVersion,
        snapshots: [{
          snapshot_id: snapshotId,
          snapshot_version: snapshotVersion,
          name: 'Path E2E',
          profile: 'IP_NETWORK',
          alarm_count: 2,
          chain_count: 1,
          description: 'Browser-only fixture',
          badge: 'E2E',
          available: true,
        }],
      }
    } else if (pathname.endsWith('/chains')) {
      body = {
        snapshot_id: snapshotId,
        snapshot_version: snapshotVersion,
        chains: [{
          chain_id: chainId,
          member_count: 2,
          is_singleton: false,
          title: 'Four-hop path fixture',
          start_time: '2026-09-24T10:00:00Z',
          end_time: '2026-09-24T10:01:00Z',
          duration_seconds: 60,
        }],
      }
    } else if (pathname.endsWith(`/chains/${chainId}/overview-cards`)) {
      body = overviewCards
    } else if (pathname.endsWith(`/chains/${chainId}/deep-dive`)) {
      body = null
    } else if (pathname.endsWith(`/chains/${chainId}`)) {
      body = analysis
    } else if (pathname.endsWith('/topology/projection')) {
      body = {
        status: 'UNAVAILABLE',
        profile: 'IP_NETWORK',
        topology_kind: 'UNAVAILABLE',
        reason: 'FIXTURE_USES_SUBGRAPH_ENDPOINT',
      }
    } else if (pathname.endsWith('/topology/subgraph')) {
      subgraphRequests.push(url)
      const complete = Number(searchParams.get('hops')) >= 4
      const nodes = complete
        ? ['R1', 'X1', 'X2', 'X3', 'R2']
        : ['R1', 'X1', 'X3', 'R2']
      const pairs: Array<[string, string]> = complete
        ? [['R1', 'X1'], ['X1', 'X2'], ['X2', 'X3'], ['X3', 'R2']]
        : [['R1', 'X1'], ['X3', 'R2']]
      body = {
        status: 'AVAILABLE',
        profile_id: 'IP_NETWORK',
        topology_version: topologyVersion,
        nodes: nodes.map(id => ({
          id,
          name: id,
          type: id.startsWith('R') ? 'SITE_ROUTER' : 'AGG_DISTRICT',
          is_seed: id === 'R1' || id === 'R2',
        })),
        edges: pairs.map(([source, target], index) => ({
          id: `path-edge-${index}`,
          source,
          target,
          relation: 'IP_ADJACENCY',
          direction_kind: 'NONE',
          dependency_semantics: 'UNAVAILABLE',
        })),
        requested_seed_count: 2,
        resolved_seed_count: 2,
        retained_seed_count: 2,
        dropped_seed_count: 0,
        truncated: false,
        truncation_reasons: [],
      }
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: chainId }).click()
  await page.getByRole('button', { name: 'Topology' }).click()

  await expect(page.getByText(/Thiếu 1 node thuộc path Overview/)).toBeVisible()
  const expandPathButton = page.getByRole('button', { name: 'Tải vùng 4-Hop để lấy đủ node path' })
  await expect(expandPathButton).toBeVisible()
  await expandPathButton.click()

  await expect.poll(() => subgraphRequests.some(request => (
    request.searchParams.get('hops') === '4'
    && request.searchParams.get('version') === topologyVersion
  ))).toBe(true)
  await expect(page.getByRole('button', { name: 'Đường evidence (5 node)' })).toBeVisible()
  await expect(page.getByText('Đường backend dài nhất đang hiển thị: 4 hop')).toBeVisible()
  await page.screenshot({ path: '/tmp/hindsight-topology-evidence-paths.png', fullPage: true })
  await page.getByRole('button', { name: 'Đường evidence (5 node)' }).click()
  await expect(page.getByRole('button', { name: 'Toàn bộ topology (5 node)' })).toBeVisible()

  expect(pageErrors).toEqual([])
})

import { expect, test } from '@playwright/test'

test('Overview path witness loads a pinned four-hop graph before highlighting', async ({ page }) => {
  const subgraphRequests: URL[] = []
  const overviewRequests: URL[] = []
  const evidenceRequests: Array<{ url: URL; headers: Record<string, string> }> = []
  const writeRequests: Array<{ method: string; url: string }> = []
  const pageErrors: string[] = []
  const consoleFailures: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => {
    if (message.type() === 'error' || message.type() === 'warning') {
      consoleFailures.push(`${message.type()}: ${message.text()}`)
    }
  })
  page.on('request', request => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      writeRequests.push({ method: request.method(), url: request.url() })
    }
  })

  const snapshotId = 'snapshot-path-e2e'
  const snapshotVersion = '1'
  const chainId = 'CHAIN-PATH-E2E'
  const topologyVersion = 'ip-path-v1'
  const evidenceId = `ev1_${'a'.repeat(64)}`
  const mappingEvidenceId = `ev1_${'b'.repeat(64)}`
  const analysisIdentity = {
    identity_version: 'analysis-identity-v1',
    snapshot_id: snapshotId,
    snapshot_version: snapshotVersion,
    chain_id: chainId,
    topology_version: topologyVersion,
    analysis_config_version: 'config-e2e',
    review_config_version: 'review-config-e2e',
    pipeline_version: 'DETERMINISTIC_QUALITY_V6',
    input_fingerprint: 'evidence-e2e-fingerprint',
  }

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
    projection_version: 'CHAIN_OVERVIEW_V6',
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
        max_hops: 4,
        relation_type: 'IP_ADJACENCY',
        path: ['R1', 'X1', 'X2', 'X3', 'R2'],
        traversal_semantic: 'UNDIRECTED_STRUCTURAL_CONNECTIVITY',
        mapping_statuses: ['EXACT', 'EXACT'],
      }],
      dependency_verified: false,
      connected_pair_count: 1,
      pair_total: 1,
      max_path_hops: 4,
    },
    quality_assessment: {
      method: 'HEURISTIC_V1',
      status: 'EVALUATED',
      readiness: 'READY',
      reason_codes: ['TOPOLOGY_MAPPING_INCOMPLETE'],
      evidence_coverage: {},
      evidence_ids: [evidenceId, mappingEvidenceId],
      reason_evidence_ids: { TOPOLOGY_MAPPING_INCOMPLETE: [evidenceId] },
      readiness_policy_version: 'quality-readiness-v1',
      observed_evidence_families: ['membership', 'topology'],
      stars: 4,
      label: 'Khá vững',
      reasons: ['Mapping topology chưa bao phủ đủ alarm và thiết bị.'],
      available_dimension_count: 4,
    },
    recommendations: null,
    analysis_identity: analysisIdentity,
    artifact_revision: {
      resource_kind: 'chain_overview',
      fingerprint: analysisIdentity.input_fingerprint,
    },
  }

  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    const { pathname, searchParams } = url
    let body: unknown = {}

    if (pathname.endsWith('/health')) {
      body = { status: 'ok' }
    } else if (pathname.endsWith(`/chains/${chainId}/evidence`)) {
      evidenceRequests.push({ url, headers: route.request().headers() })
      body = {
        analysis_identity: analysisIdentity,
        records: [
          {
            evidence_id: mappingEvidenceId,
            analysis_identity: analysisIdentity,
            kind: 'MAPPING',
            status: 'AVAILABLE',
            statement_kind: 'OBSERVED',
            source_artifact_id: null,
            source_fingerprint: analysisIdentity.input_fingerprint,
            summary: 'Đã ánh xạ 2/2 cảnh báo vào tài nguyên topology.',
            reason_codes: [],
            limitations: ['MAPPING_DOES_NOT_ESTABLISH_DEPENDENCY'],
            path: null,
          },
          {
            evidence_id: evidenceId,
            analysis_identity: analysisIdentity,
            kind: 'TOPOLOGY_PATH',
            status: 'AVAILABLE',
            statement_kind: 'DERIVED',
            source_artifact_id: null,
            source_fingerprint: analysisIdentity.input_fingerprint,
            summary: 'Đường Overview R1 đến R2 gồm 4 hop trong giới hạn 4 hop.',
            reason_codes: [],
            limitations: ['TRANSIT_CONNECTIVITY_IS_NOT_CAUSAL_DEPENDENCY'],
            path: {
              resource_ids: ['R1', 'X1', 'X2', 'X3', 'R2'],
              relation_types: ['IP_ADJACENCY', 'IP_ADJACENCY', 'IP_ADJACENCY', 'IP_ADJACENCY'],
              hop_count: 4,
              traversal_semantic: 'UNDIRECTED_STRUCTURAL_CONNECTIVITY',
              max_hops: 4,
              topology_version: topologyVersion,
              mapping_statuses: ['EXACT', 'EXACT'],
              analysis_truncated: false,
              direction_policy: 'UNDIRECTED',
            },
          },
        ],
        truncated: false,
        next_cursor: null,
      }
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
        topology_version: topologyVersion,
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
      overviewRequests.push(url)
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

  const starButton = page.getByRole('button', { name: 'Mở evidence đánh giá 4 trên 5 sao' })
  await expect(starButton).toBeVisible()
  await expect.poll(() => overviewRequests.length).toBe(1)
  const writesBeforeStar = writeRequests.length
  await starButton.click()
  const evidenceDrawer = page.getByTestId('evidence-details-dialog')
  await expect(evidenceDrawer).toBeVisible()
  await expect(evidenceDrawer.getByTestId(`evidence-record-${mappingEvidenceId}`)).toBeVisible()
  await expect(evidenceDrawer.getByTestId(`evidence-record-${evidenceId}`)).toBeVisible()
  expect(writeRequests.slice(writesBeforeStar)).toEqual([])
  await page.keyboard.press('Escape')
  await expect(starButton).toBeFocused()

  const reasonEvidenceButton = page.getByRole('button', {
    name: 'Mở 1 evidence cho lý do TOPOLOGY_MAPPING_INCOMPLETE',
  })
  const writesBeforeReason = writeRequests.length
  await reasonEvidenceButton.click()
  await expect(evidenceDrawer).toBeVisible()
  await expect(evidenceDrawer.getByTestId(`evidence-record-${evidenceId}`)).toBeVisible()
  await expect(evidenceDrawer.getByTestId(`evidence-record-${mappingEvidenceId}`)).toHaveCount(0)
  expect(writeRequests.slice(writesBeforeReason)).toEqual([])
  await page.keyboard.press('Escape')
  await expect(reasonEvidenceButton).toBeFocused()

  await page.getByRole('button', { name: 'lan Topology' }).click()

  await expect(page.getByText(/Thiếu 1 node thuộc path Overview/)).toBeVisible()
  const expandPathButton = page.getByRole('button', { name: 'Tải vùng 4-Hop để lấy đủ node path' })
  await expect(expandPathButton).toBeVisible()
  await expandPathButton.click()

  await expect.poll(() => subgraphRequests.some(request => (
    request.searchParams.get('hops') === '4'
    && request.searchParams.get('version') === topologyVersion
  ))).toBe(true)
  await expect(page.getByRole('button', { name: 'Đường evidence (5 node)' })).toBeVisible()
  expect(overviewRequests).toHaveLength(1)
  await expect(page.getByText('Đường backend dài nhất đang hiển thị: 4 hop')).toBeVisible()
  await page.screenshot({ path: '/tmp/hindsight-topology-evidence-paths.png', fullPage: true })
  await page.getByRole('button', { name: 'Đường evidence (5 node)' }).click()
  await expect(page.getByRole('button', { name: 'Toàn bộ topology (5 node)' })).toBeVisible()

  const evidenceEdge = page.getByRole('button', { name: 'KỀ VẬT LÝ (1-HOP)' }).first()
  await evidenceEdge.focus()
  const writesBeforeEvidenceOpen = writeRequests.length
  await evidenceEdge.click()
  const drawer = page.getByTestId('evidence-details-dialog').last()
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText(/Đường Overview R1 đến R2 gồm 4 hop/)).toBeVisible()
  await expect(drawer.getByText('R1 → X1 → X2 → X3 → R2')).toBeVisible()
  await page.screenshot({ path: '/tmp/hindsight-evidence-drawer.png', fullPage: true })
  await expect.poll(() => evidenceRequests.length).toBe(3)
  expect(evidenceRequests[0].headers['x-nocpro-snapshot-id']).toBe(snapshotId)
  expect(evidenceRequests[0].headers['x-nocpro-snapshot-version']).toBe(snapshotVersion)
  expect(evidenceRequests[0].headers['x-nocpro-topology-version']).toBe(topologyVersion)
  expect(writeRequests.slice(writesBeforeEvidenceOpen)).toEqual([])

  await page.keyboard.press('Escape')
  await expect(drawer).not.toBeVisible()
  await expect(evidenceEdge).toBeFocused()

  expect(pageErrors).toEqual([])
  expect(consoleFailures).toEqual([])
})

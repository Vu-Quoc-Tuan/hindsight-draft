import { expect, test, type Page, type Route } from '@playwright/test'

const chains = {
  snapshot_id: 'S-BROWSER',
  snapshot_version: 'v1',
  chains: [
    { chain_id: 'C-A', member_count: 3, is_singleton: false, title: 'Observed A', start_time: '2026-09-06T10:00:00Z', end_time: '2026-09-06T10:02:00Z', duration_seconds: 120 },
    { chain_id: 'C-B', member_count: 1, is_singleton: true, title: 'Observed B', start_time: null, end_time: null, duration_seconds: null },
  ],
}

function analysis(chainId: string) {
  return {
    chain_id: chainId,
    title: `Analysis ${chainId}`,
    member_count: chainId === 'C-A' ? 3 : 1,
    singleton: chainId === 'C-B',
    statistics_mode: 'EXACT_INDEXED',
    audit_graph_mode: 'DEFERRED_TO_TIER2',
    pair_materialization: 'LAZY',
    config_version: 'cfg-browser',
    graybox: { mode: 'STRICT', merge_strategy: null, rules: 0, characteristics: 0, pair_facts: 0, unavailable_capabilities: [] },
    descriptors: [],
    members: chainId === 'C-A' ? [
      { alarm_id: 'A-1', alarm_name: 'Observed alarm one', device_code: null, node_reference: null, canonical_start_time: null, role: 'CORE', membership_support: null, availability_coverage: 0, computable_groups: 0, representativeness: null, group_fits: [], margins: [], redundancy_role: null, failure_domains: [] },
      { alarm_id: 'A-2', alarm_name: 'Observed alarm two', device_code: null, node_reference: null, canonical_start_time: null, role: 'WEAK', membership_support: 0.7, availability_coverage: 1, computable_groups: 1, representativeness: null, group_fits: [], margins: [], redundancy_role: null, failure_domains: [] },
      { alarm_id: 'A-3', alarm_name: 'Observed alarm three', device_code: null, node_reference: null, canonical_start_time: null, role: 'CORE', membership_support: 0.8, availability_coverage: 1, computable_groups: 1, representativeness: null, group_fits: [], margins: [], redundancy_role: null, failure_domains: [] },
    ] : [
      { alarm_id: 'B-1', alarm_name: 'Observed singleton', device_code: null, node_reference: null, canonical_start_time: null, role: 'SINGLETON', membership_support: null, availability_coverage: 0, computable_groups: 0, representativeness: null, group_fits: [], margins: [], redundancy_role: null, failure_domains: [] },
    ],
    role_counts: {},
    phase_durations: {},
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function installApi(page: Page, delayedB?: Promise<void>, assistantContexts?: Array<Record<string, unknown>>) {
  await page.route('**/api/topology/**', route => fulfillJson(route, {
    status: 'UNAVAILABLE',
    reason: 'TOPOLOGY_FIXTURE_UNAVAILABLE',
    profile: 'IP_NETWORK',
    topology_kind: 'UNAVAILABLE',
  }))
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/v1/health') return fulfillJson(route, { status: 'ok' })
    if (url.pathname === '/api/v1/config') return fulfillJson(route, { config_version: 'cfg-browser' })
    if (url.pathname === '/api/v1/chains') return fulfillJson(route, chains)
    if (url.pathname === '/api/v1/chains/C-A') return fulfillJson(route, analysis('C-A'))
    if (url.pathname === '/api/v1/chains/C-B') {
      if (delayedB) await delayedB
      return fulfillJson(route, analysis('C-B'))
    }
    if (url.pathname === '/api/v1/assistant/query') {
      const requestPayload = route.request().postDataJSON() as { context?: Record<string, unknown> }
      if (requestPayload.context) assistantContexts?.push(requestPayload.context)
      return fulfillJson(route, {
        contract_version: 'nocpro-assistant-v1', status: 'AVAILABLE',
        message: 'ASSISTANT_CONTEXT_RESPONSE', fact_refs: ['analysis:C-A'], actions: [],
        model: 'DETERMINISTIC_EVIDENCE', provider_status: 'OK',
      })
    }
    if (url.pathname === '/api/v1/chains/C-A/audit-visualization') return fulfillJson(route, {
      snapshot_id: 'S-BROWSER', snapshot_version: 'v1', chain_id: 'C-A',
      audit_artifact_id: 'audit-browser-1', audit_artifact_fingerprint: 'fingerprint-browser-1',
      visualization: {
        status: 'AVAILABLE', reason: null, projection_version: 'audit-visualization-v1',
        selection_strategy: 'BEST_CUT_BALANCED_WEIGHTED_DEGREE_V1', max_nodes: 80, max_edges: 160,
        total_node_count: 3, shown_node_count: 3, hidden_node_count: 0,
        total_edge_count: 2, shown_edge_count: 2, hidden_edge_count: 0, truncated: false,
        nodes: [
          { alarm_id: 'A-1', weighted_degree: 1.2, cut_side: 'A', structural_role: 'NON_CONNECTOR' },
          { alarm_id: 'A-2', weighted_degree: 1.8, cut_side: 'A', structural_role: 'CONNECTOR' },
          { alarm_id: 'A-3', weighted_degree: 0.7, cut_side: 'B', structural_role: 'NON_CONNECTOR' },
        ],
        edges: [
          { source_alarm_id: 'A-1', target_alarm_id: 'A-2', weight: 0.8, supporting_groups: ['entity'], crosses_best_cut: false },
          { source_alarm_id: 'A-2', target_alarm_id: 'A-3', weight: 0.7, supporting_groups: ['temporal'], crosses_best_cut: true },
        ],
      },
    })
    if (url.pathname === '/api/v1/chains/C-A/evolution') return fulfillJson(route, {
      status: 'UNAVAILABLE', reason: 'SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE', source_kind: null,
      sequence_status: 'UNAVAILABLE', production_validation: 'NOT_ESTABLISHED', lineage_component_id: null,
      branch_id: null, snapshot_id: 'S-BROWSER', snapshot_version: 'v1', chain_id: 'C-A', nodes: [], edges: [],
    })
    return fulfillJson(route, { detail: 'NOT_AVAILABLE_IN_BROWSER_FIXTURE' }, 404)
  })
}

test('overview uses observed values and remains within a mobile viewport', async ({ page }) => {
  await installApi(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByRole('main').getByText('S-BROWSER@v1')).toBeVisible()
  await expect(page.getByText('Largest observed chains')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Observed A', exact: true })).toBeVisible()
  await expect(page.getByText('8,714')).toHaveCount(0)
  await expect(page.getByText('37 Structural Findings')).toHaveCount(0)
  const dimensions = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client)
})

test('switching chains never renders the previous analysis under the new chain', async ({ page }) => {
  let releaseB!: () => void
  const delayedB = new Promise<void>(resolve => { releaseB = resolve })
  await installApi(page, delayedB)
  await page.goto('/')
  await page.getByRole('button', { name: 'Chains Explorer' }).click()
  await page.getByText('C-A', { exact: true }).click()
  await expect(page.getByText('Observed alarm one')).toBeVisible()

  await page.getByRole('button', { name: 'arrow_back Chains', exact: true }).click()
  await page.getByText('C-B', { exact: true }).click()
  await expect(page.getByText('Loading analysis for C-B…')).toBeVisible()
  await expect(page.getByText('Observed alarm one')).toHaveCount(0)
  releaseB()
  await expect(page.getByText('Observed singleton')).toBeVisible()
})

test('missing lineage and topology are explicit unavailable states', async ({ page }) => {
  await installApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Chains Explorer' }).click()
  await page.getByText('C-A', { exact: true }).click()
  await expect(page.getByText('Observed alarm one')).toBeVisible()

  await page.getByRole('button', { name: 'Evolution' }).click()
  await expect(page.getByRole('heading', { name: 'Sequential snapshots are not available.' })).toBeVisible()
  await expect(page.getByText('Sequential Snapshots Not Available')).toBeVisible()

  await page.getByRole('button', { name: 'Topology' }).click()
  await expect(page.getByRole('heading', { name: 'Topology unavailable' })).toBeVisible()
  await expect(page.getByText('TOPOLOGY_FIXTURE_UNAVAILABLE')).toBeVisible()
})

test('Structure reads and renders the persisted bounded Audit graph without submitting work', async ({ page }) => {
  const mutations: string[] = []
  page.on('request', request => {
    if (request.method() !== 'GET') mutations.push(`${request.method()} ${request.url()}`)
  })
  await installApi(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Chains Explorer' }).click()
  await page.getByText('C-A', { exact: true }).click()
  await page.getByRole('button', { name: 'Audit & Structure' }).click()

  const graph = page.getByRole('img', { name: 'Audit graph with 3 nodes and 2 edges' })
  await expect(graph).toBeVisible()
  await expect(page.getByText('3 / 3 nodes')).toBeVisible()
  await expect(graph.locator('circle')).toHaveCount(3)
  await expect(graph.locator('line')).toHaveCount(2)
  expect(mutations).toEqual([])
  const dimensions = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client)
})

test('Assistant history is discarded when the selected chain context changes', async ({ page }) => {
  await installApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Chains Explorer' }).click()
  await page.getByText('C-A', { exact: true }).click()
  await expect(page.getByText('Observed alarm one')).toBeVisible()

  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  const query = page.getByLabel('Hỏi về snapshot hiện tại')
  await query.fill('Conductance là gì?')
  await page.getByRole('button', { name: 'Hỏi' }).click()
  await expect(page.getByText('ASSISTANT_CONTEXT_RESPONSE')).toBeVisible()

  await page.getByRole('button', { name: 'arrow_back Chains', exact: true }).click()
  await page.getByText('C-B', { exact: true }).click()
  await expect(page.getByText('Observed singleton')).toBeVisible()
  await expect(page.getByText('ASSISTANT_CONTEXT_RESPONSE')).toHaveCount(0)
})

test('Assistant receives Pair WHY context and discards history when the pair changes', async ({ page }) => {
  const assistantContexts: Array<Record<string, unknown>> = []
  await installApi(page, undefined, assistantContexts)
  await page.goto('/')
  await page.getByRole('button', { name: 'Chains Explorer' }).click()
  await page.getByText('C-A', { exact: true }).click()
  await page.getByRole('button', { name: 'Why' }).click()
  await page.getByText('Scope:', { exact: true }).click()
  await page.getByText('Pair', { exact: true }).last().click()
  await page.getByLabel('Pair endpoint A').selectOption('A-1')
  await page.getByLabel('Pair endpoint B').selectOption('A-2')

  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  const query = page.getByLabel('Hỏi về snapshot hiện tại')
  await query.fill('Open Pair WHY')
  await page.getByRole('button', { name: 'Hỏi' }).click()
  await expect(page.getByText('ASSISTANT_CONTEXT_RESPONSE')).toBeVisible()
  expect(assistantContexts.at(-1)).toMatchObject({
    chain_id: 'C-A', pair_alarm_id_a: 'A-1', pair_alarm_id_b: 'A-2',
  })

  await page.getByLabel('Pair endpoint B').selectOption('A-3')
  await expect(page.getByText('ASSISTANT_CONTEXT_RESPONSE')).toHaveCount(0)
  await page.getByLabel('Hỏi về snapshot hiện tại').fill('Open Pair WHY')
  await page.getByRole('button', { name: 'Hỏi' }).click()
  await expect(page.getByText('ASSISTANT_CONTEXT_RESPONSE')).toBeVisible()
  expect(assistantContexts.at(-1)).toMatchObject({
    chain_id: 'C-A', pair_alarm_id_a: 'A-1', pair_alarm_id_b: 'A-3',
  })
})

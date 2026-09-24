import { expect, test, type Page, type Route } from '@playwright/test'

const epoch = 'ad2c5f7a-70aa-4ff6-91d8-8e5037247e76'

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

async function openEvolution(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'All Chains', exact: true }).click()
  await page.getByText('C1', { exact: true }).click()
  await page.getByRole('button', { name: 'Timeline & Evolution' }).click()
  await expect(page.getByRole('heading', { name: /Alarm Arrival Timeline/ })).toBeVisible()
  await page.getByRole('button', { name: 'Persisted Evolution' }).click()
  await expect(page.getByRole('button', { name: 'Persisted Evolution' })).toHaveAttribute('aria-pressed', 'true')
}

test('normal Timeline route opens persisted Evolution and loads its API', async ({ page }) => {
  let evolutionReads = 0
  await installFixture(page, () => { evolutionReads += 1 })
  await openEvolution(page)

  await expect(page.getByLabel('Persisted chain evolution')).toContainText('Synthetic test sequence')
  expect(evolutionReads).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Intra-chain Timeline' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Chronological Alarm Cascade' })).toBeVisible()
})

test('new snapshot event refreshes selected chain Evolution without refreshing its snapshot-scoped resources', async ({ page }) => {
  let releaseEvent!: () => void
  const allowEvent = new Promise<void>(resolve => { releaseEvent = resolve })
  let evolutionReads = 0
  let chainListReads = 0
  let detailReads = 0
  await installFixture(page, () => { evolutionReads += 1 }, allowEvent, () => { chainListReads += 1 }, () => { detailReads += 1 })
  await openEvolution(page)
  const panel = page.getByLabel('Persisted chain evolution')
  await expect(panel).toContainText(`Receipt ${evolutionReads}`)
  const evolutionBefore = evolutionReads
  const listBefore = chainListReads
  const detailBefore = detailReads

  releaseEvent()
  await expect.poll(() => evolutionReads).toBeGreaterThan(evolutionBefore)
  await expect(panel).toContainText(`Receipt ${evolutionReads}`)
  expect(chainListReads).toBe(listBefore)
  expect(detailReads).toBe(detailBefore)
  await expect(page.getByText('S1@v1', { exact: true }).first()).toBeVisible()
})

async function installFixture(
  page: Page,
  onEvolutionRead: () => void,
  allowEvent?: Promise<void>,
  onChainListRead?: () => void,
  onDetailRead?: () => void,
) {
  let reads = 0
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/events') {
      if (!allowEvent) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 1000\n\n' })
      await allowEvent
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: [
        `id: ${epoch}:1`,
        'event: invalidate',
        `data: ${JSON.stringify({
          schema_version: 'change-event-v1', event_type: 'snapshot.changed',
          snapshot_id: 'S2', snapshot_version: 'v1', chain_id: null,
          topology_version: null, identity_digest: null,
          invalidates: ['catalog', 'chain-list', 'quality-summary', 'evolution'],
        })}`,
        '', '',
      ].join('\n') })
    }
    if (path === '/api/v1/health') return json(route, { status: 'ok' })
    if (path === '/api/v1/config') return json(route, { config_version: 'cfg-1' })
    if (path === '/api/v1/snapshots') return json(route, { active_snapshot_id: 'S1', active_snapshot_version: 'v1', snapshots: [] })
    if (path === '/api/v1/snapshots/quality-summaries') return json(route, { summaries: [] })
    if (path === '/api/v1/chains') {
      onChainListRead?.()
      return json(route, { snapshot_id: 'S1', snapshot_version: 'v1', topology_version: null,
        chains: [{ chain_id: 'C1', member_count: 1, is_singleton: true, title: 'Selected chain', start_time: null, end_time: null, duration_seconds: null }] })
    }
    if (path === '/api/v1/chains/C1') {
      onDetailRead?.()
      return json(route, { chain_id: 'C1', title: 'Selected chain', member_count: 1, singleton: true,
        statistics_mode: 'EXACT', audit_graph_mode: 'DEFERRED', pair_materialization: 'LAZY', config_version: 'cfg-1',
        graybox: { mode: 'STRICT', merge_strategy: null, rules: 0, characteristics: 0, pair_facts: 0, unavailable_capabilities: [] },
        descriptors: [], members: [], role_counts: {}, phase_durations: {} })
    }
    if (path === '/api/v1/chains/C1/evolution') {
      onEvolutionRead()
      reads += 1
      return json(route, { status: 'AVAILABLE', reason: null, source_kind: 'SYNTHETIC_TEST', sequence_status: 'VERIFIED',
        production_validation: 'NOT_ESTABLISHED', lineage_component_id: `Receipt ${reads}`, branch_id: 'branch-1',
        snapshot_id: 'S1', snapshot_version: 'v1', chain_id: 'C1', nodes: [], edges: [] })
    }
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"fixture unavailable"}' })
  })
}

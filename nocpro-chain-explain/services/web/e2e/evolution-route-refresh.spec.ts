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
  let changesReads = 0
  let chainListReads = 0
  let detailReads = 0
  await installFixture(page, () => { evolutionReads += 1 }, allowEvent, () => { chainListReads += 1 }, () => { detailReads += 1 }, {
    onChangesRead: parentChainId => { if (!parentChainId) changesReads += 1 },
  })
  await openEvolution(page)
  const panel = page.getByLabel('Persisted chain evolution')
  await expect(panel).toContainText(`Receipt ${evolutionReads}`)
  await expect.poll(() => changesReads).toBeGreaterThan(0)
  const evolutionBefore = evolutionReads
  const changesBefore = changesReads
  const listBefore = chainListReads
  const detailBefore = detailReads

  releaseEvent()
  await expect.poll(() => evolutionReads).toBeGreaterThan(evolutionBefore)
  await expect.poll(() => changesReads).toBeGreaterThan(changesBefore)
  await expect(panel).toContainText(`Receipt ${evolutionReads}`)
  expect(chainListReads).toBe(listBefore)
  expect(detailReads).toBe(detailBefore)
  await expect(page.getByText('S1@v1', { exact: true }).first()).toBeVisible()
})

test('Evolution changes lets keyboard users choose a lineage edge and reports missing evidence clearly', async ({ page }) => {
  const selectedTransitions: string[] = []
  const consoleErrors: string[] = []
  const failedResponses: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('response', response => {
    if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`)
  })
  await installFixture(page, () => undefined, undefined, undefined, undefined, {
    onChangesRead: (parentChainId, parentReceiptId) => {
      if (parentChainId) selectedTransitions.push(`${parentChainId}:${parentReceiptId ?? 'auto'}`)
    },
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await openEvolution(page)

  const panel = page.getByLabel('Dữ kiện chuyển tiếp đã chọn')
  await expect(panel).toContainText('Cần chọn một chuyển tiếp trước để xem chi tiết.')
  const choices = panel.getByRole('radio')
  await expect(choices).toHaveCount(2)

  await choices.first().focus()
  await page.keyboard.press('Space')
  await expect(choices.first()).toBeChecked()
  await expect(panel).toContainText('1 alarm được thêm vào chain.')
  await expect(panel).toContainText('1 alarm rời chain; điều này không đồng nghĩa alarm đã clear.')
  await expect(panel).toContainText('Không thể so sánh trực tiếp điểm vì dữ liệu hoặc cấu hình đánh giá không tương thích.')

  await page.keyboard.press('ArrowDown')
  await expect(choices.nth(1)).toBeFocused()
  await expect(choices.nth(1)).toBeChecked()
  await expect(panel.getByLabel('Chuyển tiếp đã chọn')).toContainText('C1 · S0@v1')
  const parentReceiptPicker = panel.getByLabel('Biên nhận trước')
  await expect(parentReceiptPicker).toBeVisible()
  await parentReceiptPicker.selectOption('r-parent-new')
  await expect(panel).toContainText('Biên nhận trước: r-parent-new')
  expect(selectedTransitions).toEqual(['C0:auto', 'C1:auto', 'C1:r-parent-new'])

  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }))
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport)
  expect(consoleErrors, `Failed HTTP responses: ${failedResponses.join(' | ')}`).toEqual([])
})

test('a single snapshot shows an explicit missing-history explanation', async ({ page }) => {
  await installFixture(page, () => undefined, undefined, undefined, undefined, { evolutionAvailable: false })
  await openEvolution(page)

  const changes = page.getByLabel('Dữ kiện chuyển tiếp đã chọn')
  await expect(changes).toContainText('Chưa có snapshot trước để đối chiếu.')
  await expect(changes).not.toContainText('UNAVAILABLE')
  await expect(changes).not.toContainText('SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE')
})

test('a disabled Evolution changes feature is presented as unavailable, not as a request failure', async ({ page }) => {
  await installFixture(page, () => undefined, undefined, undefined, undefined, { changesEnabled: false })
  await openEvolution(page)

  await expect(page.getByLabel('Dữ kiện chuyển tiếp đã chọn')).toContainText(
    'Chức năng đối chiếu thay đổi chưa được bật trên máy chủ.',
  )
})

async function installFixture(
  page: Page,
  onEvolutionRead: () => void,
  allowEvent?: Promise<void>,
  onChainListRead?: () => void,
  onDetailRead?: () => void,
  options: {
    onChangesRead?: (parentChainId: string | null, parentReceiptId: string | null) => void
    evolutionAvailable?: boolean
    changesEnabled?: boolean
  } = {},
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
    if (path === '/api/v1/chains/C1/overview-cards') return json(route, {
      snapshot_id: 'S1', snapshot_version: 'v1', chain_id: 'C1', status: 'NOT_APPLICABLE',
      projection_version: null, reason: 'SINGLETON_CHAIN', topology_version: null,
      representative_member: null, topology: null, quality_assessment: null, recommendations: null,
    })
    if (path === '/api/v1/chains/C1/evolution') {
      onEvolutionRead()
      reads += 1
      if (options.evolutionAvailable === false) return json(route, {
        status: 'UNAVAILABLE', reason: 'SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE', source_kind: null,
        sequence_status: 'UNAVAILABLE', production_validation: 'NOT_ESTABLISHED', lineage_component_id: null,
        branch_id: null, snapshot_id: 'S1', snapshot_version: 'v1', chain_id: 'C1', nodes: [], edges: [],
      })
      return json(route, { status: 'AVAILABLE', reason: null, source_kind: 'SYNTHETIC_TEST', sequence_status: 'VERIFIED',
        production_validation: 'NOT_ESTABLISHED', lineage_component_id: `Receipt ${reads}`, branch_id: 'branch-1',
        snapshot_id: 'S1', snapshot_version: 'v1', chain_id: 'C1', nodes: [], edges: [] })
    }
    if (path === '/api/v1/chains/C1/evolution/changes') {
      if (options.changesEnabled === false) {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'EVOLUTION_CHANGES_DISABLED' }) })
      }
      expect(route.request().headers()['x-nocpro-snapshot-id']).toBe('S1')
      expect(route.request().headers()['x-nocpro-snapshot-version']).toBe('v1')
      const params = new URL(route.request().url()).searchParams
      const parentChainId = params.get('parent_chain_id')
      const parentReceiptId = params.get('parent_receipt_id')
      options.onChangesRead?.(parentChainId, parentReceiptId)
      if (!parentChainId) return json(route, {
        status: options.evolutionAvailable === false ? 'UNAVAILABLE' : 'PARTIAL',
        reason_codes: options.evolutionAvailable === false ? ['SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE'] : ['PARENT_SELECTION_REQUIRED'],
        parent: null,
        child: { snapshot_id: 'S1', snapshot_version: 'v1', chain_id: 'C1' }, event_type: null,
        parent_source_kind: null, child_source_kind: null,
        predecessor_choices: [
          { parent: { snapshot_id: 'S0', snapshot_version: 'v1', chain_id: 'C0' }, event_type: 'MERGE', parent_source_kind: 'SYNTHETIC', child_source_kind: 'REAL_EXPORT_REPLAY' },
          { parent: { snapshot_id: 'S0', snapshot_version: 'v1', chain_id: 'C1' }, event_type: 'CONTINUE', parent_source_kind: 'SYNTHETIC', child_source_kind: 'REAL_EXPORT_REPLAY' },
        ], predecessor_choices_truncated: false,
        parent_receipt_choices: [], child_receipt_choices: [],
        parent_receipt_choices_truncated: false, child_receipt_choices_truncated: false,
        membership: null, context_changes: [],
        quality: { comparable: false, reason_codes: ['QUALITY_RECEIPT_UNAVAILABLE'], before_score: null, after_score: null, before_stars: null, after_stars: null, delta: null, before_receipt_id: null, after_receipt_id: null },
        explanations: [],
      })
      return json(route, {
        status: 'PARTIAL', reason_codes: ['QUALITY_RECEIPT_UNAVAILABLE'],
        parent: { snapshot_id: 'S0', snapshot_version: 'v1', chain_id: parentChainId },
        child: { snapshot_id: 'S1', snapshot_version: 'v1', chain_id: 'C1' },
        event_type: parentChainId === 'C0' ? 'MERGE' : 'CONTINUE',
        parent_source_kind: 'SYNTHETIC', child_source_kind: 'REAL_EXPORT_REPLAY',
        predecessor_choices: [], predecessor_choices_truncated: false,
        parent_receipt_choices: parentReceiptId ? [] : [
          { receipt_id: 'r-parent-new', artifact_revision: 'rev-new', created_at: '2026-01-02T00:00:00Z' },
          { receipt_id: 'r-parent-old', artifact_revision: 'rev-old', created_at: '2026-01-01T00:00:00Z' },
        ], child_receipt_choices: [],
        parent_receipt_choices_truncated: false, child_receipt_choices_truncated: false,
        membership: { added_count: 1, removed_count: 1, retained_count: 2, added_alarm_ids: ['A-2'], removed_alarm_ids: ['A-1'], truncated: false },
        context_changes: [{ field: 'source_kind', before: 'SYNTHETIC', after: 'REAL_EXPORT_REPLAY' }],
        quality: { comparable: false, reason_codes: ['QUALITY_RECEIPT_UNAVAILABLE'], before_score: parentReceiptId ? 0.67 : null, after_score: null, before_stars: parentReceiptId ? 3 : null, after_stars: null, delta: null, before_receipt_id: parentReceiptId, after_receipt_id: null },
        explanations: [
          { code: 'MEMBERS_ENTERED_CHAIN', text: 'server-generated text', evidence_ids: ['A-2'] },
          { code: 'MEMBERS_LEFT_CHAIN', text: 'server-generated text', evidence_ids: ['A-1'] },
          { code: 'QUALITY_NOT_COMPARABLE', text: 'server-generated text', evidence_ids: [] },
        ],
      })
    }
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"fixture unavailable"}' })
  })
}

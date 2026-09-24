import { expect, test, type Route } from '@playwright/test'

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

const topologyVersion = 'topology-1'
const epoch = 'ad2c5f7a-70aa-4ff6-91d8-8e5037247e76'

const catalog = {
  active_snapshot_id: 'S1', active_snapshot_version: 'v1',
  snapshots: [
    { snapshot_id: 'S1', snapshot_version: 'v1', name: 'Active snapshot', profile: 'IP_NETWORK', alarm_count: 4, chain_count: 1, description: 'Current', badge: 'Current', available: true },
    { snapshot_id: 'S2', snapshot_version: 'v1', name: 'Background snapshot', profile: 'IP_NETWORK', alarm_count: 3, chain_count: 1, description: 'Background', badge: 'Background', available: true },
  ],
}

function qualitySummaries(backgroundStatus: 'REVIEW' | 'HEALTHY') {
  const backgroundHealthy = backgroundStatus === 'HEALTHY'
  return { summaries: [
    {
      snapshot_id: 'S1', snapshot_version: 'v1', total_chain_count: 1, eligible_chain_count: 1,
      sturdy_count: 1, review_count: 0, evaluating_count: 0, unevaluated_count: 0, unavailable_count: 0,
      star_counts: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 0 }, attention_chains: [],
      chain_assessments: [{ chain_id: 'C1', member_count: 4, title: 'active-chain', duration_seconds: 30, status: 'EVALUATED', stars: 4, label: 'Vững', reason: null }],
    },
    {
      snapshot_id: 'S2', snapshot_version: 'v1', total_chain_count: 1, eligible_chain_count: 1,
      sturdy_count: backgroundHealthy ? 1 : 0, review_count: backgroundHealthy ? 0 : 1,
      evaluating_count: 0, unevaluated_count: 0, unavailable_count: 0,
      star_counts: backgroundHealthy
        ? { '1': 0, '2': 0, '3': 0, '4': 1, '5': 0 }
        : { '1': 0, '2': 1, '3': 0, '4': 0, '5': 0 },
      attention_chains: [],
      chain_assessments: [{
        chain_id: 'C2', member_count: 3, title: 'background-chain', duration_seconds: 25,
        status: backgroundHealthy ? 'EVALUATED' : 'NEEDS_REVIEW', stars: backgroundHealthy ? 4 : 2,
        label: backgroundHealthy ? 'Vững' : 'Cần xem', reason: null,
      }],
    },
  ] }
}

const chains = {
  snapshot_id: 'S1', snapshot_version: 'v1', topology_version: topologyVersion,
  chains: [{ chain_id: 'C1', member_count: 4, is_singleton: false, title: 'active-chain', start_time: null, end_time: null, duration_seconds: 30 }],
}

test('a background snapshot quality change updates the portfolio through SSE and REST', async ({ page }) => {
  let backgroundStatus: 'REVIEW' | 'HEALTHY' = 'REVIEW'
  let qualitySummaryReads = 0
  let releaseInvalidation: () => void = () => {}
  const allowInvalidation = new Promise<void>(resolve => { releaseInvalidation = resolve })

  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/events') {
      await allowInvalidation
      const eventBody = [
        'retry: 1000',
        '',
        `id: ${epoch}:1`,
        'event: invalidate',
        `data: ${JSON.stringify({
          schema_version: 'change-event-v1',
          event_type: 'quality.changed',
          snapshot_id: 'S2',
          snapshot_version: 'v1',
          chain_id: 'C2',
          topology_version: topologyVersion,
          identity_digest: null,
          invalidates: ['quality-summary', 'chain-list', 'chain-detail', 'evolution'],
        })}`,
        '',
        // Replaying the same cursor must not cause an extra REST read or count.
        `id: ${epoch}:1`,
        'event: invalidate',
        `data: ${JSON.stringify({
          schema_version: 'change-event-v1',
          event_type: 'quality.changed',
          snapshot_id: 'S2',
          snapshot_version: 'v1',
          chain_id: 'C2',
          topology_version: topologyVersion,
          identity_digest: null,
          invalidates: ['quality-summary', 'chain-list', 'chain-detail', 'evolution'],
        })}`,
        '',
      ].join('\n')
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: eventBody })
    }
    if (path === '/api/v1/health') return json(route, { status: 'ok' })
    if (path === '/api/v1/config') return json(route, { config_version: 'cfg-1' })
    if (path === '/api/v1/snapshots') return json(route, catalog)
    if (path === '/api/v1/snapshots/quality-summaries') {
      qualitySummaryReads += 1
      await json(route, qualitySummaries(backgroundStatus))
      return
    }
    if (path === '/api/v1/chains') return json(route, chains)
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"fixture unavailable"}' })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Snapshots', exact: true }).click()
  const summary = page.getByRole('region', { name: 'Snapshot status summary' })
  await expect(summary.getByText('● Ổn: 1 (50.0%)', { exact: true })).toBeVisible()
  await expect(summary.getByText('● Cần xem: 1 (50.0%)', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /IP Network .*S1@v1/ })).toBeVisible()

  const summaryReadsBeforeInvalidation = qualitySummaryReads
  backgroundStatus = 'HEALTHY'
  releaseInvalidation()

  await expect.poll(() => qualitySummaryReads, { timeout: 8000 }).toBe(summaryReadsBeforeInvalidation + 1)
  await expect(summary.getByText('● Ổn: 2 (100.0%)', { exact: true })).toBeVisible()
  await expect(summary.getByText('● Cần xem: 0 (0.0%)', { exact: true })).toBeVisible()
})

test('degraded fallback and native SSE reset coalesce a stale in-flight summary into one fresh GET', async ({ page }) => {
  await page.addInitScript(() => {
    const NativeEventSource = window.EventSource
    const stats = { created: 0, closed: 0, opens: 0, peakActive: 0 }
    class ObservedEventSource extends NativeEventSource {
      constructor(url: string | URL, options?: EventSourceInit) {
        super(url, options)
        stats.created += 1
        stats.peakActive = Math.max(stats.peakActive, stats.created - stats.closed)
        this.addEventListener('open', () => { stats.opens += 1 })
      }

      close() {
        if (this.readyState !== EventSource.CLOSED) stats.closed += 1
        super.close()
      }
    }
    window.EventSource = ObservedEventSource
    ;(window as typeof window & { __liveSourceStats: typeof stats }).__liveSourceStats = stats
  })

  let eventRequests = 0
  let catalogReads = 0
  let qualityReads = 0
  let holdNextQualityRead = false
  let heldFallbackRead = false
  let releaseReconnect: () => void = () => {}
  const allowReconnect = new Promise<void>(resolve => { releaseReconnect = resolve })
  let releaseLaterReconnect: () => void = () => {}
  const allowLaterReconnect = new Promise<void>(resolve => { releaseLaterReconnect = resolve })
  let releaseFallback: () => void = () => {}
  const allowFallback = new Promise<void>(resolve => { releaseFallback = resolve })

  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/events') {
      eventRequests += 1
      if (eventRequests === 1) {
        // A finite stream opens once, then closes so native EventSource retries.
        return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 1000\n\n' })
      }
      if (eventRequests > 2) {
        await allowLaterReconnect
        return route.fulfill({ status: 503, body: '' })
      }
      await allowReconnect
      const reset = [
        'retry: 1000',
        '',
        `id: ${epoch}:2`,
        'event: reset',
        `data: ${JSON.stringify({ reason: 'CURSOR_EXPIRED', epoch, revision: 2 })}`,
        '',
        '',
      ].join('\n')
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: reset })
    }
    if (path === '/api/v1/health') return json(route, { status: 'ok' })
    if (path === '/api/v1/config') return json(route, { config_version: 'cfg-1' })
    if (path === '/api/v1/snapshots') {
      catalogReads += 1
      return json(route, catalog)
    }
    if (path === '/api/v1/snapshots/quality-summaries') {
      qualityReads += 1
      if (holdNextQualityRead) {
        holdNextQualityRead = false
        heldFallbackRead = true
        const stale = qualitySummaries('REVIEW')
        await allowFallback
        return json(route, stale)
      }
      return json(route, qualitySummaries(heldFallbackRead ? 'HEALTHY' : 'REVIEW'))
    }
    if (path === '/api/v1/chains') return json(route, chains)
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"fixture unavailable"}' })
  })

  try {
    await page.goto('/')
    await page.getByRole('button', { name: 'Snapshots', exact: true }).click()
    const summary = page.getByRole('region', { name: 'Snapshot status summary' })
    await expect(summary.getByText('● Ổn: 1 (50.0%)', { exact: true })).toBeVisible()
    await expect(summary.getByText('● Cần xem: 1 (50.0%)', { exact: true })).toBeVisible()
    await expect(page.getByText('Kết nối gián đoạn · đang đồng bộ định kỳ', { exact: true })).toBeVisible()
    await expect.poll(() => eventRequests).toBe(2)
    await expect.poll(() => page.evaluate(() => (
      (window as typeof window & { __liveSourceStats: { opens: number } }).__liveSourceStats.opens
    ))).toBe(1)

    const readsBeforeFallback = qualityReads
    const catalogBeforeFallback = catalogReads
    holdNextQualityRead = true
    await expect.poll(() => heldFallbackRead, { timeout: 12_000 }).toBe(true)
    await expect.poll(() => catalogReads).toBe(catalogBeforeFallback + 1)
    expect(qualityReads).toBe(readsBeforeFallback + 1)
    await expect(summary.getByText('● Cần xem: 1 (50.0%)', { exact: true })).toBeVisible()

    releaseReconnect()
    await expect.poll(() => page.evaluate(() => (
      (window as typeof window & { __liveSourceStats: { created: number; closed: number; opens: number; peakActive: number } }).__liveSourceStats
    ))).toMatchObject({ created: 2, closed: 1, opens: 2, peakActive: 1 })
    // The reset must be parsed and dispatched while the previous summary GET is held.
    await expect.poll(() => catalogReads, { timeout: 5000 }).toBe(catalogBeforeFallback + 2)
    expect(qualityReads).toBe(readsBeforeFallback + 1)

    releaseFallback()
    await expect.poll(() => qualityReads).toBe(readsBeforeFallback + 2)
    await expect(summary.getByText('● Ổn: 2 (100.0%)', { exact: true })).toBeVisible()
    await expect(summary.getByText('● Cần xem: 0 (0.0%)', { exact: true })).toBeVisible()
    expect(qualityReads).toBe(readsBeforeFallback + 2)
    expect(catalogReads).toBe(catalogBeforeFallback + 2)
    expect(eventRequests).toBeLessThanOrEqual(3)
  } finally {
    releaseReconnect()
    releaseLaterReconnect()
    releaseFallback()
  }
})

test('useLiveUpdates keeps one StrictMode EventSource and clears owned timers on unmount', async ({ page }) => {
  await page.goto('/e2e/fixtures/use-live-updates-lifecycle.html')
  await expect(page.locator('#mounted')).toHaveText('mounted')

  await expect.poll(() => page.evaluate(() => window.lifecycleHarness.snapshot())).toMatchObject({
    createdSources: 2,
    openSources: 1,
    closedSources: 1,
    activeIntervals: 1,
    activeTimeouts: 1,
  })

  await page.evaluate(() => window.lifecycleHarness.unmount())

  await expect.poll(() => page.evaluate(() => window.lifecycleHarness.snapshot())).toMatchObject({
    openSources: 0,
    closedSources: 2,
    activeIntervals: 0,
    activeTimeouts: 0,
  })
})

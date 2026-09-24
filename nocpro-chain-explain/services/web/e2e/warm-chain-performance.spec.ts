import { expect, test } from '@playwright/test'

type ActiveChains = {
  snapshot_id: string
  snapshot_version: string
  chains: Array<{ chain_id: string; member_count: number }>
}

type QualitySummary = {
  snapshot_id: string
  snapshot_version: string
  chain_assessments: Array<{ chain_id: string; status: string; stars: number | null }>
}

test('reopening a completed chain shows persisted Overview without submitting work', async ({ page }) => {
  const inventoryResponse = await page.request.get('/api/v1/chains')
  expect(inventoryResponse.ok()).toBeTruthy()
  const inventory = await inventoryResponse.json() as ActiveChains
  const qualityResponse = await page.request.get('/api/v1/snapshots/quality-summaries')
  expect(qualityResponse.ok()).toBeTruthy()
  const qualityPayload = await qualityResponse.json() as { summaries: QualitySummary[] }
  const summary = qualityPayload.summaries.find(item =>
    item.snapshot_id === inventory.snapshot_id
    && item.snapshot_version === inventory.snapshot_version,
  )
  const completed = new Set(
    (summary?.chain_assessments ?? [])
      .filter(item => item.status === 'EVALUATED' && item.stars !== null)
      .map(item => item.chain_id),
  )
  const chain = inventory.chains.find(item => item.member_count > 1 && completed.has(item.chain_id))
  test.skip(!chain, 'active snapshot has no completed multi-alarm chain projection yet')

  const submissions: string[] = []
  const samples: number[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/api/v1/')) {
      submissions.push(request.url().split('?')[0] ?? 'unknown')
    }
  })

  for (let repetition = 0; repetition < 30; repetition += 1) {
    if (repetition === 0) await page.goto('/')
    else await page.reload()
    await page.getByRole('button', { name: 'All Chains', exact: true }).click()
    await expect(page.getByText(chain!.chain_id, { exact: true })).toBeVisible()

    await page.evaluate(() => {
      performance.mark('warm-chain-open-start')
    })
    const overviewResponse = page.waitForResponse(response =>
      response.request().method() === 'GET'
      && response.url().includes(`/chains/${encodeURIComponent(chain!.chain_id)}/overview-cards`),
    )
    await page.getByText(chain!.chain_id, { exact: true }).click()
    const overview = await overviewResponse
    expect(overview.ok()).toBeTruthy()
    const projection = await overview.json() as {
      chain_id: string
      snapshot_id: string
      snapshot_version: string
      status: string
    }
    expect(projection).toMatchObject({
      chain_id: chain!.chain_id,
      snapshot_id: inventory.snapshot_id,
      snapshot_version: inventory.snapshot_version,
      status: 'READY',
    })
    await expect(page.getByText('Tổng quan chain', { exact: true })).toBeVisible()
    samples.push(await page.evaluate(() => {
      performance.mark('warm-chain-open-end')
      return performance.measure(
        'warm-chain-open',
        'warm-chain-open-start',
        'warm-chain-open-end',
      ).duration
    }))
  }

  const sorted = [...samples].sort((left, right) => left - right)
  const p50 = sorted[Math.ceil(0.5 * sorted.length) - 1]
  const p95 = sorted[Math.ceil(0.95 * sorted.length) - 1]
  await test.info().attach('warm-chain-performance.json', {
    body: JSON.stringify({
      origin: 'ISOLATED_E2E_API',
      production_validation: 'NOT_ESTABLISHED',
      snapshot_id: inventory.snapshot_id,
      snapshot_version: inventory.snapshot_version,
      chain_id: chain!.chain_id,
      sample_count: samples.length,
      p50_ms: p50,
      p95_ms: p95,
      samples_ms: samples,
      post_requests: submissions,
    }, null, 2),
    contentType: 'application/json',
  })
  expect(samples).toHaveLength(30)
  expect(submissions).toEqual([])
  expect(p95).toBeLessThanOrEqual(1000)
})

import { expect, test } from '@playwright/test'

type ChainSummary = { chain_id: string; member_count: number }

async function selectPairContext(page: import('@playwright/test').Page) {
  const response = await page.request.get('/api/v1/chains')
  expect(response.ok()).toBeTruthy()
  const inventory = await response.json() as { chains: ChainSummary[] }
  const chain = inventory.chains.find((item) => item.member_count >= 2 && item.member_count <= 9)
  expect(chain, 'active snapshot needs a bounded pair chain').toBeDefined()

  await page.goto('/')
  await page.getByLabel('Select alarm chain').selectOption(chain!.chain_id)
  await page.getByRole('button', { name: 'Chain Tree' }).click()
  const compareControls = page.getByLabel('Hierarchical alarm chain tree').locator('.node-compare-btn')
  await compareControls.nth(0).click()
  await Promise.all([
    page.waitForResponse((item) => item.url().includes('/pairs/') && item.ok()),
    compareControls.nth(1).click(),
  ])
  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
}

test('NocPro Assistant is snapshot-bound, read-only, and navigates with typed actions', async ({ page }) => {
  const consoleErrors: string[] = []
  const mutationRequests: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('request', (request) => {
    const url = request.url()
    if (request.method() === 'POST' && (
      url.includes('/deep-dive') || url.includes('/review') || url.includes('/feedback')
    )) mutationRequests.push(`${request.method()} ${url}`)
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  await expect(page.getByRole('heading', { name: 'NocPro Assistant' })).toBeVisible()
  await expect(page.getByText('Assistant không thay đổi analysis')).toBeVisible()

  const query = page.getByLabel('Hỏi về snapshot hiện tại')
  await query.fill('Conductance là gì?')
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/assistant/query') && response.ok()),
    page.getByRole('button', { name: 'Hỏi' }).click(),
  ])
  await expect(page.getByText(/semantic-registry:conductance/i)).toBeVisible()
  await expect(
    page.locator('[aria-label^="AI-assisted narrative"], [aria-label^="Deterministic fallback"]').first(),
  ).toBeVisible()

  await query.fill('Open audit')
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/assistant/query') && response.ok()),
    page.getByRole('button', { name: 'Hỏi' }).click(),
  ])
  await page.getByRole('button', { name: 'Open Structural Audit' }).click()
  await expect(page.getByRole('button', { name: 'Structure' })).toHaveClass(/is-active/)

  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  await query.fill('Open review')
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/assistant/query') && response.ok()),
    page.getByRole('button', { name: 'Hỏi' }).click(),
  ])
  await page.getByRole('button', { name: 'Open Counterfactual Review' }).click()
  await expect(page.getByRole('button', { name: 'Review' })).toHaveClass(/is-active/)
  expect(mutationRequests, 'Assistant navigation must not start analysis or mutate Review/feedback').toEqual([])
  expect(consoleErrors, 'browser console must stay free of errors').toEqual([])
})

test('Assistant hides completed and delayed responses when pair context changes', async ({ page }) => {
  const consoleProblems: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') consoleProblems.push(message.text())
  })
  await selectPairContext(page)
  const query = page.getByLabel('Hỏi về snapshot hiện tại')

  await query.fill('Open Pair WHY')
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/assistant/query') && response.ok()),
    page.getByRole('button', { name: 'Hỏi' }).click(),
  ])
  await expect(page.locator('.assistant-result')).toBeVisible()
  await page.getByRole('button', { name: 'Close pair comparison' }).click()
  await expect(page.locator('.assistant-result')).toBeHidden()

  await selectPairContext(page)
  let releaseResponse!: () => void
  let requestStarted!: () => void
  let requestFinished!: () => void
  const responseGate = new Promise<void>((resolve) => { releaseResponse = resolve })
  const requestGate = new Promise<void>((resolve) => { requestStarted = resolve })
  const finishedGate = new Promise<void>((resolve) => { requestFinished = resolve })
  await page.route('**/api/v1/assistant/query', async (route) => {
    requestStarted()
    await responseGate
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'nocpro-assistant-v1',
        status: 'AVAILABLE',
        message: 'STALE_PAIR_RESPONSE_MUST_NOT_RENDER',
        actions: [],
        fact_refs: [],
      }),
    }).catch(() => undefined).finally(requestFinished)
  })
  await query.fill('Open Pair WHY')
  await page.getByRole('button', { name: 'Hỏi' }).click()
  await requestGate
  await page.getByRole('button', { name: 'Close pair comparison' }).click()
  releaseResponse()
  await finishedGate
  await page.waitForTimeout(100)
  await expect(page.getByText('STALE_PAIR_RESPONSE_MUST_NOT_RENDER')).toBeHidden()
  expect(consoleProblems, 'context change must not produce browser errors or warnings').toEqual([])
})

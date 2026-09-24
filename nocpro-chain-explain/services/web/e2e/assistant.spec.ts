import { expect, test } from '@playwright/test'

type ChainSummary = { chain_id: string; member_count: number }

async function openChain(page: import('@playwright/test').Page, chainId: string) {
  await page.getByRole('button', { name: 'All Chains', exact: true }).click()
  await page.getByText(chainId, { exact: true }).click()
}

async function selectPairContext(page: import('@playwright/test').Page) {
  const response = await page.request.get('/api/v1/chains')
  expect(response.ok()).toBeTruthy()
  const inventory = await response.json() as { chains: ChainSummary[] }
  const chain = inventory.chains.find((item) => item.member_count >= 3 && item.member_count <= 9)
  expect(chain, 'active snapshot needs a bounded pair chain').toBeDefined()

  await page.goto('/')
  await openChain(page, chain!.chain_id)
  await page.getByRole('button', { name: /WHY$/ }).click()
  await page.getByRole('button', { name: /Pair$/ }).click()
  const endpointA = page.getByLabel('Pair endpoint A')
  await expect(endpointA).toBeVisible()
  const members = await endpointA.locator('option').evaluateAll(options =>
    options.map(option => (option as HTMLOptionElement).value).filter(Boolean),
  )
  expect(members.length).toBeGreaterThanOrEqual(2)
  await page.getByLabel('Pair endpoint A').selectOption(members[0])
  await Promise.all([
    page.waitForResponse((item) => item.url().includes('/pairs/') && item.ok()),
    page.getByLabel('Pair endpoint B').selectOption(members[1]),
  ])
  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
}

async function changePairEndpoint(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Đóng chat' }).click()
  const endpointB = page.getByLabel('Pair endpoint B')
  const current = await endpointB.inputValue()
  const endpointA = await page.getByLabel('Pair endpoint A').inputValue()
  const replacement = await endpointB.locator('option').evaluateAll(
    (options, excluded) => options
      .map(option => (option as HTMLOptionElement).value)
      .find(value => Boolean(value) && !(excluded as string[]).includes(value)),
    [current, endpointA],
  )
  expect(replacement, 'pair-chain fixture needs a third distinct endpoint').toBeTruthy()
  await endpointB.selectOption(replacement!)
}

test('NocPro Assistant is snapshot-bound, read-only, and navigates with typed actions', async ({ page }) => {
  const inventoryResponse = await page.request.get('/api/v1/chains')
  expect(inventoryResponse.ok()).toBeTruthy()
  const inventory = await inventoryResponse.json() as { snapshot_id: string; snapshot_version: string; chains: ChainSummary[] }
  const targetChain = inventory.chains.find(item => item.member_count > 1) ?? inventory.chains[0]
  expect(targetChain, 'active snapshot needs at least one chain').toBeDefined()
  const consoleErrors: string[] = []
  const reviewReadResponses: string[] = []
  const missingReviewResponses: string[] = []
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
  page.on('response', (response) => {
    if (/\/api\/v1\/chains\/[^/]+\/review$/.test(new URL(response.url()).pathname)) {
      reviewReadResponses.push(response.url())
      if (response.status() === 404) missingReviewResponses.push(response.url())
    }
  })

  await page.goto('/')
  await expect(page.getByRole('main').getByText(
    `${inventory.snapshot_id}@${inventory.snapshot_version}`,
    { exact: true },
  )).toBeVisible()
  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  await expect(page.getByRole('heading', { name: 'NocPro Assistant' })).toBeVisible()
  await expect(page.getByText('Assistant không thay đổi analysis')).toBeVisible()

  const query = page.getByLabel('Hỏi về snapshot hiện tại')
  await query.fill('Conductance là gì?')
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/assistant/query') && response.ok()),
    page.getByRole('button', { name: 'Hỏi' }).click(),
  ])
  await expect(page.locator('.assistant-result')).toContainText(/Conductance/i)
  await expect(page.locator('.assistant-result .pill').nth(1)).toBeVisible()

  await page.getByRole('button', { name: 'Đóng chat' }).click()
  await openChain(page, targetChain.chain_id)
  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  const chainQuery = page.getByLabel('Hỏi về snapshot hiện tại')
  await chainQuery.fill('Open audit')
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/assistant/query') && response.ok()),
    page.getByRole('button', { name: 'Hỏi' }).click(),
  ])
  await page.getByRole('button', { name: 'Open Structural Audit' }).click()
  await expect(page.getByRole('button', { name: 'Audit & Structure' })).toHaveClass(/bg-secondary/)

  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  await query.fill('Open review')
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/assistant/query') && response.ok()),
    page.getByRole('button', { name: 'Hỏi' }).click(),
  ])
  await page.getByRole('button', { name: 'Open Counterfactual Review' }).click()
  await expect(page.getByRole('button', { name: 'Recommendations & Validation' })).toHaveClass(/bg-secondary/)
  await expect(page.getByText('Counterfactual đã chạy xong.', { exact: true })).toBeVisible()
  expect(mutationRequests, 'Assistant navigation must not start analysis or mutate Review/feedback').toEqual([])
  expect(reviewReadResponses, 'read-only navigation must fetch exactly one persisted Review').toHaveLength(1)
  const expected404Messages = consoleErrors.filter((message) => (
    message === 'Failed to load resource: the server responded with a status of 404 (Not Found)'
  ))
  expect(
    consoleErrors.filter((message) => !expected404Messages.includes(message)),
    'browser console must stay free of unexpected errors',
  ).toEqual([])
  expect(
    expected404Messages.length,
    'the browser may log at most the one expected missing persisted-Review probe',
  ).toBeLessThanOrEqual(missingReviewResponses.length)
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
  await changePairEndpoint(page)
  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  await expect(page.locator('.assistant-result')).toHaveCount(0)

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
        model: 'mock-model',
        provider_status: 'OK',
        response_mode: 'LLM_PRIMARY',
        tools_used: ['inspect_current_view'],
      }),
    }).catch(() => undefined).finally(requestFinished)
  })
  await query.fill('Open Pair WHY')
  await page.getByRole('button', { name: 'Hỏi' }).click()
  await requestGate
  await changePairEndpoint(page)
  releaseResponse()
  await finishedGate
  await page.waitForTimeout(100)
  await page.getByRole('button', { name: 'NocPro Assistant' }).click()
  await expect(page.getByText('STALE_PAIR_RESPONSE_MUST_NOT_RENDER')).toBeHidden()
  expect(consoleProblems, 'context change must not produce browser errors or warnings').toEqual([])
})

import { expect, test, type Page } from '@playwright/test'

type ChainSummary = {
  chain_id: string
  member_count: number
}

async function openChain(page: Page, chainId: string) {
  await page.getByRole('button', { name: 'All Chains', exact: true }).click()
  await page.getByText(chainId, { exact: true }).click()
}

test('completed Deep Dive hydrates after browser reload without resubmission', async ({ page }) => {
  const consoleErrors: string[] = []
  const submissions: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/deep-dive')) {
      submissions.push(request.url())
    }
  })

  const response = await page.request.get('/api/v1/chains')
  expect(response.ok()).toBeTruthy()
  const inventory = await response.json() as { chains: ChainSummary[] }
  const chain = inventory.chains.find(item =>
    item.member_count >= 2 && item.member_count <= 20,
  )
  expect(chain, 'active snapshot needs a bounded multi-member chain').toBeDefined()

  await page.goto('/')
  await openChain(page, chain!.chain_id)
  await page.getByRole('button', { name: 'Audit & Structure' }).click()

  const runButton = page.getByRole('button', { name: /Chạy Deep Dive|Run Deep Dive/ }).first()
  await expect(runButton).toBeVisible()
  await runButton.click()
  await expect(
    page.getByRole('region', { name: 'Evidence Coverage Attribution' }),
  ).toBeVisible({ timeout: 120_000 })
  const submissionsAfterCompletion = submissions.length

  await page.reload()
  await openChain(page, chain!.chain_id)
  const hydratedResponse = page.waitForResponse(result =>
    result.request().method() === 'GET'
    && result.url().includes(`/chains/${encodeURIComponent(chain!.chain_id)}/deep-dive`)
    && result.ok(),
  )
  await page.getByRole('button', { name: 'Audit & Structure' }).click()
  await hydratedResponse

  await expect(
    page.getByRole('region', { name: 'Evidence Coverage Attribution' }),
  ).toBeVisible()
  await expect(
    page.getByRole('img', { name: /Audit graph with \d+ nodes and \d+ edges/ }),
  ).toBeVisible()
  expect(submissions.length).toBe(submissionsAfterCompletion)
  expect(consoleErrors).toEqual([])
})

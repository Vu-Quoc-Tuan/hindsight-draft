import { expect, test } from '@playwright/test'

test('synthetic verified sequence renders persisted Evolution without production promotion', async ({ page }) => {
  const inventoryResponse = await page.request.get('/api/v1/chains')
  expect(inventoryResponse.ok()).toBeTruthy()
  const inventory = await inventoryResponse.json() as { chains: Array<{ chain_id: string }> }

  let chainId = ''
  for (const chain of inventory.chains) {
    const response = await page.request.get(`/api/v1/chains/${encodeURIComponent(chain.chain_id)}/evolution`)
    if (!response.ok()) continue
    const evolution = await response.json() as { status: string; source_kind: string | null }
    if (evolution.status === 'AVAILABLE' && evolution.source_kind === 'SYNTHETIC_TEST') {
      chainId = chain.chain_id
      break
    }
  }
  expect(chainId, 'synthetic P2 acceptance must leave a verified sequence active').not.toBe('')

  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Chains Explorer' }).click()
  const row = page.getByRole('row').filter({
    has: page.getByRole('cell', { name: chainId, exact: true }),
  })
  await row.getByRole('button', { name: 'Inspect →' }).click()
  await page.getByRole('button', { name: 'Evolution' }).click()

  const panel = page.getByLabel('Persisted chain evolution')
  await expect(panel).toBeVisible()
  await expect(panel).toContainText('Synthetic test sequence')
  await expect(panel).toContainText('Production validation not established')
  await expect(panel.getByRole('table', { name: 'Chronological lineage edges' })).toBeVisible()
  expect(await panel.locator('.evolution-edge').count()).toBeGreaterThan(1)
  await expect(panel).not.toContainText('joined')
  await expect(panel).not.toContainText('turnover')
  expect(consoleErrors, 'browser console must stay free of errors').toEqual([])
})

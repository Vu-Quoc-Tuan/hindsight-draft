import { expect, test } from '@playwright/test'


test('review tab renders a synthetic Pareto MOVE proposal without applying it', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  const inventoryResponse = await page.request.get('/api/v1/chains')
  expect(inventoryResponse.ok()).toBeTruthy()
  const inventory = await inventoryResponse.json() as {
    snapshot_id: string
    chains: Array<{ chain_id: string; member_count: number }>
  }
  const chain = inventory.chains.find((item) => item.chain_id === 'SYN-CHAIN-MOVE-SOURCE')
  expect(chain, 'Python Kafka acceptance leaves the MOVE fixture active').toBeDefined()

  await page.goto('/')
  await page.getByRole('button', { name: 'Chains Explorer' }).click()
  const row = page.getByRole('row').filter({
    has: page.getByRole('cell', { name: chain!.chain_id, exact: true }),
  })
  await row.getByRole('button', { name: 'Inspect →' }).click()
  await page.getByRole('button', { name: 'Recommendations' }).click()

  const review = page.getByRole('heading', { name: 'Counterfactual chain review' }).locator('..').locator('..')
  await expect(review).toBeVisible()
  await expect(page.getByText('Proposal only', { exact: true })).toBeVisible()
  await expect(page.getByText('NocPro was not changed. No candidate is applied automatically.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'MOVE_MEMBER', exact: true })).toBeVisible()
  const move = page.locator('.review-candidate--recommended').filter({
    hasText: 'Transfer SYN-CHAIN-MOVE-SOURCE → SYN-CHAIN-MOVE-TARGET',
  })
  await expect(move).toHaveCount(1)
  await expect(move).toContainText('SYN-MOVE-MISASSIGNED')
  await expect(move).toContainText('Transfer SYN-CHAIN-MOVE-SOURCE → SYN-CHAIN-MOVE-TARGET')
  await expect(page.getByRole('button', { name: /apply/i })).toHaveCount(0)
  expect(consoleErrors).toEqual([])
})

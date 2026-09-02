import { expect, test } from '@playwright/test'


test('review tab loads the compatible synthetic split proposal without applying it', async ({ page }) => {
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
  const chain = inventory.chains.find((item) => item.chain_id === 'SYN-CHAIN-SPLIT-MUTATED')
  expect(chain, 'Python Kafka acceptance leaves the split fixture active').toBeDefined()

  await page.goto('/')
  await page.getByLabel('Select alarm chain').selectOption(chain!.chain_id)
  await page.getByRole('button', { name: 'Review' }).click()

  const review = page.getByRole('heading', { name: 'Counterfactual chain review' }).locator('..').locator('..')
  await expect(review).toBeVisible()
  await expect(page.getByText('Proposal only', { exact: true })).toBeVisible()
  await expect(page.getByText('NocPro was not changed. No candidate is applied automatically.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'SPLIT_CHAIN' })).toBeVisible()
  const recommended = page.locator('.review-candidate--recommended')
  await expect(recommended).toHaveCount(1)
  await expect(recommended.locator('.review-partition').getByText('8 members', { exact: true })).toHaveCount(2)
  await expect(page.getByRole('button', { name: /apply/i })).toHaveCount(0)
  expect(consoleErrors).toEqual([])
})

import { expect, test, type Page } from '@playwright/test'

type ChainSummary = {
  chain_id: string
  member_count: number
  is_singleton: boolean
}

type ChainList = {
  snapshot_id: string
  snapshot_version: string
  chains: ChainSummary[]
}

async function chainInventory(page: Page): Promise<ChainList> {
  const response = await page.request.get('/api/v1/chains')
  expect(response.ok(), 'Docker API must already expose an active READY snapshot').toBeTruthy()
  return await response.json() as ChainList
}

function requireChain(
  inventory: ChainList,
  predicate: (chain: ChainSummary) => boolean,
  description: string,
): ChainSummary {
  const chain = inventory.chains.find(predicate)
  expect(chain, `active snapshot needs ${description}`).toBeDefined()
  return chain!
}

async function openChain(page: Page, chainId: string) {
  await page.getByRole('button', { name: 'Chains Explorer' }).click()
  const row = page.getByRole('row').filter({
    has: page.getByRole('cell', { name: chainId, exact: true }),
  })
  await row.getByRole('button', { name: 'Inspect →' }).click()
}

test('operator flow exposes indexed WHY, provenance and Tier-2 audit', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  const inventory = await chainInventory(page)
  const pairChain = requireChain(
    inventory,
    (chain) => chain.member_count >= 2 && chain.member_count <= 9,
    'a bounded multi-member chain',
  )
  const auditChain = requireChain(
    inventory,
    (chain) => chain.member_count >= 10 && chain.member_count <= 20,
    'a chain inside the exact Tier-2 audit ceiling',
  )

  await page.goto('/')
  await expect(page.getByRole('main').getByText(`${inventory.snapshot_id}@${inventory.snapshot_version}`, { exact: true })).toBeVisible()
  await openChain(page, pairChain.chain_id)
  await expect(page.getByText('EXACT_INDEXED', { exact: true })).toBeVisible()

  // The hierarchy is part of the chain overview in the redesigned dashboard.
  const tree = page.getByLabel('Hierarchical alarm chain tree')
  const compareControls = tree.locator('.node-compare-btn')
  await expect(compareControls).toHaveCount(pairChain.member_count)

  await page.getByRole('button', { name: 'WHY Grouped' }).click()
  await page.getByText('Scope:', { exact: true }).click()
  await page.getByText('Pair', { exact: true }).last().click()
  const members = await page.getByLabel('Pair endpoint A').locator('option').evaluateAll(options =>
    options.map(option => (option as HTMLOptionElement).value).filter(Boolean),
  )
  expect(members.length).toBeGreaterThanOrEqual(2)
  await page.getByLabel('Pair endpoint A').selectOption(members[0])
  await Promise.all([
    page.waitForResponse(response => response.url().includes('/pairs/') && response.ok()),
    page.getByLabel('Pair endpoint B').selectOption(members[1]),
  ])
  await expect(page.getByLabel('Pair WHY evidence')).toContainText('Dep_hop')
  await expect(page.getByLabel('Pair WHY evidence')).toContainText('UNAVAILABLE')

  await page.getByRole('button', { name: 'arrow_back Chains', exact: true }).click()
  await openChain(page, auditChain.chain_id)
  await page.getByRole('button', { name: 'Audit & Structure' }).click()
  await expect(page.getByRole('heading', { name: 'Structural Audit unavailable' })).toBeVisible()
  await page.getByRole('button', { name: 'Run Deep Dive' }).click()

  const graph = page.getByRole('img', { name: /Audit graph with \d+ nodes and \d+ edges/ })
  await expect(graph).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText('Visualization only; exact Audit uses the full eligible graph.')).toBeVisible()

  const attribution = page.getByRole('region', { name: 'Evidence Coverage Attribution' })
  await expect(attribution).toBeVisible()
  await expect(attribution.getByText('AVAILABLE', { exact: true })).toBeVisible()
  await expect(attribution.getByText('EXACT', { exact: true })).toBeVisible()
  await expect(attribution).toContainText('evidence coverage')
  await expect(attribution).not.toContainText('causal importance')
  await expect(attribution).not.toContainText('cohesion')

  expect(consoleErrors, 'browser console must stay free of errors').toEqual([])
})

test('singleton remains first class and is never made weak by missing pairs', async ({ page }) => {
  const inventory = await chainInventory(page)
  const singleton = requireChain(
    inventory,
    (chain) => chain.is_singleton && chain.member_count === 1,
    'a singleton chain',
  )

  await page.goto('/')
  await openChain(page, singleton.chain_id)
  await expect(page.getByText('NOT_APPLICABLE', { exact: true })).toBeVisible()
  await expect(page.getByText('WEAK', { exact: true }).locator('..')).toContainText('0')
  await expect(
    page.getByLabel('Hierarchical alarm chain tree').locator('.node-compare-btn'),
  ).toHaveCount(1)
})

import { expect, test, type Page } from '@playwright/test'

type ChainSummary = {
  chain_id: string
  member_count: number
  is_singleton: boolean
}

type ChainList = {
  snapshot_id: string
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
  await expect(page.getByText(inventory.snapshot_id, { exact: true })).toBeVisible()
  await page.getByLabel('Select alarm chain').selectOption(pairChain.chain_id)
  await expect(
    page.getByRole('heading', { level: 1, name: `Chain ${pairChain.chain_id}` }),
  ).toBeVisible()
  await expect(page.getByText('exact indexed', { exact: true })).toBeVisible()
  await expect(page.getByText('What defines this chain')).toBeVisible()
  await expect(page.getByText('Role distribution')).toBeVisible()

  const timeline = page.getByLabel('Bounded member timeline')
  const nodes = timeline.locator('button')
  await expect(nodes).toHaveCount(pairChain.member_count)
  await nodes.nth(0).click()
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/pairs/') && response.ok()),
    nodes.nth(1).click(),
  ])
  await expect(page.getByText(/evidence channels$/)).toBeVisible()
  const dependencyEvidence = page.locator('.evidence-item').filter({ hasText: 'DEP_HOP' })
  await expect(dependencyEvidence).toContainText('UNAVAILABLE')

  await page.getByLabel('Select alarm chain').selectOption(auditChain.chain_id)
  await page.getByRole('button', { name: 'Structure' }).click()
  await expect(page.getByText('Audit graph not computed')).toBeVisible()
  await page.getByRole('button', { name: /Run deep dive/ }).click()
  const similar = page.getByLabel('Similar chains')
  await expect(similar).toBeVisible()
  await expect(similar.getByText('AVAILABLE', { exact: true })).toBeVisible()
  await expect(similar).toContainText('HISTORY_BEFORE_SNAPSHOT')
  await expect(similar).toContainText('SNAPSHOT_VERSIONED')
  await expect(similar).toContainText('UNAVAILABLE')
  await expect(similar).toContainText(/alarm taxonomy not used by source/i)
  await expect(similar.locator('.similar-model')).toContainText('sim_')

  const topology = page.getByRole('region', { name: 'Topology hypotheses' })
  await expect(topology).toBeVisible()
  await expect(topology.getByRole('heading', { name: 'Unavoidable dependency annotation' })).toBeVisible()
  await expect(topology.getByRole('heading', { name: 'Propagation hypothesis score' })).toBeVisible()
  await expect(topology.getByRole('heading', { name: 'Dependency scope overlap signal' })).toBeVisible()
  await expect(topology.getByText('UNAVAILABLE', { exact: true })).toHaveCount(3)
  await expect(topology).toContainText('PROPAGATION_CONFIG_INCOMPLETE')
  await expect(topology).toContainText('DIRECTED_TOPOLOGY_UNAVAILABLE')

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
  await page.getByLabel('Select alarm chain').selectOption(singleton.chain_id)
  await expect(page.getByText('singleton path', { exact: false })).toBeVisible()
  const rolePanel = page.locator('.role-panel')
  await expect(rolePanel).toContainText('not applicable')
  await expect(rolePanel).not.toContainText('weak')
  await expect(page.getByText('Select two alarms')).toBeVisible()
})

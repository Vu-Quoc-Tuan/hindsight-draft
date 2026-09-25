import { expect, test } from '@playwright/test'

test('active chain opens the application topology workspace without promoting navigation to P2', async ({ page }) => {
  const topologyEndpoint = `${(process.env.NOCPRO_E2E_TOPOLOGY_URL || 'http://127.0.0.1:3000/api/v1/topology').replace(/\/$/, '')}/resolve`
  const sourceIdentifier = process.env.NOCPRO_E2E_IT_SOURCE_IDENTIFIER
  test.skip(!sourceIdentifier, 'acceptance must select an unambiguous IT source identifier')
  expect(sourceIdentifier).toBeTruthy()

  const resolutionResponse = await page.request.get(
    `${topologyEndpoint}?profile_id=IT_SERVICES&identifier=${encodeURIComponent(sourceIdentifier!)}`,
  )
  expect(resolutionResponse.ok()).toBeTruthy()
  const resolution = await resolutionResponse.json() as {
    status: string
    resource_id: string | null
    p2_mapping_eligible: boolean
    dependency_semantics: string
  }
  expect(resolution.status).toBe('AVAILABLE')
  expect(resolution.resource_id).toBeTruthy()
  expect(resolution.p2_mapping_eligible).toBe(false)
  expect(resolution.dependency_semantics).toBe('UNVERIFIED')

  const chainsResponse = await page.request.get('/api/v1/chains')
  expect(chainsResponse.ok(), 'acceptance must expose an active READY snapshot').toBeTruthy()
  const chainList = await chainsResponse.json() as {
    chains: Array<{ chain_id: string; member_count: number }>
  }
  const chain = chainList.chains.find(item => item.member_count > 0)
  expect(chain, 'active snapshot must contain a chain to open').toBeDefined()

  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (
      message.type() === 'error'
      && message.text() !== 'Failed to load resource: net::ERR_CONNECTION_CLOSED'
    ) consoleErrors.push(message.text())
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'All Chains', exact: true }).click()
  await page.getByText(chain!.chain_id, { exact: true }).click()
  const topologyResponse = page.waitForResponse(response =>
    response.url().includes('/api/v1/topology/subgraph'),
  )
  await page.getByRole('button', { name: /Topology/ }).click()
  await expect(page.getByRole('heading', {
    name: 'Kết nối topology giữa các thiết bị có cảnh báo',
  })).toBeVisible()
  expect((await topologyResponse).ok(), 'application topology tab must load its subgraph API').toBeTruthy()
  await expect(page.getByRole('heading', { name: 'NocPro topology tree' })).toHaveCount(0)
  expect(consoleErrors, 'topology navigation must not log browser errors').toEqual([])
})

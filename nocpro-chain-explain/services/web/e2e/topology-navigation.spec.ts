import { expect, test } from '@playwright/test'

test('real IT source identifier opens a read-only topology tree without P2 promotion', async ({ page }) => {
  const mockUrl = process.env.NOCPRO_E2E_MOCK_URL
  const sourceIdentifier = process.env.NOCPRO_E2E_IT_SOURCE_IDENTIFIER
  expect(mockUrl, 'acceptance must expose the mock topology endpoint').toBeTruthy()
  expect(sourceIdentifier, 'acceptance must select an unambiguous IT source identifier').toBeTruthy()

  const resolutionResponse = await page.request.get(
    `${mockUrl}/api/topology/resolve?profile_id=IT_SERVICES&identifier=${encodeURIComponent(sourceIdentifier!)}`,
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

  const consoleErrors: string[] = []
  page.on('console', (message) => {
    // Opening a resolved root aborts the previous bounded projection request.
    // Chromium may surface that deliberate AbortController cancellation as a
    // transport-only console line; UI/API errors still fail this acceptance.
    if (
      message.type() === 'error'
      && message.text() !== 'Failed to load resource: net::ERR_CONNECTION_CLOSED'
    ) consoleErrors.push(message.text())
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Topology' }).click()
  await expect(page.getByRole('heading', { name: 'Topology records' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Relation Tree Projection' })).toBeVisible()

  await page.getByPlaceholder('Open exact source key or IP…').fill(sourceIdentifier!)
  await page.getByRole('button', { name: 'Open source key' }).click()
  await expect(page.getByText(`Opened ${resolution.resource_id}`)).toBeVisible()
  await expect(page.getByTestId('topology-selected-resource')).toHaveAttribute('data-resource-id', resolution.resource_id!)
  await expect(page.getByText(/Navigation only; dependency analysis remains unverified/i)).toBeVisible()
  await expect(page.getByText('P2 capability')).toHaveCount(0)
  expect(consoleErrors, 'topology navigation must not log browser errors').toEqual([])
})

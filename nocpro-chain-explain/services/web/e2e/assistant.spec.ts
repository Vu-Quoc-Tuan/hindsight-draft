import { expect, test } from '@playwright/test'

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

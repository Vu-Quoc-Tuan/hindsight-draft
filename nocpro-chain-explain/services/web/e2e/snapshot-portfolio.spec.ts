import { expect, test, type Route } from '@playwright/test'

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

test('snapshot portfolio and all chains stay evidence-backed', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/health') return json(route, { status: 'ok' })
    if (path === '/api/v1/config') return json(route, { config_version: 'cfg-1' })
    if (path === '/api/v1/snapshots') return json(route, {
      active_snapshot_id: 'S1', active_snapshot_version: 'v1',
      snapshots: [{ snapshot_id: 'S1', name: 'IP replay', profile: 'IP_NETWORK', alarm_count: 7, chain_count: 3, description: 'Observed replay', badge: 'Replay', available: true }],
    })
    if (path === '/api/v1/snapshots/quality-summaries') return json(route, { summaries: [{
      snapshot_id: 'S1', snapshot_version: 'v1', total_chain_count: 3, eligible_chain_count: 2,
      sturdy_count: 1, review_count: 0, evaluating_count: 1, unevaluated_count: 0, not_applicable_count: 1,
      star_counts: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 0 },
      attention_chains: [],
      chain_assessments: [
        { chain_id: 'C1', member_count: 4, title: 'component=10.1.1.1', duration_seconds: 60, status: 'EVALUATED', stars: 4, label: 'Vững', reason: null },
        { chain_id: 'C2', member_count: 2, title: 'network_class_name=CORE_LAYER', duration_seconds: null, status: 'EVALUATING', stars: null, label: 'Đang đánh giá', reason: null },
        { chain_id: 'C3', member_count: 1, title: 'device_code=RTR-1', duration_seconds: null, status: 'NOT_APPLICABLE', stars: null, label: 'Singleton không chấm', reason: null },
      ],
    }] })
    if (path === '/api/v1/chains') return json(route, { snapshot_id: 'S1', snapshot_version: 'v1', chains: [
      { chain_id: 'C1', member_count: 4, is_singleton: false, title: 'component=10.1.1.1 (57% of chain)', start_time: '2026-09-21T00:00:00Z', end_time: '2026-09-21T00:01:00Z', duration_seconds: 60 },
      { chain_id: 'C2', member_count: 2, is_singleton: false, title: 'network_class_name=CORE_LAYER (50% of chain)', start_time: null, end_time: null, duration_seconds: null },
      { chain_id: 'C3', member_count: 1, is_singleton: true, title: 'device_code=RTR-1 (100% of chain)', start_time: null, end_time: null, duration_seconds: null },
    ] })
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"fixture unavailable"}' })
  })

  await page.goto('/')
  await expect(page.getByText('1 vững')).toBeVisible()
  await expect(page.getByText('1 đang chạy')).toBeVisible()

  await page.getByRole('button', { name: 'Snapshots', exact: true }).click()
  await expect(page.getByText('Toàn bộ dữ liệu đã tiếp nhận')).toBeVisible()
  await expect(page.getByText('1/2')).toBeVisible()
  await expect(page.getByText('50%', { exact: true })).toBeVisible()
  await expect(page.getByText('Tổng quan trạng thái snapshot')).toBeVisible()
  await expect(page.getByLabel('Snapshot status summary').getByText('Đang đánh giá', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'All Chains', exact: true }).click()
  await expect(page.getByText('Toàn bộ chain trong snapshot')).toBeVisible()
  await expect(page.getByText('C1')).toBeVisible()
  await expect(page.getByText('C2')).toBeVisible()
  await expect(page.getByText('C3')).toBeVisible()
  await expect(page.getByRole('button', { name: /C1/ }).getByText('★★★★☆')).toBeVisible()
  await expect(page.getByText('Lọc theo sao')).toBeVisible()
  await expect(page.getByPlaceholder('Tìm chain ID hoặc tiêu đề…')).toHaveCount(0)
  await expect(page.getByText('Attribute explorer')).toHaveCount(0)
  expect(consoleErrors).toEqual([])
})

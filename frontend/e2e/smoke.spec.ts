import { expect, test } from '@playwright/test'

test.describe('Loci smoke', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/**', async (route) => {
      const url = route.request().url()
      if (url.includes('/auth/session') || url.includes('/auth/login')) {
        return route.fulfill({
          json: { authenticated: true, username: 'smoke' },
        })
      }
      if (url.includes('/api/health') || url.endsWith('/api/')) {
        return route.fulfill({ json: { status: 'ok' } })
      }
      if (url.includes('/candidates/list')) {
        return route.fulfill({
          json: [
            {
              id: 'c1',
              date: '2026-07-28',
              code: '600519',
              name: '贵州茅台',
              decision: '精选',
              rule_version: 'qianlong',
              timing: 'close',
              score: 88,
              reason: 'smoke',
              source: 'test',
              pool_id: 'p1',
              evidence: {},
            },
          ],
        })
      }
      if (url.includes('/strategies')) {
        return route.fulfill({ json: [{ slug: 'qianlong', name: '潜龙' }] })
      }
      if (url.includes('/market/board') || url.includes('/market/session')) {
        return route.fulfill({
          json: {
            items: [],
            total: 0,
            as_of: '2026-07-28T15:00:00',
            live_allowed: false,
          },
        })
      }
      return route.fulfill({ status: 200, json: {} })
    })
  })

  test('pool virtual table renders mocked candidates', async ({ page }) => {
    // createWebHistory：路径是 /pool，不是 /#/pool
    await page.goto('/pool')
    await expect(page.getByText('贵州茅台')).toBeVisible({ timeout: 30_000 })
  })

  test('data query shell loads', async ({ page }) => {
    await page.goto('/data')
    await expect(page.getByRole('textbox', { name: '关键词' })).toBeVisible({ timeout: 30_000 })
  })
})

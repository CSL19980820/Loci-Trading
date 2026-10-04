/** Click the real screening navigation in compiled UI; ALL API calls are local fixtures. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

const base = process.env.SCREEN_BASE || 'http://127.0.0.1:5189'
const output = process.env.SCREEN_OUT || path.resolve('../.local/screen-menu-fix/ui-local')
const origin = new URL(base).origin
await fs.mkdir(output, { recursive: true })
const strategy = { slug: 'menu-fixture', name: '选股入口验收战法', description: '仅浏览器夹具，不执行真实选股', params: {}, required_fields: [], min_bars: 20, entry_timing: 'next_open' }
const history = { strategy: strategy.slug, total: 0, dates: [], by_date: {} }
const result = { strategy: strategy.slug, strategy_revision: 'fixture', trade_date: '2026-09-22', entry_timing: 'next_open', universe_size: 2, elapsed_seconds: 0.1, params: {}, effective_params: {}, picks: [], watch_picks: [] }
const completed = { strategy: strategy.slug, status: 'done', phase: 'done', done: 2, total: 2, percent: 100, started_at: '2026-09-22T08:00:00Z', finished_at: '2026-09-22T08:00:01Z', result, log: ['隔离交互验收完成'] }
const browser = await chromium.launch({ headless: true })
const receipts = []
try {
  for (const [name, width, collapsed] of [['desktop', 1440, false], ['desktop-collapsed', 1440, true], ['mobile', 390, false], ['mobile-narrow', 320, false]]) {
    const context = await browser.newContext({ viewport: { width, height: 960 }, serviceWorkers: 'block', reducedMotion: 'reduce' })
    const page = await context.newPage()
    const errors = [], gaps = [], requests = [], submitted = [], unexpectedWrites = []
    page.on('pageerror', error => errors.push(String(error)))
    await context.route('**/*', async handler => {
      const request = handler.request(), url = new URL(request.url())
      if (url.origin !== origin) return handler.abort()
      if (!url.pathname.startsWith('/api/')) {
        // The server's document authentication is NOT changed; this test uses a fixture session only.
        if (!base.includes('127.0.0.1') && request.isNavigationRequest() && url.pathname !== '/login') {
          const document = await context.request.get(`${base}/login`)
          return handler.fulfill({ response: document })
        }
        return handler.continue()
      }
      requests.push(`${request.method()} ${url.pathname}`)
      if (request.method() === 'POST' && url.pathname === '/api/screen/run') {
        submitted.push(request.postDataJSON())
        return handler.fulfill({ contentType: 'application/json', body: JSON.stringify(completed) })
      }
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        unexpectedWrites.push(`${request.method()} ${url.pathname}`)
        return handler.fulfill({ status: 405, contentType: 'application/json', body: '{}' })
      }
      let fixture
      if (url.pathname === '/api/strategies') fixture = { body: [strategy] }
      else if (url.pathname === '/api/screen/history') fixture = { body: history }
      else if (url.pathname === '/api/screen/history/batch') fixture = { body: { strategies: [strategy.slug], histories: [history] } }
      else if (url.pathname === '/api/screen/run' && submitted.length) fixture = { body: { ...completed, runs: { [strategy.slug]: completed }, running_strategies: [], max_concurrent_runs: 2 } }
      else fixture = routeFixture(url, 'screen-navigation')
      if (!fixture) gaps.push(url.pathname)
      return handler.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? {}) })
    })
    try {
      // Regression must start at the candidate page and click the menu, never just visit the target URL.
      await page.goto(`${base}/pool`, { waitUntil: 'domcontentloaded', timeout: 45000 })
      const nav = page.getByRole('navigation', { name: width < 768 ? '主导航' : '功能导航', exact: true })
      await expect(nav.getByRole('link', { name: '候选', exact: true })).toBeVisible()
      if (collapsed) await page.getByRole('button', { name: '收起侧栏', exact: true }).click()
      const screen = nav.getByRole('link', { name: '选股', exact: true })
      await expect(screen).toBeVisible()
      await expect(screen).toHaveAttribute('href', '/screen-history')
      await screen.click()
      await expect(page).toHaveURL(/\/screen-history(?:\?|$)/)
      await expect(screen).toHaveAttribute('aria-current', 'page')
      await expect(nav.locator('[aria-current="page"]')).toHaveCount(1)
      await expect(page.getByRole('region', { name: '选股执行与结果' })).toBeVisible()
      const run = page.locator(width < 768 ? '.screen-phone-run' : '.screen-run-primary')
      await expect(run).toBeEnabled({ timeout: 15000 })
      if (width < 768) {
        await expect(page.locator('.screen-phone-catalog')).toContainText(strategy.name)
        await page.getByRole('button', { name: '选股条件', exact: true }).click()
        const dialog = page.getByRole('dialog', { name: '选股条件' })
        await expect(dialog.locator('[aria-label="交易日区间"]').first()).toBeVisible()
        await dialog.getByRole('checkbox').uncheck()
        await dialog.getByRole('button', { name: '应用', exact: true }).click()
      } else {
        await expect(page.getByRole('textbox', { name: '搜索战法或技能' })).toBeVisible()
        await expect(page.locator('.screen-catalog').getByText(strategy.name, { exact: true })).toBeVisible()
        await page.getByRole('checkbox', { name: '入库候选' }).uncheck()
      }
      await run.click()
      await expect(page.getByText('已完成', { exact: true }).first()).toBeVisible()
      await expect(page.getByText(/今日结果\s*·\s*2026-09-22/)).toBeVisible()
      assert.equal(submitted.length, 1)
      assert.equal(submitted[0].strategy, strategy.slug)
      assert.equal(submitted[0].record_candidates, false)
      assert.equal(submitted[0].skip_health_check, undefined)
      await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true })
      if (width < 768) {
        const bounds = await nav.locator('.nav-tab').evaluateAll(nodes => nodes.map(node => { const r = node.getBoundingClientRect(); return { width: r.width, height: r.height } }))
        assert.ok(bounds.every(r => r.width >= 44 && r.height >= 44), JSON.stringify(bounds))
      }
      if (width >= 768) {
        await page.getByRole('button', { name: '入库历史', exact: true }).click()
        await expect(page.locator('.screen-history-dialog')).toBeVisible()
        await page.keyboard.press('Escape')
        await nav.getByRole('link', { name: '候选', exact: true }).click()
        await page.getByRole('button', { name: '搜索或跳转', exact: true }).click()
        const palette = page.getByRole('dialog')
        await palette.getByPlaceholder('搜索页面、操作或外观…').fill('选股')
        await palette.getByRole('option').filter({ hasText: '选股' }).first().click()
        await expect(page).toHaveURL(/\/screen-history(?:\?|$)/)
      }
      await page.waitForLoadState('networkidle')
      const widthCheck = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }))
      assert.ok(widthCheck.document <= widthCheck.viewport + 2, JSON.stringify(widthCheck))
      assert.deepEqual(errors, []); assert.deepEqual(gaps, []); assert.deepEqual(unexpectedWrites, [])
      assert.equal(requests.some(item => /paper-cabins|community|akshare|hithink/.test(item)), false)
      receipts.push({ name, ok: true, width: widthCheck, selectionRequests: submitted, apiScope: 'all mocked; no production API writes' })
    } catch (error) {
      receipts.push({ name, ok: false, error: String(error), errors, gaps, unexpectedWrites, requests })
      await page.screenshot({ path: path.join(output, `${name}-failed.png`), fullPage: true })
    } finally { await context.close() }
    console.log(JSON.stringify(receipts.at(-1)))
  }
} finally { await browser.close() }
await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(receipts, null, 2))
assert.ok(receipts.every(row => row.ok), 'Screen navigation regression failed')

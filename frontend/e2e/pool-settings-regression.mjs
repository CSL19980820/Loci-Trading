import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

// Real application components; all API requests are intercepted, no real data or writes.
const base = process.env.POOL_SETTINGS_BASE || 'http://127.0.0.1:5187'
const baseline = process.argv.includes('--baseline')
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const out = path.join(root, '.local/pool-settings-20260929')
await fs.mkdir(out, { recursive: true })
const strategy = { slug: 'fixture-yang', name: '杨氏尾盘选股（15:30）', description: '隔离回归夹具', params: {}, required_fields: [], min_bars: 20, entry_timing: 'next_open' }
const live = { id: 'fixture-live', date: '2026-09-29', code: '300616', name: '尚品宅配', score: 93.07, decision: '精选', timing: 'next_open', reason: '隔离夹具：当日选出', rule_version: strategy.name, strategy_slug: strategy.slug, pool_id: 'fixture-yang@2026-09-29', source: 'api:screen', created_at: '2026-09-29 15:30:00', evidence: {} }
const history = { ...live, id: 'fixture-history', date: '2026-09-22', score: 92.52, pool_id: 'fixture-yang@2026-09-22', source: 'api:screen_backfill', reason: '隔离夹具：历史回填，不是当日实时选出' }
const servers = ['loci-market', 'wudao', 'hithink-finance-a-share', 'hithink-finance-a-share-index', 'hithink-finance-fund', 'hithink-finance-futures', 'hithink-finance-meta', 'hithink-finance-options'].map((name, index) => ({ id: `fixture-${index}`, name, url: '', token_last4: '', has_token: false, is_active: true, is_usable: true, builtin: true, resident: index > 0, source: 'fixture', tools_synced_at: '', tools: [{ name: 'fixture-tool', description: '不执行工具' }], note: '隔离布局验收，不使用真实服务' }))
const browser = await chromium.launch({ headless: true })
const results = []

async function openPage(scenario, width, dark = false) {
  const context = await browser.newContext({ viewport: { width, height: 960 }, serviceWorkers: 'block', reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.setDefaultTimeout(12000)
  const state = { errors: [], gaps: [], writes: [], candidates: [] }
  page.on('pageerror', error => state.errors.push(String(error)))
  page.on('console', message => { if (/Failed to resolve component|Unhandled error|Invalid vnode|Invalid prop/.test(message.text())) state.errors.push(message.text()) })
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.origin !== new URL(base).origin) return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      state.writes.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({ status: 405, contentType: 'application/json', body: '{}' })
    }
    let fixture
    if (url.pathname === '/api/candidates/list') {
      state.candidates.push(Object.fromEntries(url.searchParams))
      const all = url.searchParams.get('include_backfill') === 'true' || url.searchParams.get('include_backfill') === '1'
      fixture = { body: all ? [live, history] : [live] }
    } else if (url.pathname === '/api/strategies') fixture = { body: [strategy] }
    else if (url.pathname === '/api/jobs') fixture = { body: [{ name: 'screen:fixture-yang', kind: 'screen', enabled: true }] }
    else if (url.pathname === '/api/mcp') fixture = { body: servers }
    else if (url.pathname === '/api/market/quotes/300616') fixture = { body: { code: '300616', name: '尚品宅配', adjust: 'qfq', bars: [], rows: 0 } }
    else fixture = routeFixture(url, scenario)
    if (!fixture) state.gaps.push(url.pathname)
    await route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? { detail: '隔离夹具未提供' }) })
  })
  await page.clock.setFixedTime(new Date('2026-09-29T08:00:00Z'))
  await page.goto(`${base}/${scenario}`, { waitUntil: 'networkidle', timeout: 60000 })
  await page.evaluate(async dark => {
    const { applyTheme, getStoredPrimary } = await import('/src/shared/lib/theme.ts')
    applyTheme(dark ? 'night' : 'day', getStoredPrimary())
  }, dark)
  return { context, page, state }
}

async function measure(page) {
  return page.evaluate(() => {
    const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden'
    const boxes = selector => [...document.querySelectorAll(selector)].filter(visible).map(el => {
      const r = el.getBoundingClientRect(), style = getComputedStyle(el)
      return { x: r.x, y: r.y, width: r.width, height: r.height, flex: style.flex, maxWidth: style.maxWidth, scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }
    })
    return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, buttons: boxes('.settings-rail__item'), panes: boxes('.ops-pane'), panels: boxes('.settings-panel'), cards: boxes('.mcp-card') }
  })
}

async function check(name, scenario, width, run, dark = false) {
  const opened = await openPage(scenario, width, dark)
  const row = { name, width, dark, ok: false }
  results.push(row)
  try {
    await run(opened.page, row, opened.state)
    assert.deepEqual(opened.state.errors, [])
    assert.deepEqual(opened.state.gaps, [])
    assert.deepEqual(opened.state.writes, [])
    row.ok = true
  } catch (error) {
    row.error = String(error)
    console.error(name, row.error)
    await opened.page.screenshot({ path: path.join(out, `${name}-failure.png`) })
  } finally {
    row.api = opened.state
    await opened.context.close()
    await fs.writeFile(path.join(out, baseline ? 'baseline.json' : 'results.json'), JSON.stringify(results, null, 2))
    console.log(JSON.stringify({ name, ok: row.ok, error: row.error, measurements: row.measurements }))
  }
}

try {
  for (const width of (baseline ? [1800] : [1800, 1366, 980, 390, 320])) {
    await check(`settings-${width}${baseline ? '-before' : ''}`, 'ops', width, async (page, row) => {
      await expect(page.locator('.mcp-row')).toHaveCount(8)
      row.measurements = await measure(page)
      await page.screenshot({ path: path.join(out, `settings-${width}${baseline ? '-before' : '-after'}.png`) })
      if (baseline) return
      const m = row.measurements
      assert(m.documentWidth <= width + 1, JSON.stringify(m))
      assert(m.panels[0].width >= m.panes[0].width - 22, JSON.stringify(m))
      if (width > 980) {
        assert(m.buttons.length === 4 && m.buttons.every(button => button.height >= 38), JSON.stringify(m))
        const first = page.locator('[data-settings-rail="mcp"]')
        await first.focus(); await first.press('ArrowDown')
        await expect(page.locator('[data-settings-rail="llm"]')).toBeFocused()
        await expect(page.locator('#ops-main-panel')).toHaveAttribute('aria-labelledby', 'ops-main-panel-tab-llm')
      }
      const tabs = await page.locator('[role="tab"]:visible').all()
      for (const tab of tabs) {
        await tab.click()
        const panel = page.locator('.ops-pane:visible')
        await expect(panel).toBeVisible()
        const dimensions = await measure(page)
        assert(dimensions.documentWidth <= width + 1, JSON.stringify(dimensions))
        for (const content of dimensions.panels) assert(content.width >= dimensions.panes[0].width - 22, JSON.stringify(dimensions))
        const controls = await tab.getAttribute('aria-controls')
        assert(controls && await page.locator(`[id="${controls}"]`).count() === 1)
      }
    }, width === 1366)
  }
  if (!baseline) {
    for (const [width, dark] of [[1800, false], [1366, true], [390, false], [320, false]]) {
      await check(`pool-${width}${dark ? '-dark' : ''}`, 'pool', width, async (page, row, state) => {
        const mobile = width < 768
        const candidateRows = page.locator(mobile ? '.pool-mobile-row' : '.pool-stock-table tbody tr')
        await expect(candidateRows).toHaveCount(1)
        const scope = page.getByRole('switch', { name: '包含历史回填', exact: true })
        await expect(scope).not.toBeChecked()
        await page.getByText('2026-09-29', { exact: true }).first().click()
        await expect(page.locator('.fp__dot')).toHaveCount(2)
        await expect(page.locator('.fp__history-note')).toContainText('其中 1 次为历史回填')
        await expect(page.locator('.fp__dot.is-backfill')).toHaveAttribute('aria-label', /历史回填/)
        await page.screenshot({ path: path.join(out, `detail-${width}${dark ? '-dark' : ''}.png`) })
        await page.locator('.cand__foot').getByRole('button', { name: '关闭', exact: true }).click()
        await scope.click()
        await expect(scope).toBeChecked()
        await expect(candidateRows).toHaveCount(2)
        await expect(candidateRows.filter({ hasText: '2026-09-22' })).toContainText('历史回填')
        await expect(candidateRows.filter({ hasText: '2026-09-22' }).getByText('历史回填', { exact: true })).toBeVisible()
        await page.getByText('2026-09-22', { exact: true }).first().click()
        await expect(page.locator('.cand__meta')).toContainText('历史回填')
        await page.locator('.cand__foot').getByRole('button', { name: '关闭', exact: true }).click()
        await page.screenshot({ path: path.join(out, `pool-${width}${dark ? '-dark' : ''}.png`) })
        await scope.click()
        await expect(candidateRows).toHaveCount(1)
        await scope.click()
        await expect(candidateRows).toHaveCount(2)
        if (mobile) {
          await page.getByRole('button', { name: '更多筛选', exact: true }).click()
          await page.getByRole('button', { name: '取消', exact: true }).click()
          await expect(scope).toBeChecked()
          await page.getByRole('button', { name: '更多筛选', exact: true }).click()
          await page.getByRole('button', { name: '重置全部', exact: true }).click()
        } else await page.getByRole('button', { name: '重置', exact: true }).click()
        await expect(scope).not.toBeChecked()
        await expect(candidateRows).toHaveCount(1)
        assert(state.candidates.some(q => !q.code && ['true', '1'].includes(q.include_backfill)))
        assert(state.candidates.some(q => q.code === '300616' && ['true', '1'].includes(q.include_backfill)))
        row.measurements = await measure(page)
        assert(row.measurements.documentWidth <= width + 1, JSON.stringify(row.measurements))
      }, dark)
    }
  }
} finally { await browser.close() }
console.log(`Evidence: ${out}; ${results.filter(row => row.ok).length}/${results.length} passed`)
if (results.some(row => !row.ok)) process.exitCode = 1

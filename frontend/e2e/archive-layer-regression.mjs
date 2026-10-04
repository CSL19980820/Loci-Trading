/** Real cached source dialogs and archive UI; all API requests use local fixtures. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

const base = process.env.ARCHIVE_LAYER_BASE || 'http://127.0.0.1:5195'
const output = process.env.ARCHIVE_LAYER_OUT || path.resolve('../.local/archive-layer-regression')
const baseline = process.argv.includes('--baseline')
const strategy = { slug: 'archive-layer-fixture', name: '回填弹层验收战法', description: '隔离浏览器夹具', params: {}, required_fields: [], min_bars: 20, entry_timing: 'next_open' }
const candidate = { id: 'archive-layer-fixture', code: '000001', name: '回填验收标的', date: '2026-09-29', decision: '精选', score: 90, reason: '仅隔离历史回填夹具', strategy_slug: strategy.slug, rule_version: strategy.name, source: 'api:screen_backfill', created_at: '2026-09-30 08:00:00', pool_id: `${strategy.slug}@2026-09-29`, evidence: {} }
const second = { ...candidate, id: 'archive-layer-second', code: '000002', name: '第二验收标的' }
const slimCandidates = [candidate, second].map(({ evidence, ...item }) => item)
const history = { strategy: strategy.slug, total: 2, dates: [candidate.date], by_date: { [candidate.date]: [candidate, second] } }
const bars = Array.from({ length: 60 }, (_, index) => ({ trade_date: new Date(Date.UTC(2026, 7, 2 + index)).toISOString().slice(0, 10), open: 10 + index / 100, close: 10.05 + index / 100, high: 10.1 + index / 100, low: 9.9 + index / 100, volume: 100000, amount: 1000000, turnover: 0.01 }))

await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const [source, width] of [['screen-history', 1440], ['pool', 1440], ['screen-history', 390], ['pool', 390]]) {
    const context = await browser.newContext({ viewport: { width, height: 960 }, serviceWorkers: 'block', reducedMotion: 'reduce' })
    const page = await context.newPage()
    const result = { source, width, errors: [], gaps: [], writes: [] }
    results.push(result)
    page.on('pageerror', error => result.errors.push(String(error)))
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        result.writes.push(`${request.method()} ${url.pathname}`)
        return route.fulfill({ status: 405, contentType: 'application/json', body: '{}' })
      }
      let fixture
      if (url.pathname === '/api/strategies') fixture = { body: [strategy] }
      else if (url.pathname === '/api/screen/history') fixture = { body: url.searchParams.get('live_only') === 'false' ? history : { ...history, total: 0, dates: [], by_date: {} } }
      else if (url.pathname === '/api/screen/history/batch') fixture = { body: { strategies: [strategy.slug], histories: [history] } }
      else if (url.pathname === '/api/candidates/list') fixture = { body: url.searchParams.get('include_backfill') === 'true' || url.searchParams.get('include_backfill') === '1' ? slimCandidates : [] }
      else if (url.pathname === `/api/candidates/${candidate.id}`) fixture = { body: candidate }
      else if (url.pathname === `/api/candidates/${second.id}`) fixture = { body: second }
      else if (/^\/api\/market\/quotes\/00000[12]$/.test(url.pathname)) fixture = { body: { code: url.pathname.split('/').at(-1), name: url.pathname.endsWith('000001') ? candidate.name : second.name, adjust: 'qfq', rows: bars.length, total_rows: bars.length, bars } }
      else fixture = routeFixture(url, source)
      if (!fixture) result.gaps.push(url.pathname)
      return route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? {}) })
    })
    try {
      await page.goto(`${base}/${source}`, { waitUntil: 'networkidle', timeout: 45000 })
      if (source === 'screen-history') {
        if (width < 768) {
          await page.getByRole('button', { name: '选股操作', exact: true }).click()
          await page.getByRole('menuitem', { name: '入库历史', exact: true }).click()
        } else await page.getByRole('button', { name: '入库历史', exact: true }).click()
        await page.getByRole('switch', { name: '含区间回填', exact: true }).check()
        await page.locator('.screen-history-dialog').getByRole('button', { name: '详情', exact: true }).click()
        await expect(page.locator('.history-detail-dialog')).toBeVisible()
        await page.locator('.history-detail-dialog').getByRole('link', { name: `${candidate.name} ${candidate.code}`, exact: true }).click()
      } else {
        await page.getByRole('switch', { name: '包含历史回填', exact: true }).check()
        if (width < 768) await page.getByRole('button', { name: `查看${candidate.name}候选详情`, exact: true }).click()
        else await page.locator('.pool-stock-table tbody tr').filter({ hasText: candidate.name }).getByText(candidate.date, { exact: true }).click()
        await expect(page.locator('.cand__title')).toContainText(candidate.name)
        await page.locator('.cand__title').getByRole('link', { name: candidate.name, exact: true }).click()
      }
      await expect(page).toHaveURL(/\/archive\/000001\?date=2026-09-29$/)
      await expect(page.locator('.archive-overlay')).toBeVisible()
      await expect(page.locator(width < 768 ? '.mobile-stock-header' : '.sw-name')).toContainText(candidate.name)
      // Visibility alone misses the bug: the archive exists underneath an earlier portal mask.
      const layers = await page.locator('.archive-overlay').evaluate(element => {
        const r = element.getBoundingClientRect()
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
        return { foreground: element.contains(hit), topSlot: hit?.getAttribute('data-slot') || hit?.tagName || '', dialogs: [...document.querySelectorAll('[role="dialog"]')].filter(dialog => dialog.getClientRects().length > 0).map(dialog => ({ title: document.getElementById(dialog.getAttribute('aria-labelledby'))?.textContent, zIndex: getComputedStyle(dialog).zIndex })) }
      })
      result.layers = layers
      if (baseline) {
        assert.equal(layers.foreground, false, 'Baseline should reproduce the source dialog covering the archive')
        await page.screenshot({ path: path.join(output, `${source}-${width}-baseline.png`) })
        result.ok = true
        continue
      }
      assert.equal(layers.foreground, true, JSON.stringify(layers))
      assert.equal(layers.dialogs.length, 1, JSON.stringify(layers))
      const archive = page.locator('.archive-overlay')
      const historyButton = width < 768 ? archive.getByRole('button', { name: /选股记录/ }) : archive.locator('.sw-history')
      await historyButton.click()
      await expect(page.locator('.sw-history-dialog')).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.locator('.sw-history-dialog')).toHaveCount(0)
      await expect(page).toHaveURL(/\/archive\/000001/)
      await expect(historyButton).toBeFocused()
      await page.screenshot({ path: path.join(output, `${source}-${width}-archive.png`) })
      await archive.getByRole('button', { name: width < 768 ? '返回' : '返回本批来源', exact: true }).first().click()
      await expect(page).toHaveURL(new RegExp(`/${source}(?:\\?|$)`))
      result.restored = await page.evaluate(() => ({ focus: document.activeElement?.tagName, dialogs: [...document.querySelectorAll('[role="dialog"][data-state="open"]')].map(element => ({ title: document.getElementById(element.getAttribute('aria-labelledby'))?.textContent, hidden: element.getAttribute('aria-hidden') })) }))
      if (source === 'screen-history') {
        await expect(page.locator('.history-detail-dialog')).toBeVisible()
        await expect(page.getByRole('switch', { name: '含区间回填', exact: true, includeHidden: true })).toBeChecked()
        await expect(page.locator('.history-detail-dialog').getByRole('link', { name: `${candidate.name} ${candidate.code}`, exact: true })).toBeVisible()
        assert.equal(await page.locator('.history-detail-dialog').evaluate(element => element.contains(document.activeElement)), true, 'Returned focus must belong to the innermost history dialog')
        await page.screenshot({ path: path.join(output, `${source}-${width}-restored-detail.png`) })
        await page.keyboard.press('Escape')
        await expect(page.locator('.history-detail-dialog')).toHaveCount(0)
        await expect(page.locator('.screen-history-dialog')).toBeVisible()
      } else {
        await expect(page.locator('.cand__title')).toContainText(candidate.name)
        await expect(page.getByRole('switch', { name: '包含历史回填', exact: true, includeHidden: true })).toBeChecked()
        await expect(page.locator('.cand__title').getByRole('link', { name: candidate.name, exact: true })).toBeFocused()
      }
      await page.screenshot({ path: path.join(output, `${source}-${width}-restored.png`) })
      assert.deepEqual(result.errors, [])
      assert.deepEqual(result.gaps, [])
      assert.deepEqual(result.writes, [])
      result.ok = true
    } catch (error) {
      result.ok = false
      result.error = String(error)
      await page.screenshot({ path: path.join(output, `${source}-${width}-failed.png`) })
    } finally {
      await context.close()
      console.log(JSON.stringify(result))
    }
  }
} finally { await browser.close() }
await fs.writeFile(path.join(output, baseline ? 'baseline.json' : 'results.json'), JSON.stringify(results, null, 2))
assert.ok(results.every(result => result.ok), 'Archive overlay regression failed')

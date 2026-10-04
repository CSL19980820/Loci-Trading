/** Candidate-to-quote navigation keeps the batch sidebar; APIs are entirely local fixtures. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

const base = process.env.STOCK_NAV_BASE || 'http://127.0.0.1:5198'
const output = process.env.STOCK_NAV_OUT || path.resolve('../.local/experience-speed-20261001/ui')
const candidates = Array.from({ length: 48 }, (_, index) => {
  const code = String(index + 1).padStart(6, '0')
  return { id: `navigation-${code}`, code, name: `导航验收${index + 1}`, date: '2026-09-29',
    score: 90, decision: '精选', timing: 'next_open', reason: `股票 ${code} 的独立选股记录`,
    strategy_slug: `navigation-${code}`, rule_version: `导航验收战法 ${code}`,
    source: 'api:screen', created_at: '2026-09-29 15:30:00', pool_id: `navigation-${code}@2026-09-29` }
})
const strategies = candidates.map(item => ({ slug: item.strategy_slug, name: item.rule_version,
  description: '隔离浏览器验收', params: {}, required_fields: [], min_bars: 20, entry_timing: 'next_open' }))
const bars = Array.from({ length: 92 }, (_, index) => ({
  trade_date: new Date(Date.UTC(2026, 6, 1 + index)).toISOString().slice(0, 10),
  open: 10 + index / 100, close: 10.05 + index / 100, high: 10.1 + index / 100,
  low: 9.9 + index / 100, volume: 100000, amount: 1000000, turnover: 0.01,
}))

async function periodIs(archive, label) {
  await expect(archive.getByRole('button', { name: label, exact: true })).toHaveAttribute('aria-pressed', 'true')
}

async function openFootprint(page, archive) {
  await archive.getByRole('button', { name: '战法足迹', exact: true }).click()
  await expect(page.locator('.archive-footprint-dialog')).toBeVisible()
  return page.locator('.archive-footprint-dialog')
}

await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
console.log('Archive navigation browser ready')
const results = []
try {
  for (const width of [1440, 390]) {
    const mobile = width < 768
    const context = await browser.newContext({ viewport: { width, height: mobile ? 844 : 960 }, serviceWorkers: 'block', reducedMotion: 'reduce' })
    const page = await context.newPage()
    page.setDefaultTimeout(12000)
    const result = { width, candidateCount: candidates.length, errors: [], gaps: [], writes: [], calls: [], checks: [] }
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
      if (url.pathname === '/api/strategies') fixture = { body: strategies }
      else if (url.pathname === '/api/jobs') fixture = { body: [] }
      else if (url.pathname === '/api/candidates/list') {
        const code = url.searchParams.get('code')
        const candidate = candidates.find(item => item.code === code)
        if (candidate) {
          result.calls.push({ kind: 'footprints', code, phase: 'requested' })
          const delay = code === '000047' ? 1000 : code === '000048' ? 180 : 0
          if (delay) await new Promise(resolve => setTimeout(resolve, delay))
          fixture = { body: [candidate, { ...candidate, id: `${candidate.id}-earlier`, date: '2026-09-23', pool_id: `${candidate.strategy_slug}@2026-09-23` }] }
          result.calls.push({ kind: 'footprints', code, phase: 'replied' })
        } else fixture = { body: candidates }
      } else if (url.pathname.startsWith('/api/candidates/navigation-')) {
        fixture = { body: { ...candidates.find(item => item.id === url.pathname.split('/').at(-1)), evidence: { 验收: '仅浏览器夹具' } } }
      } else if (url.pathname.startsWith('/api/market/quotes/')) {
        const code = url.pathname.split('/').at(-1)
        fixture = { body: { code, name: candidates.find(item => item.code === code)?.name,
          adjust: url.searchParams.get('adjust') || 'qfq', rows: bars.length, total_rows: bars.length, bars } }
      } else fixture = routeFixture(url, 'pool')
      if (!fixture) result.gaps.push(url.pathname)
      return route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? {}) })
    })

    try {
      console.log(`Archive navigation ${width}: loading pool`)
      await page.goto(`${base}/pool`, { waitUntil: 'networkidle', timeout: 45000 })
      console.log(`Archive navigation ${width}: opening archive`)
      if (mobile) await page.getByRole('button', { name: '查看导航验收1候选详情', exact: true }).click()
      else await page.locator('.pool-stock-table tbody tr').first().getByText(candidates[0].date, { exact: true }).click()
      await expect(page.locator('.cand__title')).toContainText(candidates[0].name)
      await page.locator('.cand__title').getByRole('link', { name: candidates[0].name, exact: true }).click()
      await expect(page).toHaveURL(/\/archive\/000001\?date=2026-09-29$/)
      const archive = page.locator('.archive-overlay')
      await expect(archive).toBeVisible()
      const identity = mobile ? '.mobile-stock-name h1' : '.sw-name'
      await expect(archive.locator(identity)).toHaveText(candidates[0].name)
      result.checks.push('real pool detail link opens a 48-stock archive batch')
      console.log(`Archive navigation ${width}: testing stock and date changes`)

      await archive.getByRole('button', { name: '周K', exact: true }).click()
      await periodIs(archive, '周K')
      await archive.getByRole('button', { name: 'KDJ', exact: true }).click()
      if (mobile) {
        await archive.getByRole('combobox', { name: '复权方式', exact: true }).click()
        await page.getByRole('option', { name: '不复权', exact: true }).click()
      } else await archive.getByRole('button', { name: '不复权', exact: true }).click()

      let beforeScroll = null
      if (mobile) {
        await archive.getByRole('button', { name: '本批列表', exact: true }).click()
        await page.locator('.batch-dock-sheet .batch-dock__row').filter({ hasText: '000046' }).click()
        await expect(page.locator('.batch-dock-sheet')).toHaveCount(0)
      } else {
        const list = archive.locator('.batch-dock__list')
        beforeScroll = await list.evaluate(element => {
          element.scrollTop = element.scrollHeight - element.clientHeight
          element.__navigationList = true
          return element.scrollTop
        })
        assert.ok(beforeScroll > 300, `Candidate batch must overflow: ${beforeScroll}`)
        await list.locator('.batch-dock__row').filter({ hasText: '000046' }).click()
      }
      await expect(page).toHaveURL(/\/archive\/000046/)
      await expect(archive.locator(identity)).toHaveText(candidates[45].name)
      await periodIs(archive, '周K')
      await expect(archive.getByRole('button', { name: 'KDJ', exact: true })).toHaveAttribute('aria-pressed', 'true')
      if (mobile) await expect(archive.getByRole('combobox', { name: '复权方式', exact: true })).toContainText('不复权')
      else await expect(archive.getByRole('button', { name: '不复权', exact: true })).toHaveAttribute('aria-pressed', 'true')
      if (!mobile) {
        result.scroll = { before: beforeScroll, afterStock: await archive.locator('.batch-dock__list').evaluate(element => element.scrollTop) }
        assert.ok(Math.abs(result.scroll.afterStock - beforeScroll) <= 1, JSON.stringify(result.scroll))
        assert.equal(await archive.locator('.batch-dock__list').evaluate(element => element.__navigationList), true, 'Sidebar DOM must survive stock navigation')
      }
      result.checks.push('stock change preserves period, indicator and adjustment', mobile ? 'mobile batch drawer selects a stock and closes' : 'desktop stock change preserves sidebar DOM and scroll position')

      await archive.getByRole('button', { name: '日K', exact: true }).click()
      const footprint = await openFootprint(page, archive)
      await expect(footprint.locator('.fp__dot')).toHaveCount(2)
      await footprint.getByRole('button', { name: new RegExp(`${strategies[45].name} 2026-09-23 精选`) }).click()
      await expect(page).toHaveURL(/\/archive\/000046\?date=2026-09-23$/)
      await expect(page.locator('.archive-footprint-dialog')).toHaveCount(0)
      await periodIs(archive, '日K')
      await expect(archive.getByRole('button', { name: 'KDJ', exact: true })).toHaveAttribute('aria-pressed', 'true')
      if (!mobile) {
        result.scroll.afterDate = await archive.locator('.batch-dock__list').evaluate(element => element.scrollTop)
        assert.ok(Math.abs(result.scroll.afterDate - beforeScroll) <= 1, JSON.stringify(result.scroll))
      }
      result.checks.push('signal date updates the same stock without resetting batch position or settings')
      await page.screenshot({ path: path.join(output, `archive-navigation-${width}-date.png`) })
      console.log(`Archive navigation ${width}: testing delayed signals`)

      await archive.getByRole('button', { name: '月K', exact: true }).click()
      if (mobile) await archive.getByRole('button', { name: '下一只', exact: true }).click()
      else await archive.locator('.batch-dock__row').filter({ hasText: '000047' }).click()
      await expect(page).toHaveURL(/\/archive\/000047/)
      await expect.poll(() => result.calls.some(call => call.code === '000047' && call.phase === 'requested')).toBe(true)
      if (mobile) await archive.getByRole('button', { name: '下一只', exact: true }).click()
      else await archive.locator('.batch-dock__row').filter({ hasText: '000048' }).click()
      await expect(page).toHaveURL(/\/archive\/000048/)
      await periodIs(archive, '月K')
      await page.evaluate(() => {
        window.__navigationSignals = { wrong: [], observed: [] }
        const sample = () => {
          const labels = [...document.querySelectorAll('.archive-footprint-dialog .fp__dot')].map(element => element.getAttribute('aria-label'))
          window.__navigationSignals.observed.push(...labels)
          window.__navigationSignals.wrong.push(...labels.filter(label => !label.includes('000048')))
        }
        window.__navigationSignalObserver = new MutationObserver(sample)
        window.__navigationSignalObserver.observe(document.body, { childList: true, subtree: true, attributes: true })
        sample()
      })
      const currentFootprint = await openFootprint(page, archive)
      await expect(currentFootprint.locator('.fp__dot')).toHaveCount(2)
      await expect(currentFootprint.locator('.fp__dot').first()).toHaveAttribute('aria-label', /000048/)
      await expect.poll(() => result.calls.some(call => call.code === '000047' && call.phase === 'replied')).toBe(true)
      await page.waitForLoadState('networkidle')
      result.signals = await page.evaluate(() => {
        window.__navigationSignalObserver.disconnect()
        return { wrong: [...new Set(window.__navigationSignals.wrong)], observed: [...new Set(window.__navigationSignals.observed)] }
      })
      assert.deepEqual(result.signals.wrong, [])
      assert.equal(result.signals.observed.length, 2)
      await expect(currentFootprint.locator('.fp__dot').first()).toHaveAttribute('aria-label', /000048/)
      result.checks.push('late response from stock 47 never renders after switching to stock 48', 'monthly period survives rapid stock changes')
      await page.keyboard.press('Escape')
      await expect(page.locator('.archive-footprint-dialog')).toHaveCount(0)
      await page.screenshot({ path: path.join(output, `archive-navigation-${width}-final.png`) })

      if (mobile) {
        await archive.getByRole('button', { name: '上一只', exact: true }).click()
        await expect(page).toHaveURL(/\/archive\/000047/)
        await periodIs(archive, '月K')
        result.checks.push('mobile previous-stock navigation preserves settings')
      }
      assert.deepEqual(result.errors, [])
      assert.deepEqual(result.gaps, [])
      assert.deepEqual(result.writes, [])
      result.ok = true
    } catch (error) {
      result.ok = false
      result.error = String(error)
      await page.screenshot({ path: path.join(output, `archive-navigation-${width}-failed.png`) })
    } finally {
      await context.close()
      console.log(JSON.stringify(result))
    }
  }
} finally { await browser.close() }
await fs.writeFile(path.join(output, 'archive-navigation-results.json'), JSON.stringify(results, null, 2))
assert.ok(results.every(result => result.ok), 'Archive navigation regression failed')

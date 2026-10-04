/** Retired strategy links and record choices; all APIs use isolated fixtures. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

const base = process.env.STRATEGY_RETIRE_BASE || 'http://127.0.0.1:5198'
const output = process.env.STRATEGY_RETIRE_OUT || path.resolve('../.local/tail-micro-right-retirement-20261001')
const retired = 'tail-micro-right-v1'
const strategies = [
  { slug: 'qianlong-close-v3', name: '潜龙出海（V3.2）' },
  { slug: 'sanyuan-tail-v1', name: '三源尾盘共振（15:30）' },
  { slug: 'yangshi-tail-v1', name: '杨氏尾盘选股（15:30）' },
].map(strategy => ({ ...strategy, params: {}, required_fields: [], min_bars: 20, entry_timing: 'next_open', source_kind: 'builtin' }))
const errors = [], gaps = [], writes = []
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, serviceWorkers: 'block', reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(String(error)))
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.origin !== new URL(base).origin) return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      writes.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({ status: 405, contentType: 'application/json', body: '{}' })
    }
    let fixture
    if (url.pathname === '/api/strategies') fixture = { body: strategies }
    else if (url.pathname === '/api/screen/history') fixture = { body: { strategy: url.searchParams.get('strategy'), total: 0, dates: [], by_date: {} } }
    else fixture = routeFixture(url, 'pool')
    if (!fixture) gaps.push(url.pathname)
    return route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? {}) })
  })
  await page.goto(`${base}/screen-history?select=engine:${retired}`, { waitUntil: 'networkidle', timeout: 45000 })
  await expect(page.locator('.screen-catalog .is-selected')).toBeVisible()
  assert.notEqual(new URL(page.url()).searchParams.get('select'), `engine:${retired}`)
  await expect(page.locator('.screen-catalog')).not.toContainText('尾盘微右侧')
  await page.goto(`${base}/quant`, { waitUntil: 'networkidle' })
  await expect(page.locator('[aria-label="查看杨氏尾盘选股（15:30）配置"]')).toBeVisible()
  await expect(page.getByText('尾盘微右侧', { exact: false })).toHaveCount(0)
  await page.screenshot({ path: path.join(output, 'strategy-catalog.png') })

  await page.goto(`${base}/e2e/fixtures/feature-foundation.html?view=strategy-record`, { waitUntil: 'networkidle' })
  const record = page.getByRole('dialog', { name: '写复盘', exact: true })
  await expect(record).toBeVisible()
  await record.getByRole('combobox', { name: /^战法/ }).click()
  await expect(page.getByRole('option', { name: /尾盘微右侧/ })).toHaveCount(0)
  const yangshi = page.getByRole('option', { name: '杨氏尾盘选股（15:30）', exact: true })
  await expect(yangshi).toBeVisible()
  await page.screenshot({ path: path.join(output, 'record-strategy-options.png') })
  await yangshi.click()
  await expect(record.getByRole('combobox', { name: /^战法/ })).toHaveText('杨氏尾盘选股（15:30）')
  assert.deepEqual(errors, [])
  assert.deepEqual(gaps, [])
  assert.deepEqual(writes, [])
  const receipt = { passed: true, fixture: true, retired,
    checks: ['retired deep-link falls back to an available strategy', 'strategy catalog has no retired entry', 'review strategy dropdown has no retired option', 'Yangshi choice remains usable'], errors, gaps, writes }
  await fs.writeFile(path.join(output, 'verification.json'), JSON.stringify(receipt, null, 2))
  console.log(JSON.stringify(receipt))
  await context.close()
} finally { await browser.close() }

/** Candidate list stays light; full evidence loads on demand with retry and race protection. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

const base = process.env.CANDIDATE_DETAIL_BASE || 'http://127.0.0.1:5195'
const out = process.env.CANDIDATE_DETAIL_OUT || path.resolve('../.local/candidate-detail-regression')
const strategy = { slug: 'candidate-detail-fixture', name: '候选证据验收战法', params: {}, required_fields: [], min_bars: 20 }
const live = { id: 'fixture-live-detail', date: '2026-09-30', code: '000001', name: '当日验收标的', score: 90, decision: '精选', timing: '收盘', reason: '当日候选验收理由', rule_version: strategy.name, strategy_slug: strategy.slug, pool_id: `${strategy.slug}@2026-09-30`, source: 'api:screen', created_at: '2026-09-30 15:30:00' }
const history = { ...live, id: 'fixture-history-detail', date: '2026-09-29', code: '000002', name: '回填验收标的', reason: '历史回填验收理由', pool_id: `${strategy.slug}@2026-09-29`, source: 'api:screen_backfill' }
const calls = [], errors = [], gaps = [], writes = []
let failHistory = true
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, serviceWorkers: 'block', reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.setDefaultTimeout(12000)
  page.on('pageerror', error => errors.push(String(error)))
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.origin !== new URL(base).origin) return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (request.method() !== 'GET') {
      writes.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({ status: 405, body: '{}' })
    }
    let fixture
    if (url.pathname === '/api/candidates/list') {
      calls.push({ kind: 'list', params: Object.fromEntries(url.searchParams) })
      assert.equal(url.searchParams.get('slim'), 'true')
      fixture = { body: url.searchParams.get('code') ? [] : url.searchParams.get('include_backfill') === 'true' ? [live, history] : [live] }
    } else if (url.pathname === `/api/candidates/${history.id}`) {
      calls.push({ kind: 'detail', id: history.id })
      await new Promise(resolve => setTimeout(resolve, 600))
      fixture = failHistory ? { status: 400, body: { detail: '隔离夹具证据暂时不可用' } } : { body: { ...history, evidence: { 验收证据: '历史证据保留' }, effective_params: { window: 20 } } }
    } else if (url.pathname === `/api/candidates/${live.id}`) {
      calls.push({ kind: 'detail', id: live.id })
      fixture = { body: { ...live, evidence: { 验收证据: '当日证据保留' } } }
    } else if (url.pathname === '/api/strategies') fixture = { body: [strategy] }
    else if (url.pathname === '/api/jobs') fixture = { body: [] }
    else if (url.pathname.startsWith('/api/market/quotes/')) fixture = { body: { code: url.pathname.split('/').at(-1), adjust: 'qfq', bars: [], rows: 0 } }
    else fixture = routeFixture(url, 'pool')
    if (!fixture) gaps.push(url.pathname)
    await route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? {}) })
  })
  await page.goto(`${base}/pool`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('row').filter({ hasText: live.reason })).toBeVisible()
  assert.equal(calls.filter(call => call.kind === 'detail').length, 0)
  await page.getByRole('switch', { name: '包含历史回填', exact: true }).click()
  await page.getByRole('row').filter({ hasText: history.reason }).click()
  await expect(page.getByLabel('加载候选证据')).toBeVisible()
  await expect(page.getByRole('button', { name: '重试证据', exact: true })).toBeVisible()
  // Start a delayed retry, then immediately choose a different candidate.
  failHistory = false
  await page.getByRole('button', { name: '重试证据', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.getByRole('row').filter({ hasText: live.reason }).click()
  await page.getByRole('button', { name: /^证据/ }).click()
  await expect(page.getByText('当日证据保留', { exact: true })).toBeVisible()
  await page.waitForLoadState('networkidle')
  await expect(page.getByText('历史证据保留', { exact: true })).toHaveCount(0)
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.getByRole('row').filter({ hasText: history.reason }).click()
  await page.getByRole('button', { name: /^证据/ }).click()
  await expect(page.getByText('历史证据保留', { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(out, 'backfill-evidence.png') })
  assert.deepEqual(errors, [])
  assert.deepEqual(gaps, [])
  assert.deepEqual(writes, [])
  const result = { passed: true, checks: ['slim list', 'no prefetch evidence', 'history toggle', 'loading state', 'error retry', 'late response isolation', 'full historical evidence'], calls, errors, gaps, writes }
  await fs.writeFile(path.join(out, 'verification.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} finally { await browser.close() }

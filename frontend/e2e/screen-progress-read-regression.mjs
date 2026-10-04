/** Shared polling and lazy result recovery against isolated API fixtures, desktop only. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

const base = process.env.SCREEN_READ_BASE || 'http://127.0.0.1:5198'
const output = process.env.SCREEN_READ_OUT || path.resolve('../.local/architecture-read-20261001')
const strategies = Array.from({ length: 64 }, (_, index) => ({ slug: `read-${String(index).padStart(2, '0')}`,
  name: `公共读取验收战法${String(index).padStart(2, '0')}`, params: {}, required_fields: [], min_bars: 20, entry_timing: 'next_open' }))
const picks = Array.from({ length: 200 }, (_, index) => ({ code: String(index + 1).padStart(6, '0'), name: `结果验收${index + 1}`,
  open: 10, close: 11, factors: Object.fromEntries(Array.from({ length: 25 }, (_, factor) => [`factor_${factor}`, index + factor])) }))
const bodyFor = strategy => ({ strategy, strategy_revision: 'fixture-1', trade_date: '2026-10-01', entry_timing: 'next_open',
  universe_size: 5000, elapsed_seconds: 12, params: {}, effective_params: {}, picks, watch_picks: [], recorded: { written: picks.length } })
const slotFor = strategy => ({ strategy, status: 'done', phase: 'done', percent: 100, message: '选股已完成', trade_date: '2026-10-01',
  log: ['开始选股', '完成选股'], error: '', started_at: 1, updated_at: 2, result_omitted: true })
const calls = [], errors = [], gaps = [], writes = []
let stage = 'cold', progressRound = 0
const slotsFor = () => Object.fromEntries(strategies.map((strategy, index) => [strategy.slug,
  stage === 'polling' && index === 1 ? { ...slotFor(strategy.slug), status: 'running', phase: 'scan', percent: 20 + progressRound,
    message: '扫描候选', updated_at: 2 + progressRound } : slotFor(strategy.slug)]))

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
    if (url.pathname === '/api/screen/run') {
      const strategy = url.searchParams.get('strategy'), view = url.searchParams.get('view')
      if (strategy) {
        await new Promise(resolve => setTimeout(resolve, 150))
        fixture = { body: { ...slotFor(strategy), result_omitted: false, result: bodyFor(strategy) } }
      } else {
        progressRound++
        const slots = slotsFor()
        fixture = { body: { ...slots['read-00'], runs: slots, running_strategies: stage === 'polling' ? ['read-01'] : [], max_concurrent_runs: 4 } }
        // App and ScreenHistoryView overlap during initial mounting.
        await new Promise(resolve => setTimeout(resolve, 100))
      }
      calls.push({ stage, strategy, view, bytes: Buffer.byteLength(JSON.stringify(fixture.body)) })
    } else if (url.pathname === '/api/strategies') fixture = { body: strategies }
    else if (url.pathname === '/api/screen/history') fixture = { body: { strategy: url.searchParams.get('strategy'), total: 0, dates: [], by_date: {} } }
    else fixture = routeFixture(url, 'pool')
    if (!fixture) gaps.push(url.pathname)
    return route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? {}) })
  })

  await page.goto(`${base}/pool`, { waitUntil: 'networkidle', timeout: 45000 })
  if (!calls.length) {
    console.log(JSON.stringify({ url: page.url(), errors, gaps, writes, calls }))
    await page.screenshot({ path: path.join(output, 'frontend-screen-progress-failed.png') })
  }
  assert.equal(calls.filter(call => call.stage === 'cold').length, 1, 'App cold startup should make one light request')
  assert.equal(calls[0].view, 'progress')
  assert.equal(calls.filter(call => call.strategy).length, 0, '64 historical completed runs must not trigger full result fan-out')

  stage = 'polling'
  progressRound = 0
  await page.goto(`${base}/screen-history?select=engine%3Aread-00`, { waitUntil: 'domcontentloaded', timeout: 45000 })
  await expect(page.locator('.run-status__name')).toHaveText(strategies[0].name)
  await expect(page.locator('.pick-table tbody tr')).toHaveCount(200)
  await expect(page.locator('.run-results__title')).toContainText('已入库 200')
  await expect.poll(() => calls.filter(call => call.stage === 'polling' && !call.strategy).length, { timeout: 10000 }).toBeGreaterThanOrEqual(4)
  assert.equal(calls.filter(call => call.strategy === 'read-00').length, 1, 'Selected historical result is fetched exactly once')
  assert.equal(calls.filter(call => call.strategy && call.strategy !== 'read-00').length, 0, 'Unselected completed runs stay metadata-only')
  assert.equal(calls.filter(call => !call.strategy && call.view !== 'progress').length, 0)
  await expect(page.locator('.run-results__title')).toContainText('已入库 200')
  await page.screenshot({ path: path.join(output, 'frontend-screen-progress.png') })

  const progressReads = calls.filter(call => call.stage === 'polling' && !call.strategy)
  const fullSlots = Object.fromEntries(strategies.map(item => [item.slug, { ...slotFor(item.slug), result_omitted: false, result: bodyFor(item.slug) }]))
  const oldAggregateBytes = Buffer.byteLength(JSON.stringify({ ...fullSlots['read-00'], runs: fullSlots, running_strategies: ['read-01'], max_concurrent_runs: 4 }))
  const transferred = calls.filter(call => call.stage === 'polling').reduce((total, call) => total + call.bytes, 0)
  const formerTransferForSamePolls = oldAggregateBytes * progressReads.length
  assert.deepEqual(errors, [])
  assert.deepEqual(gaps, [])
  assert.deepEqual(writes, [])
  const verification = { passed: true, fixture: true, storedCompletedSlots: 64, selectedPicks: 200,
    checks: ['cold App progress only', 'no historical result fan-out', 'selected result recovered after reload', 'one full result read during repeated progress', 'unselected completed slots metadata only'],
    progressReads: progressReads.length, fullResultReads: calls.filter(call => call.strategy).length,
    bytes: { progressPerRead: progressReads[0].bytes, selectedFull: calls.find(call => call.strategy).bytes,
      oldAggregatePerRead: oldAggregateBytes, transferred, formerTransferForSamePolls,
      reductionPercent: Number(((1 - transferred / formerTransferForSamePolls) * 100).toFixed(2)) }, calls, errors, gaps, writes }
  await fs.writeFile(path.join(output, 'frontend-screen-read.json'), JSON.stringify(verification, null, 2))
  console.log(JSON.stringify(verification))
  await context.close()
} finally { await browser.close() }

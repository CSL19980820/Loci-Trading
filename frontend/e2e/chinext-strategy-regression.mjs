/** Real catalog and historical financial results replayed through isolated API routes. */
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

const base = process.env.CHINEXT_UI_BASE || 'http://127.0.0.1:5193'
const inputs = process.env.CHINEXT_UI_INPUT || path.resolve('../.local/chinext-review-20261003')
const output = process.env.CHINEXT_UI_OUT || path.join(inputs, 'ui')
const slugs = ['contraction-rebreakout-v1', 'impulse-inside-breakout-v1']
const viewports = [{ name: 'desktop', width: 1440, height: 960 },
  { name: 'mobile390', width: 390, height: 844 }, { name: 'mobile320', width: 320, height: 780 }]
const catalogBytes = await fs.readFile(path.join(inputs, 'strategy-catalog.json'), 'utf8')
const replayBytes = await fs.readFile(path.join(inputs, 'ui-api-replay.json'), 'utf8')
const catalog = JSON.parse(catalogBytes)
const replay = JSON.parse(replayBytes)
const strategies = Object.fromEntries(slugs.map(slug => [slug, catalog.find(row => row.slug === slug)]))
for (const slug of slugs) {
  assert.ok(strategies[slug], `Actual catalog is missing ${slug}`)
  assert.deepEqual(strategies[slug].default_universe.boards, ['chi_next'])
  assert.equal(strategies[slug].backtest_config.mode, 'trade')
  assert.equal(replay.backtests[slug].strategy, slug)
  assert.equal(replay.screens[slug].strategy, slug)
  assert.ok(replay.screens[slug].picks.length <= 2)
  if (slug === slugs[0]) {
    assert.deepEqual(replay.screens[slug].picks.map(pick => pick.code), ['300804', '300413'],
      'Actual calibrated 9/29 Top 2 must be GuangKang and Mango')
    assert.deepEqual(replay.screens[slug].picks.map(pick => pick.factors.score), [72.8576, 72.4752])
  }
  for (const pick of replay.screens[slug].picks) {
    assert.match(pick.code, /^(300|301)\d{3}$/)
    assert.ok(Number.isFinite(pick.factors.score))
  }
}

const errors = [], gaps = [], unexpectedWrites = [], backtestRequests = [], checks = []
const staticFailures = [], staticAssets = new Set()
const hash = text => crypto.createHash('sha256').update(text).digest('hex')
const ratioText = value => value == null ? '—' : Number(value).toFixed(2)
const percentText = value => value == null ? '—' : `${Number(value).toFixed(2)}%`
await fs.mkdir(output, { recursive: true })

function slot(slug) {
  const result = replay.screens[slug]
  return { status: 'done', phase: 'done', percent: 100, message: '实际历史结果隔离回放',
    strategy: slug, trade_date: result.trade_date, log: [], result, error: '',
    started_at: 1, updated_at: 2, cancel_requested: false }
}

async function screenshot(page, name) {
  await page.screenshot({ path: path.join(output, `${name}.png`), animations: 'disabled' })
}

async function assertNoPageOverflow(page, description, selectors = []) {
  const result = await page.evaluate(items => {
    const outside = []
    for (const selector of items) {
      for (const element of document.querySelectorAll(selector)) {
        const rect = element.getBoundingClientRect()
        if (rect.width && (rect.left < -1 || rect.right > innerWidth + 1)) {
          outside.push({ selector, text: element.textContent?.trim(), left: rect.left, right: rect.right })
        }
      }
    }
    return { width: innerWidth, documentWidth: document.documentElement.scrollWidth, outside }
  }, selectors)
  assert.ok(result.documentWidth <= result.width + 1, `${description}: document overflow ${JSON.stringify(result)}`)
  assert.deepEqual(result.outside, [], `${description}: visible content extends outside viewport`)
}

const browser = await chromium.launch({ headless: true })
let activePage
let completed = false
try {
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport, serviceWorkers: 'block', reducedMotion: 'reduce' })
    const page = await context.newPage()
    activePage = page
    page.on('pageerror', error => errors.push(`${viewport.name}: ${error}`))
    page.on('response', response => {
      const url = new URL(response.url())
      if (url.origin !== new URL(base).origin || url.pathname.startsWith('/api/')) return
      if (response.status() >= 400) staticFailures.push(`${response.status()} ${url.pathname}`)
      const resourceType = response.request().resourceType(), contentType = response.headers()['content-type'] || ''
      if (resourceType === 'script' && !/javascript/.test(contentType)) staticFailures.push(`script MIME ${contentType} ${url.pathname}`)
      if (resourceType === 'stylesheet' && !/text\/css/.test(contentType)) staticFailures.push(`stylesheet MIME ${contentType} ${url.pathname}`)
      if (['script', 'stylesheet', 'font', 'image'].includes(resourceType)) staticAssets.add(url.pathname)
    })
    page.on('requestfailed', request => {
      const url = new URL(request.url())
      if (url.origin === new URL(base).origin && !url.pathname.startsWith('/api/')) {
        staticFailures.push(`${request.failure()?.errorText || 'failed'} ${url.pathname}`)
      }
    })
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const fulfill = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        if (request.method() === 'POST' && url.pathname === '/api/backtest') {
          const payload = request.postDataJSON()
          backtestRequests.push({ viewport: viewport.name, payload })
          const result = replay.backtests[payload.strategy]
          if (result) return fulfill(result)
        }
        unexpectedWrites.push(`${request.method()} ${url.pathname}`)
        return route.fulfill({ status: 405, contentType: 'application/json', body: '{}' })
      }
      if (url.pathname === '/api/strategies') return fulfill(catalog)
      if (/^\/api\/strategies\/[^/]+\/job$/.test(url.pathname)) return fulfill({ bound: false })
      if (/^\/api\/strategies\/[^/]+\/versions$/.test(url.pathname)) {
        const slug = decodeURIComponent(url.pathname.split('/')[3])
        return fulfill(strategies[slug]?.version_history || [])
      }
      if (url.pathname === '/api/screen/history') {
        return fulfill({ strategy: url.searchParams.get('strategy'), total: 0, dates: [], by_date: {} })
      }
      if (url.pathname === '/api/screen/run') {
        const selected = url.searchParams.get('strategy')
        if (selected && replay.screens[selected]) return fulfill(slot(selected))
        return fulfill({ ...slot(slugs[0]), runs: Object.fromEntries(slugs.map(slug => [slug, slot(slug)])),
          running_strategies: [], max_concurrent_runs: 2 })
      }
      const fixture = routeFixture(url, 'pool')
      if (!fixture) gaps.push(url.pathname)
      return route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json',
        body: JSON.stringify(fixture?.body ?? {}) })
    })

    for (const slug of slugs) {
      const strategy = strategies[slug], config = strategy.backtest_config
      await page.goto(`${base}/quant`, { waitUntil: 'networkidle', timeout: 45000 })
      await page.locator(`[aria-label="查看${strategy.name}配置"]`).click()
      const dialog = page.getByRole('dialog', { name: strategy.name, exact: true })
      await expect(dialog).toBeVisible()
      await expect(dialog.locator('.ov__desc')).toContainText('创业板')
      const instructions = dialog.getByRole('region', { name: '买入说明' })
      await expect(instructions).toContainText('每日最多')
      for (const weight of slug === slugs[0] ? ['10日动量 40 分', '回调缩量 15 分', '回调深度 15 分', '再突破放量 10 分', '收盘位置 20 分', '已知案例校准']
        : ['整理收敛 30 分', '三日缩量 25 分', '突破放量 25 分', '收盘位置 20 分']) {
        await expect(instructions).toContainText(weight)
      }
      const metrics = dialog.locator('.sd__metrics')
      await expect(metrics.locator('.sd__metric')).toHaveCount(5)
      for (const [label, value] of [['胜率', percentText(strategy.backtest_metrics.win_rate)],
        ['盈亏比', ratioText(strategy.backtest_metrics.payoff_ratio)],
        ['利润因子 PF', ratioText(strategy.backtest_metrics.profit_factor)]]) {
        await expect(metrics.locator('.sd__metric').filter({ has: page.locator('dt', { hasText: new RegExp(`^${label}$`) }) }).locator('dd')).toHaveText(value)
      }
      await assertNoPageOverflow(page, `${viewport.name}/${slug}/detail`, ['.sd__metric', '.sd__title'])
      await screenshot(page, `${viewport.name}-${slug}-detail`)
      const caliber = dialog.getByRole('region', { name: '回测口径' })
      await caliber.scrollIntoViewIfNeeded()
      for (const text of [config.start, config.end, '单边佣金(bps)', '卖出印花税(bps)', '单边滑点(bps)', '持有期口径']) {
        await expect(caliber).toContainText(text)
      }
      await screenshot(page, `${viewport.name}-${slug}-caliber`)
      await dialog.getByRole('tab', { name: '调度与范围', exact: true }).click()
      await expect(dialog.getByRole('button', { name: '创业板', exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const name of ['主板', '科创板', '北交所']) {
        await expect(dialog.getByRole('button', { name, exact: true })).toHaveAttribute('aria-pressed', 'false')
      }
      await assertNoPageOverflow(page, `${viewport.name}/${slug}/scope`, ['.sd__foot > button'])
      await screenshot(page, `${viewport.name}-${slug}-scope`)
      await dialog.locator('.sd__foot').getByRole('button', { name: '关闭', exact: true }).click()

      await page.goto(`${base}/quant?tab=backtest`, { waitUntil: 'networkidle' })
      await page.getByRole('combobox', { name: '选择战法', exact: true }).click()
      await page.getByRole('option', { name: strategy.name, exact: true }).click()
      const panel = page.getByRole('region', { name: '战法回测', exact: true })
      await expect(panel.getByText('成交回测', { exact: true })).toHaveAttribute('data-state', 'on')
      await expect(panel.getByRole('spinbutton', { name: '持有日', exact: true })).toHaveValue(String(config.hold_days))
      await panel.getByRole('button', { name: '成本参数', exact: true }).click()
      for (const [label, key] of [['佣金 bps', 'commission_bps'], ['印花税 bps', 'stamp_duty_bps'], ['滑点 bps', 'slippage_bps']]) {
        await expect(panel.getByRole('spinbutton', { name: label, exact: true })).toHaveValue(String(config[key]))
      }
      const before = backtestRequests.length
      await panel.getByRole('button', { name: '跑回测', exact: true }).click()
      await expect.poll(() => backtestRequests.length).toBe(before + 1)
      const payload = backtestRequests.at(-1).payload
      for (const [key, value] of Object.entries({ strategy: slug, mode: 'trade', start: config.start, end: config.end,
        hold_days: config.hold_days, commission_bps: config.commission_bps,
        stamp_duty_bps: config.stamp_duty_bps, slippage_bps: config.slippage_bps })) {
        assert.equal(payload[key], value, `${slug}: default template ${key}`)
      }
      await expect(panel.locator('.tr-hero')).toBeVisible()
      await expect(panel.locator('.tr-hero .stat-card')).toHaveCount(7)
      for (const label of ['盈亏比', '利润因子 PF', '平均持仓']) await expect(panel.locator('.tr-hero')).toContainText(label)
      await expect(panel.locator('.tr-hero')).toContainText(ratioText(replay.backtests[slug].metrics.payoff_ratio))
      await expect(panel.locator('.tr-hero')).toContainText(ratioText(replay.backtests[slug].metrics.profit_factor))
      await panel.locator('.tr-hero').scrollIntoViewIfNeeded()
      await assertNoPageOverflow(page, `${viewport.name}/${slug}/backtest`, ['.tr-hero .stat-card'])
      await screenshot(page, `${viewport.name}-${slug}-backtest`)

      await page.goto(`${base}/screen-history?select=engine:${slug}`, { waitUntil: 'networkidle' })
      const picks = page.getByRole('region', { name: '正式精选', exact: true })
      await expect(picks).toBeVisible()
      await expect(picks.locator(viewport.width > 640 ? 'tbody tr' : '.pick-card')).toHaveCount(replay.screens[slug].picks.length)
      if (!replay.screens[slug].picks.length) await expect(picks).toContainText('该日无正式精选')
      for (const pick of replay.screens[slug].picks) {
        await expect(picks).toContainText(pick.name || pick.code)
        await expect(picks).toContainText(Number(pick.factors.score).toFixed(2))
      }
      await picks.scrollIntoViewIfNeeded()
      await assertNoPageOverflow(page, `${viewport.name}/${slug}/screen`, [viewport.width > 640 ? '.pick-table' : '.pick-card'])
      await screenshot(page, `${viewport.name}-${slug}-screen`)
      checks.push({ viewport: viewport.name, slug, detail_metrics: strategy.backtest_metrics,
        replay_metrics: Object.fromEntries(['trades', 'win_rate', 'payoff_ratio', 'profit_factor'].map(key => [key, replay.backtests[slug].metrics[key]])),
        screen_date: replay.screens[slug].trade_date,
        screen_picks: replay.screens[slug].picks.map(pick => ({ code: pick.code, score: pick.factors.score })),
        request_template: payload, horizontal_overflow: false })
    }
    await context.close()
  }
  assert.deepEqual(errors, [])
  assert.deepEqual(gaps, [])
  assert.deepEqual(unexpectedWrites, [])
  assert.deepEqual(staticFailures, [])
  assert.equal(backtestRequests.length, 6)
  completed = true
} catch (error) {
  errors.push(String(error))
  if (activePage && !activePage.isClosed()) await screenshot(activePage, 'failure-state')
  throw error
} finally {
  const receipt = { passed: completed, base, api_replay: true, financial_values: 'actual historical system output',
    catalog_sha256: hash(catalogBytes), replay_sha256: hash(replayBytes), checks,
    errors, gaps, unexpectedWrites, staticFailures, staticAssets: [...staticAssets].sort(),
    interceptedBacktestRequests: backtestRequests.length }
  await fs.writeFile(path.join(output, 'verification.json'), JSON.stringify(receipt, null, 2))
  console.log(JSON.stringify({ passed: completed, checks: checks.length, errors, gaps, unexpectedWrites, staticFailures,
    staticAssets: staticAssets.size,
    interceptedBacktestRequests: backtestRequests.length, receipt: path.join(output, 'verification.json') }))
  await browser.close()
}

import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { chromium, expect } from '@playwright/test'
import { createLogger, createServer } from 'vite'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

// Offline layout acceptance. All API reads use memory fixtures; every write and
// every request to another origin is refused, including model/provider calls.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = path.resolve(root, process.env.AGENT_WORKSPACE_UI_OUT || '../.local/agent-workbench-acceptance')
await fs.mkdir(out, { recursive: true })
const logger = createLogger('error')
const logError = logger.error.bind(logger)
logger.error = (message, settings) => logError(String(message).slice(0, 1800), settings)
const server = process.env.AGENT_WORKSPACE_UI_BASE ? null : await createServer({ root, customLogger: logger,
  server: { host: '127.0.0.1', port: 0, open: false } })
if (server) await server.listen()
const base = process.env.AGENT_WORKSPACE_UI_BASE || server.resolvedUrls.local[0].replace(/\/$/, '')
const origin = new URL(base).origin
assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(new URL(base).hostname), 'Use a local preview only')
console.log(`Offline workspace preview: ${base}`)

const now = '2026-09-30T14:31:00+08:00'
const paragraph = '核对市场环境、系统候选与执行证据，记录触发条件、失效条件及等待的理由。'.repeat(6)
const seed = routeFixture(new URL(`${base}/api/ops/stock-agents/smoke-agent`), 'agent-detail').body
const options = routeFixture(new URL(`${base}/api/ops/stock-agents/options`), 'agents').body
const positions = Array.from({ length: process.env.AGENT_WORKSPACE_UI_CASE === 'table-sticky' ? 24 : 8 }, (_, i) => ({
  code: String(600001 + i), name: `隔离持仓${String(i + 1).padStart(2, '0')}`, quantity: 1000, available_quantity: 800,
  cost_cents: 2000000 + i * 10000, average_cost: 20 + i / 10, mark_price_cents: 2150 + i * 10,
  market_value_cents: 2150000 + i * 10000, unrealized_pnl_cents: 150000, mark_at: now,
  strategies: ['qianlong-close-v3'], holding_plan: paragraph, take_profit_plan: paragraph, stop_loss_plan: paragraph,
  exit_today_plan: paragraph, entry_context: { reason: paragraph, opened_at: '2026-09-28T10:31:00+08:00' },
  last_review: { action: 'hold', reason: `${paragraph}持仓依据完整末尾${String(i + 1).padStart(2, '0')}`, at: now },
  entry_price_cents: i === 7 ? null : 1950 + i * 10, entry_at: i === 7 ? null : '2026-09-28T10:31:00+08:00',
  holding_days: i === 7 ? null : 2, entry_reason: `${paragraph}买入理由完整末尾${i + 1}`, pnl_pct: i === 7 ? null : 7.43,
}))
const watchlist = Array.from({ length: 24 }, (_, i) => ({
  code: String(300001 + i), name: `隔离候选${String(i + 1).padStart(2, '0')}`, reason: paragraph,
  strategies: ['qianlong-close-v3'], signals: [{ date: '2026-09-30', created_at: now, reason: paragraph, rule_version: 'offline' }],
  watch: { code: String(300001 + i), name: `隔离候选${String(i + 1).padStart(2, '0')}`, reason: paragraph,
    entry_condition: paragraph, exit_condition: paragraph, added_at: now, updated_at: now },
}))
const lesson = i => ({
  id: `lesson-${i}`, title: `择时经验${String(i).padStart(2, '0')}`, finding: paragraph, conditions: paragraph,
  status: i % 2 ? 'pending' : 'supported', evidence_refs: [`run:offline:lesson-${i}`, `trade:offline:lesson-${i}`],
  sample_size: i + 2, sample_basis: 'observed', sample_definition: paragraph,
  positive_examples: [{ evidence_ref: `run:offline:positive-${i}`, interpretation: paragraph }],
  counter_examples: [{ evidence_ref: `run:offline:counter-${i}`, interpretation: `反例全文末尾-${i}` }],
  validation_plan: paragraph, last_review_date: '2026-09-30', last_review_phase: 'weekly_review',
})
const learning = {
  lessons: Array.from({ length: 12 }, (_, i) => lesson(i + 1)),
  optimization_proposals: Array.from({ length: 8 }, (_, i) => ({ ...lesson(i + 101), id: `proposal-${i + 1}`,
    title: `判分建议${String(i + 1).padStart(2, '0')}`, target: i % 2 ? 'selection' : 'scoring', proposed_change: paragraph })),
  last_review_date: '2026-09-30', last_review_phase: 'weekly_review',
}
const account = {
  ...seed.state, account_version: 7, initial_capital_cents: 50000000, cash_cents: 35000000, equity_cents: 52400000,
  market_value_cents: 17400000, total_pnl_cents: 2400000, realized_pnl_cents: 1200000, unrealized_pnl_cents: 1200000,
  fees_cents: 12000, positions, watchlist: watchlist.map((row, i) => ({ ...row.watch,
    observed_at: i === 23 ? null : now, observed_price_cents: i === 23 ? null : 1950,
    current_price_cents: i === 23 ? null : 2150, current_price_at: i === 23 ? null : now,
    expected_entry_price_cents: i === 23 ? null : 2100, reviewed_at: i === 23 ? null : now,
    review_reason: `${paragraph}评估全文末尾${i + 1}`, review_status: i === 23 ? 'unreviewed' : 'wait',
  })), valuation_at: now,
  valuation_date: '2026-09-30', valuation_kind: 'reference', selected_today: { date: '2026-09-30', codes: watchlist.map(row => row.code) },
}
const config = { ...seed.config, provider: 'offline-provider', model: 'offline-deepseek', enabled: true,
  position_limit: 0, watch_limit: 0, description: '离线布局验收 · 不执行交易',
  schedule: { ...seed.config.schedule, weekly_review_enabled: true, weekly_review_time: '20:30' } }
const falcon = { ...seed, id: 'falcon-agent', config: { ...config, kind: 'falcon', name: '猎隼' }, state: { ...account, falcon_learning: learning,
  research_plan: Array.from({ length: 30 }, (_, i) => `研究计划第${i + 1}段：${paragraph}`).join('\n\n') + '\n研究计划完整末尾',
  research_plan_date: '2026-10-08', research_plan_at: now },
  total_runs: 60, total_actions: 120, total_trades: 60, history_kept: 56, cleaned_runs: 4, latest_at: now, latest_phase: 'weekly_review',
  latest_status: 'success', latest_summary: paragraph,
  latest_actions: Array.from({ length: 8 }, (_, i) => ({ code: String(300001 + i), name: `隔离动作${String(i + 1).padStart(2, '0')}`,
    action: 'hold', quantity: 0, status: 'filled' })),
  schedules: [{ phase: 'premarket', label: '盘前准备', time: '08:30', enabled: true },
    { phase: 'auction', label: '竞价研判', time: '09:25', enabled: true },
    { phase: 'intraday', label: '盘中管理', time: '每15分钟', enabled: true },
    { phase: 'closeout', label: '尾盘收敛', time: '14:50', enabled: false },
    { phase: 'review', label: '日复盘', time: '20:00', enabled: true },
    { phase: 'weekly_review', label: '周复盘', time: '周五 · 20:30', enabled: true }] }
const custom = { ...falcon, id: 'custom-agent', config: { ...config, name: '隔离自定义', kind: 'custom' },
  state: { ...account, research_plan: falcon.state.research_plan, research_plan_date: '2026-10-08', research_plan_at: now } }
const agents = [falcon, custom, ...Array.from({ length: 13 }, (_, i) => ({ ...custom,
  id: `overview-agent-${i + 1}`, config: { ...custom.config, name: `总览样本${String(i + 1).padStart(2, '0')}` } }))]
const sections = Array.from({ length: 12 }, (_, i) => ({
  heading: `研究章节${i + 1}`, kind: i ? 'stock' : 'overview', paragraphs: [paragraph, paragraph],
  stats: [{ label: '观察样本', value: `${i + 2}个` }], plans: [{ label: `条件计划${i + 1}`, detail: paragraph,
    meta: i === 11 ? '完整报告末尾 · 离线证据' : paragraph }], plan_date: '2026-10-08',
}))
const history = {
  runs: Array.from({ length: 60 }, (_, i) => ({ id: `offline-run-${i + 1}`, phase: 'review',
    started_at: new Date(new Date(now).getTime() - (i < 24 ? i * 60000 : 86400000 + i * 60000)).toISOString(),
    finished_at: now, status: 'success', summary: `日记${String(i + 1).padStart(2, '0')} · **保存结论** [来源](https://example.test/long-source). ${paragraph}`,
    actions: [{ code: '600001', name: '成交样本', action: 'buy', quantity: 100, status: 'filled' },
      { code: '600002', name: '拒单样本', action: 'sell', quantity: 100, status: 'rejected' },
      { code: '300001', name: '观察样本', action: 'watch', quantity: 0, status: 'recorded' }] })),
  trades: Array.from({ length: 60 }, (_, i) => ({ id: `offline-trade-${i + 1}`, at: new Date(new Date(now).getTime() - i * 60000).toISOString(), code: String(600001 + i),
    name: `隔离成交${String(i + 1).padStart(2, '0')}`, action: i % 2 ? 'sell' : 'buy', side: i % 2 ? 'sell' : 'buy',
    quantity: 1000, price_cents: 2150, gross_cents: 2150000, fees_cents: 900, realized_pnl_cents: 12000, reason: paragraph })),
  funding: Array.from({ length: 60 }, (_, i) => ({ id: `offline-fund-${i + 1}`, at: now, kind: i ? 'deposit' : 'initial',
    amount_cents: 999999999999 - i * 10000 })),
}
const assessments = watchlist.map((row, i) => ({ code: row.code, stance: i === 23 ? 'unreviewed' : i % 2 ? 'wait' : 'participate',
  summary: `研判${i + 1}：等待条件与实际执行分别核验。`, focus: i < 2, expected_entry_price: i === 23 ? null : 21,
  data_status: i === 23 ? 'missing' : 'available', evidence_refs: [`run:offline:${row.code}`, `quote:offline:${row.code}`] }))
const coverage = { required_codes: watchlist.map(row => row.code), reviewed_codes: watchlist.slice(0, 23).map(row => row.code),
  unreviewed_codes: [watchlist.at(-1).code], focus_codes: watchlist.slice(0, 2).map(row => row.code), total: 24, reviewed: 23, complete: false }
const plan = { market_view: paragraph, next_trade_date: '2026-10-08', stocks: watchlist.map((row, i) => ({ code: row.code,
  entry_condition: paragraph, exit_condition: paragraph, invalidation: paragraph,
  next_check: i === 23 ? '接续计划完整末尾' : '下次研判结合保存的行情核验。' })) }
falcon.state.research_plan_structured = plan; falcon.state.assessment_coverage = coverage
const guardianRuns = Array.from({ length: 24 }, (_, i) => ({ slot: `2026-09-30T${String(14 - Math.floor(i / 4)).padStart(2, '0')}:${String((3 - i % 4) * 15).padStart(2, '0')}:00+08:00`,
  started: 1790749860 - i * 900, status: 'success', result: { sections, analysis_only: true, outcome: 'no_action',
    decisions: [], fills: [], rejects: [], model: config.model, as_of: now, notify: { skipped: 'no_action' } } }))
const reports = Array.from({ length: 24 }, (_, i) => ({ report_key: `daily:2026-09-${String(30 - i).padStart(2, '0')}`,
  period: 'daily', trade_date: `2026-09-${String(30 - i).padStart(2, '0')}`, status: 'success', summary: paragraph, created_at: now }))
const guardian = {
  config: { enabled: true, provider: config.provider, model: config.model, prompt: '', strategies: ['qianlong-close-v3'], notify: false },
  state: account, runs: guardianRuns, default_prompt: '', default_weekly_prompt: '', job_id: 'offline-guardian',
  observation_count: watchlist.length, watchlist, active_strategies: [{ slug: 'qianlong-close-v3', name: '乾隆' }],
  data_source: { label: '离线夹具', wudao: false, reason: '界面验收', toolcount: 0 },
  experience: { date: '2026-09-30', items: learning.lessons.map((item, i) => ({ id: item.id, hypothesis: `经验记录${i + 1} · ${item.finding}`,
    validation_plan: `${item.validation_plan}经验验证完整末尾${i + 1}`, status: 'proposed', evidence_ids: item.evidence_refs })) },
}
const guardianStats = { total_runs: 60, full_entries: 60, compacted_entries: 0, total_trades: 60,
  total_reports: 24, retention: config.retention, protected_recent: 12 }
const conversations = Array.from({ length: 20 }, (_, i) => ({ id: `offline-topic-${i + 1}`, title: `离线咨询${String(i + 1).padStart(2, '0')}`,
  notes: paragraph, created: 1790749860 - i * 3600, updated: 1790749860 - i * 3600 }))
function paginate(items, url) {
  const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 20)
  const start = url.searchParams.get('start'), end = url.searchParams.get('end')
  const filtered = start || end ? items.filter(item => {
    const at = item.started_at || item.at
    if (!at) return true
    const day = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date(at))
    return (!start || day >= start) && (!end || day <= end)
  }) : items
  return { items: filtered.slice(offset, offset + limit), total: filtered.length, offset, limit }
}
function fixture(url) {
  const api = decodeURIComponent(url.pathname.replace(/^\/api/, ''))
  if (api === '/ops/stock-agents/options') return { ...options, templates: { custom: custom.config,
    leader: { ...custom.config, kind: 'leader' }, falcon: falcon.config } }
  if (api === '/ops/stock-agents') return { items: agents.map(agent => ({ ...agent,
    state: { ...agent.state, position_count: positions.length } })), as_of: now }
  if (api === '/ops/stock-agents/guardian/overview') return { config: guardian.config, state: account, runs: guardianRuns,
    stats: guardianStats, position_count: positions.length, position_policy: { normal_max: null, absolute_max: null, close_max: null } }
  if (api === '/ops/stock-agents/guardian/storage') return guardianStats
  const agent = agents.find(item => api === `/ops/stock-agents/${item.id}`)
  if (agent) return agent
  if (/^\/ops\/stock-agents\/[^/]+\/equity$/.test(api)) {
    const range = url.searchParams.get('range') || 'day'
    const delta = { day:100000, week:200000, month:300000, half_year:400000, year:500000 }[range]
    return { items: Array.from({ length: 20 }, (_, i) => ({ day: range === 'day' ? '2026-09-30' : `2026-09-${String(i + 11).padStart(2, '0')}`,
      at: range === 'day' ? `2026-09-30T09:${String(i + 30).padStart(2, '0')}:00+08:00` : now,
      equity_cents: 50000000 + i * delta, funded_cents: 50000000, pnl_cents: i * delta,
      realized_pnl_cents: i * 60000, fees_cents: i * 600, stale: 0 })), total: 20, truncated: false,
    range, granularity: range === 'day' ? 'intraday' : 'daily', caliber: '离线模拟' }
  }
  if (/^\/ops\/stock-agents\/[^/]+\/history$/.test(api)) return paginate(history[url.searchParams.get('kind')] || [], url)
  if (/^\/ops\/stock-agents\/[^/]+\/runs\//.test(api)) {
    const id = api.split('/').at(-1), old = id === 'offline-run-2', row = history.runs.find(item => item.id === id) || history.runs[0]
    return { ...row, sections: old ? sections : [], detail: old ? {
      summary: '# 旧结论\n\n' + paragraph + '\n<img src="https://example.test/pixel" onerror="window.__diaryAttack=1">',
      body: '旧全文正文\n\n' + paragraph.repeat(16) + '\n\n旧全文完整末尾', research_plan: paragraph,
      fills: [], decisions: [], rejects: [],
    } : { summary: '保留环境判断，买卖与观察分别记录。', assessments, assessment_coverage: coverage,
      detail: { market_summary: '市场环境仍需确认。', changes: '重点跟进2个标的，覆盖23/24，1个未研判。', next_steps: '按各标的条件复核。' },
      research_plan_structured: plan, research_plan: falcon.state.research_plan,
      quotes: Object.fromEntries(watchlist.map(item => [item.code, { name: item.name, price: 21.5 }])),
      fills: [{ code: '600001', name: '成交样本', action: 'buy', side: 'buy', quantity: 100, price_cents: 2100, fees_cents: 2, occurred_at: now }],
      decisions: [{ code: '600001', action: 'buy', quantity: 100, reason: '保存的买入意图。' },
        { code: '300001', action: 'watch', quantity: 0, reason: '保存的观察动作。' }],
      rejects: [{ code: '600002', action: 'sell', reason: '行情条件未满足，未执行。' }], learning,
    } }
  }
  if (api === '/ops/guardian') return guardian
  if (api === '/ops/guardian/research') return { watchlist, active_strategies: guardian.active_strategies, watchlist_as_of: now }
  if (api === '/ops/guardian/runs') return paginate(guardianRuns, url)
  if (api.startsWith('/ops/guardian/runs/')) return guardianRuns.find(run => api.endsWith(run.slot)) || guardianRuns[0]
  if (api === '/ops/guardian/reviews') return paginate(reports, url)
  if (api.startsWith('/ops/guardian/reviews/')) return { ...(reports.find(report => api.endsWith(report.trade_date)) || reports[0]),
    result: { sections, revision: 1, created_at: now, notify: { skipped: 'offline' } } }
  if (api === '/ops/guardian/activity') return { runs: guardianRuns.slice(0, 8), reports: reports.slice(0, 8), limit: 16 }
  if (api === '/ops/guardian/trades') return paginate(history.trades.map(row => ({ ...row, occurred_at: now, quote_at: now,
    commission_cents: 600, stamp_tax_cents: 200, transfer_cents: 100, allocated_cost_cents: 2000000,
    cash_after_cents: 35000000, before_quantity: 0, after_quantity: 1000, quote_source: 'offline' })), url)
  if (api === '/ops/guardian/performance') return paginate(history.trades.map(row => ({ ...row, bought_quantity: 2000,
    sold_quantity: 1000, realized_pnl_cents: 12000, fees_cents: 900 })), url)
  if (api === '/ops/guardian/holding-curve') return {
    code: '', name: '隔离账户', scope: 'account', method: 'account_equity_v1', as_of: now, start: now, end: now,
    opened_at: now, points: [], protection: [], excluded_points: 0, coverage: { sampled: true },
    summary: { current_drawdown_pct: null, max_drawdown_pct: null, last_valid_drawdown_pct: null, last_valid_at: null,
      last_valid_pnl_cents: null, peak_at: null, max_drawdown_peak_at: null, max_drawdown_at: null,
      valid_points: 0, latest_nav: null, latest_pnl_cents: null, recovery_pct: null } }
  if (api === '/ops/guardian/consultations') return { conversations }
  if (api.startsWith('/ops/guardian/consultations/')) return { ...(conversations.find(topic => api.endsWith(topic.id)) || conversations[0]),
    turns: Array.from({ length: 12 }, (_, i) => ({ id: `offline-turn-${i + 1}`, question: `离线提问${i + 1} · ${paragraph}`,
      status: 'success', created: 1790749860 + i * 60, result: { answer: `${paragraph}\n\n咨询全文末尾-${i + 1}`, model: config.model, as_of: now } })) }
  return undefined
}

async function layout(page, row, label) {
  const measured = await page.evaluate(() => ({
    width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth,
    documentHeight: document.documentElement.scrollHeight, bodyHeight: document.body.scrollHeight,
    scrollX, scrollY,
  }))
  row.measurements.push({ label, ...measured })
  assert.ok(measured.documentWidth <= measured.width + 2, `${label}: horizontal document overflow ${JSON.stringify(measured)}`)
  assert.ok(measured.documentHeight <= measured.height + 2, `${label}: vertical document overflow ${JSON.stringify(measured)}`)
  assert.equal(measured.scrollY, 0, `${label}: document scrolled instead of workspace`)
}
async function inViewport(locator, label) {
  await expect(locator, label).toBeVisible()
  await expect(locator, label).toBeInViewport({ ratio: 0.5 })
  const visible = await locator.evaluate(element => {
    const box = element.getBoundingClientRect()
    let left = Math.max(0, box.left), right = Math.min(innerWidth, box.right)
    let top = Math.max(0, box.top), bottom = Math.min(innerHeight, box.bottom)
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent), bounds = parent.getBoundingClientRect()
      if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) { left = Math.max(left, bounds.left); right = Math.min(right, bounds.right) }
      if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) { top = Math.max(top, bounds.top); bottom = Math.min(bottom, bounds.bottom) }
    }
    return { width: right - left, height: bottom - top }
  })
  assert.ok(visible.width > 4 && visible.height > 4, `${label}: clipped by an ancestor ${JSON.stringify(visible)}`)
}
async function revealTail(page, locator, row, label, { requireScroll = true } = {}) {
  await expect(locator, label).toBeVisible()
  const scrollers = await locator.evaluate(element => {
    const found = []
    for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight + 4) {
        parent.scrollTop = parent.scrollHeight
        found.push({ class: parent.className, label: parent.getAttribute('aria-label'), range: parent.scrollHeight - parent.clientHeight,
          bottom: parent.scrollHeight - parent.clientHeight - parent.scrollTop })
      }
    }
    return found
  })
  if (requireScroll) assert.ok(scrollers.length, `${label}: rich content has no internal vertical scroller`)
  assert.ok(scrollers.every(item => item.bottom < 3), `${label}: scroller cannot reach its bottom ${JSON.stringify(scrollers)}`)
  await locator.scrollIntoViewIfNeeded()
  await inViewport(locator, `${label} tail`)
  if (!scrollers.length) await expect(locator).toBeInViewport({ ratio: 1 })
  row.scrollers.push({ label, scrollers })
  await layout(page, row, label)
}
async function workspaceNavigation(page, row, name, panelSelector) {
  const nav = page.getByRole('navigation', { name, exact: true })
  await expect(nav).toBeVisible()
  assert.equal(await nav.evaluate(element => Boolean(element.closest('header, .studio-head, .guardian-header'))), false,
    `${name}: workspace navigation is embedded in the header`)
  const tabs = nav.getByRole('tab')
  assert.ok(await tabs.count() >= 4, `${name}: missing workspace tabs`)
  const desktop = row.width >= 768
  await expect(nav.getByRole('tablist')).toHaveAttribute('aria-orientation', desktop ? 'vertical' : 'horizontal')
  if (desktop) {
    const navigationBox = await nav.boundingBox(), panelBox = await page.locator(panelSelector).boundingBox()
    assert.ok(navigationBox.x + navigationBox.width <= panelBox.x + 2, `${name}: desktop navigation must be to the left of the content`)
  }
  const names = await tabs.allTextContents()
  await tabs.first().focus()
  await tabs.first().press('End')
  await expect(tabs.last()).toBeFocused()
  await tabs.last().press('Home')
  await expect(tabs.first()).toBeFocused()
  await tabs.first().press(desktop ? 'ArrowDown' : 'ArrowRight')
  await expect(tabs.nth(1)).toBeFocused()
  for (let i = 0; i < names.length; i++) {
    await tabs.nth(i).scrollIntoViewIfNeeded()
    await inViewport(tabs.nth(i), `${name} ${names[i]}`)
    await tabs.nth(i).click()
    await expect(tabs.nth(i)).toHaveAttribute('aria-selected', 'true')
    await layout(page, row, `${name} ${names[i]}`)
  }
  row.checks.push(`${name}: ${names.length} independent tabs reachable by mouse and keyboard; ${desktop ? 'left vertical navigation' : 'horizontal mobile navigation'}`)
  return nav
}
async function selectTab(nav, name) {
  const tab = nav.getByRole('tab', { name: new RegExp(`^${name}`) })
  await tab.scrollIntoViewIfNeeded(); await tab.click()
  await expect(tab).toHaveAttribute('aria-selected', 'true')
}
async function panelAtTop(page, title, row, label, fromScrollTop) {
  assert.ok(fromScrollTop > 100, `${label}: preceding pane was not scrolled far enough to reproduce the issue`)
  const panel = page.locator('#stock-agent-panel')
  await expect.poll(() => panel.evaluate(element => element.scrollTop), { message: `${label}: reset vertical scroll` }).toBe(0)
  await expect.poll(() => panel.evaluate(element => element.scrollLeft), { message: `${label}: reset horizontal scroll` }).toBe(0)
  await inViewport(title, `${label}: top-of-pane content`)
  row.scroll_resets.push({ label, from_scroll_top: fromScrollTop, scroll_top: 0, scroll_left: 0 })
  await layout(page, row, label)
}
async function parentScrollTop(locator) {
  return locator.evaluate(element => {
    let top = 0
    for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) top = Math.max(top, parent.scrollTop)
    return top
  })
}
async function revealTextEnd(page, locator, marker, row, label) {
  const measured = await locator.evaluate((element, text) => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    let node, target
    while ((node = walker.nextNode())) if (node.textContent.includes(text)) { target = node; break }
    if (!target) throw new Error(`Missing saved text marker ${text}`)
    const start = target.textContent.indexOf(text), range = document.createRange()
    range.setStart(target, start); range.setEnd(target, start + text.length)
    const parents = []
    for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight + 2) parents.push(parent)
    }
    for (const parent of parents) {
      const box = parent.getBoundingClientRect(), tail = range.getBoundingClientRect()
      if (tail.bottom > box.bottom - 12) parent.scrollTop += tail.bottom - box.bottom + 12
      if (tail.top < box.top + 12) parent.scrollTop += tail.top - box.top - 12
    }
    const tail = range.getBoundingClientRect()
    return { top:tail.top,bottom:tail.bottom,scrollTop:Math.max(0,...parents.map(parent=>parent.scrollTop)),parents:parents.length }
  }, marker)
  assert.ok(measured.top >= 0 && measured.bottom <= row.height, `${label}: saved final line cannot be reached ${JSON.stringify(measured)}`)
  assert.ok(measured.scrollTop > 100, `${label}: long source did not scroll`)
  row.scrollers.push({ label, text_tail:measured })
  await layout(page,row,label)
  return measured.scrollTop
}
async function largeDialog(page, locator, row, label, minimum = 900) {
  await expect(locator).toBeVisible()
  const box = await locator.boundingBox()
  assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= row.width + 2 && box.y + box.height <= row.height + 2, `${label}: dialog clipped by viewport ${JSON.stringify(box)}`)
  assert.ok(box.width >= Math.min(minimum, row.width - 56), `${label}: expected a reading dialog, got ${box.width}px`)
  row.dialogs.push({ label, ...box })
  await layout(page, row, label)
}
async function inspectStickyTable(page, selector, row, label) {
  const pane = page.locator(selector), scroll = pane.locator('[data-slot=table-container]')
  const measure = async phase => scroll.evaluate((element, state) => {
    const table = element.querySelector('table'), head = table.querySelector('thead'), th = head.querySelector('th')
    const attrs = node => [...node.attributes].filter(attr=>attr.name.startsWith('data-v-')).map(attr=>attr.name)
    const rect = node => {const box=node.getBoundingClientRect();return {x:box.x,y:box.y,width:box.width,height:box.height}}
    const style = getComputedStyle(th)
    return { phase:state, scrollTop:element.scrollTop,scrollHeight:element.scrollHeight,clientHeight:element.clientHeight,
      overflowY:getComputedStyle(element).overflowY,table_scope:attrs(table),th_scope:attrs(th),pane_scope:attrs(element.closest('section')),
      position:style.position,top:style.top,table_box:rect(table),header_box:rect(th),scroll_box:rect(element),thead_box:rect(head),
      headings:[...head.querySelectorAll('th')].map(node=>({text:node.textContent,position:getComputedStyle(node).position,top:getComputedStyle(node).top,box:rect(node)})) }
  }, phase)
  const before = await measure('before')
  await scroll.evaluate(element=>element.scrollTop=element.scrollHeight)
  const after = await measure('after')
  row.sticky_tables.push({ label,before,after })
  await page.screenshot({path:path.join(out,`sticky-${label}-${row.width}.png`),fullPage:true})
  if (process.env.AGENT_WORKSPACE_UI_STICKY_ASSERT === '1') {
    assert.ok(after.scrollTop>100,`${label}: table fixture was not scrolled`)
    assert.equal(after.position,'sticky',`${label}: column heading is not sticky`)
    assert.equal(after.top,'0px',`${label}: heading top must be zero`)
    assert.ok(after.header_box.y>=after.scroll_box.y-2 && after.header_box.y+after.header_box.height<=after.scroll_box.y+after.scroll_box.height+2,
      `${label}: header is clipped after scrolling ${JSON.stringify(after)}`)
    assert.ok(after.headings.every(header=>header.position==='sticky' && header.top==='0px' && Math.abs(header.box.y-after.scroll_box.y)<3),`${label}: a column header is not fixed`)
    for(const header of await pane.locator('th').all()) { await header.scrollIntoViewIfNeeded(); await inViewport(header,`${label}: column heading after scrolling`) }
    const lastStock = page.getByRole('button',{name:label==='positions'?'查看 隔离持仓24 持仓详情':'查看 隔离候选24 观察详情',exact:true})
    await revealTail(page,lastStock,row,`${label}-sticky-last-row`)
    await inViewport(pane.locator('th').first(),`${label}: column heading after last row`)
    await page.screenshot({path:path.join(out,`sticky-${label}-${row.width}.png`),fullPage:true})
  }
  await layout(page,row,`${label}-sticky-inspection`)
}
async function inspectStickyPanel(page, selector, row, label) {
  const pane=page.locator(selector),kind=label==='positions'?'持仓':'观察',prefix=label==='positions'?'隔离持仓':'隔离候选'
  const first=page.getByRole('button',{name:`查看 ${prefix}01 ${kind}详情`,exact:true})
  await expect(first).toBeVisible()
  await page.screenshot({path:path.join(out,`panel-${label}-${row.width}.png`),fullPage:true})
  const last=page.getByRole('button',{name:`查看 ${prefix}24 ${kind}详情`,exact:true})
  if(row.width>=768) await inspectStickyTable(page,selector,row,label)
  else {
    await expect(pane.locator('[data-slot=table-container]')).toBeHidden()
    const cards=pane.locator(label==='positions'?'.portfolio-mobile-row':'.watch-mobile-row')
    await expect(cards).toHaveCount(24)
    await expect(cards.first()).toContainText('19.50')
    await expect(cards.nth(label==='positions'?7:23)).toContainText('—')
    await revealTail(page,last,row,`${label}-mobile-last-card`)
    await page.screenshot({path:path.join(out,`sticky-${label}-${row.width}.png`),fullPage:true})
  }
  await last.click()
  const dialog=page.locator('[data-agent-detail-dialog]')
  await largeDialog(page,dialog,row,`${label}-delta-detail`)
  const body=dialog.locator('[data-agent-detail-scroll]')
  await body.evaluate(element=>element.scrollTop=element.scrollHeight)
  await inViewport(dialog.getByRole('heading',{name:new RegExp(`${prefix}24`)}),`${label}-delta-detail-fixed-title`)
  await inViewport(dialog.locator('[data-slot=dialog-close]'),`${label}-delta-detail-fixed-close`)
  assert.equal(await dialog.evaluate(element=>element.scrollTop),0,`${label}-delta-detail outer scrolled`)
  await layout(page,row,`${label}-delta-detail`)
  await page.screenshot({path:path.join(out,`detail-${label}-${row.width}.png`),fullPage:true})
  await page.keyboard.press('Escape')
  await layout(page,row,`${label}-delta`)
}

const viewports = [[1440, 900], [1366, 768], [1024, 600], [390, 844]]
  .filter(([width]) => !process.env.AGENT_WORKSPACE_UI_WIDTH || width === Number(process.env.AGENT_WORKSPACE_UI_WIDTH))
const productFiles = [
  'src/features/agents/AgentsView.vue', 'src/features/agents/components/StockAgentStudio.vue',
  'src/features/agents/components/StockAgentStudio.css', 'src/features/agents/components/AgentWorkspaceNav.vue',
  'src/features/agents/components/GuardianStudio.vue', 'src/features/agents/components/AgentHistoryPanel.vue',
  'src/features/agents/components/FalconLearningPanel.vue', 'src/features/ops/components/GuardianTab.vue',
  'src/features/ops/components/GuardianTab.css', 'src/features/ops/components/GuardianTab.mobile.css',
  'src/features/agents/components/AgentPositionsPanel.vue', 'src/features/agents/components/AgentWatchPanel.vue',
  'src/features/agents/components/AgentEquityChart.vue', 'src/features/agents/components/AgentRunDetail.vue',
  'src/features/agents/components/AgentReportDocument.vue', 'src/features/agents/components/agentHistoryDisplay.ts',
  'src/shared/types/stock_agents.ts', 'src/shared/api/stock_agents.ts',
]
async function productHashes() {
  return Object.fromEntries(await Promise.all(productFiles.map(async file => [file,
    createHash('sha256').update(await fs.readFile(path.join(root, file))).digest('hex') ])))
}
const sourceBefore = await productHashes()
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined, timeout: 30000 })
const results = []
try {
  for (const [width, height] of viewports) {
    const context = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce', serviceWorkers: 'block' })
    const page = await context.newPage()
    page.setDefaultTimeout(12000)
    const row = { width, height, errors: [], writes: [], externalRequests: [], checks: [], measurements: [], scrollers: [], scroll_resets: [], dialogs: [], history_queries: [], equity_queries: [],sticky_tables:[] }
    results.push(row)
    page.on('pageerror', error => row.errors.push(String(error)))
    await page.clock.install({ time: new Date(now) })
    await page.addInitScript(() => localStorage.setItem('loci-appearance', 'day'))
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== origin) { row.externalRequests.push(url.origin); return route.abort() }
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        row.writes.push(`${request.method()} ${url.pathname}`); return route.abort()
      }
      if (/\/stock-agents\/[^/]+\/history$/.test(url.pathname)) row.history_queries.push(Object.fromEntries(url.searchParams))
      if (/\/stock-agents\/[^/]+\/equity$/.test(url.pathname)) {
        const range = url.searchParams.get('range')
        row.equity_queries.push(range)
        // A deliberately slower older request tests that it cannot replace the newest range.
        if (range === 'year') await new Promise(resolve => setTimeout(resolve, 160))
      }
      const body = fixture(url)
      if (body !== undefined) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
      const fallback = routeFixture(url, 'agents')
      if (!fallback) row.errors.push(`Missing offline fixture ${url.pathname}`)
      return route.fulfill({ status: fallback?.status || (fallback ? 200 : 404), contentType: 'application/json',
        body: JSON.stringify(fallback?.body ?? { detail: 'Offline fixture missing' }) })
    })
    async function check(label, action) {
      if (process.env.AGENT_WORKSPACE_UI_CASE && process.env.AGENT_WORKSPACE_UI_CASE !== label) return
      console.log(`${width}x${height}: ${label}`)
      try { await action(); row.checks.push(label) }
      catch (error) { row.errors.push(`${label}: ${error.stack || error}`); console.error(`${width}x${height}: ${label} failed: ${error.message || error}`); await page.screenshot({ path: path.join(out, `failure-${width}-${label}.png`), fullPage: true }).catch(() => {}) }
    }
    try {
      if (process.env.AGENT_WORKSPACE_UI_CASE === 'table-sticky') await check('table-sticky',async()=>{
        await page.goto(`${base}/agents/falcon-agent`,{waitUntil:'networkidle'})
        await expect(page.getByRole('heading',{name:'猎隼',exact:true})).toBeVisible()
        await inspectStickyPanel(page,'.positions-panel',row,'positions')
        await selectTab(page.getByRole('navigation',{name:'智能体工作区',exact:true}),'观察名单')
        await inspectStickyPanel(page,'.watch-panel',row,'watch')
      })
      await check('overview', async () => {
        await page.goto(`${base}/agents`, { waitUntil: 'networkidle' })
        await expect(page.getByRole('link', { name: '进入 猎隼 工作室', exact: true })).toBeVisible()
        await expect(page.locator('.agent-card')).toHaveCount(16)
        await revealTail(page, page.getByRole('link', { name: '进入 总览样本13 工作室', exact: true }), row, 'overview')
        const cardHeight = await page.locator('.agent-card').last().evaluate(element => element.clientHeight)
        assert.ok(cardHeight >= 240, `Overview cards were compressed to ${cardHeight}px`)
        await page.screenshot({ path: path.join(out, `overview-${width}.png`), fullPage: true })
      })
      for (const id of ['falcon-agent', 'custom-agent']) await check(id, async () => {
        await page.goto(`${base}/agents/${id}`, { waitUntil: 'networkidle' })
        await expect(page.getByRole('heading', { name: id === 'falcon-agent' ? '猎隼' : '隔离自定义', exact: true })).toBeVisible()
        const nav = await workspaceNavigation(page, row, '智能体工作区', '#stock-agent-panel')
        await expect(nav.getByRole('tab').last()).toContainText('历史日记')
        await selectTab(nav, '账户与持仓')
        await page.screenshot({ path: path.join(out, `account-${id}-${width}.png`), fullPage: true })
        const scheduleButton = page.getByRole('button', { name: width < 768 ? '查看工作日程' : '工作日程', exact: true })
        await scheduleButton.click()
        const schedule = page.locator('[data-agent-schedule-dialog]')
        await largeDialog(page, schedule, row, `${id}-schedule`, 800)
        await expect(schedule.locator('.schedule-slot')).toHaveCount(6)
        await revealTail(page, schedule.locator('.schedule-slot').last(), row, `${id}-schedule-last`, { requireScroll: false })
        await page.screenshot({ path: path.join(out, `schedule-${id}-${width}.png`), fullPage: true })
        await page.keyboard.press('Escape')
        const lastPosition = page.getByRole('button', { name: '查看 隔离持仓08 持仓详情', exact: true })
        await revealTail(page, lastPosition, row, `${id}-positions`, { requireScroll: false })
        await expect(width < 768 ? lastPosition : lastPosition.locator('xpath=ancestor::tr')).toContainText('—')
        if (width >= 768) {
          const rightmost = page.locator('.portfolio-row').last().locator('td').last()
          await rightmost.scrollIntoViewIfNeeded(); await inViewport(rightmost, 'position reason column horizontally reachable')
        }
        await lastPosition.click()
        const positionDialog = page.locator('[data-agent-detail-dialog]')
        await largeDialog(page, positionDialog, row, `${id}-position-detail`)
        await expect(positionDialog.locator('.detail-metrics')).toContainText('买入日期')
        await expect(positionDialog.locator('.detail-metrics')).toContainText('持仓天数')
        await expect(positionDialog.locator('.detail-metrics')).toContainText('—')
        await revealTail(page, positionDialog.getByText(positions.at(-1).last_review.reason, { exact: true }), row, `${id}-position-plan`)
        await inViewport(positionDialog.getByRole('heading', { name: /隔离持仓08/ }), 'Position dialog fixed title after scrolling')
        await inViewport(positionDialog.locator('[data-slot=dialog-close]'), 'Position dialog fixed close after scrolling')
        assert.equal(await positionDialog.evaluate(element => element.scrollTop), 0, 'Position detail must scroll inside its body')
        await page.screenshot({ path: path.join(out, `position-detail-${id}-${width}.png`), fullPage: true })
        await page.keyboard.press('Escape')
        await page.getByRole('group', { name: '账户视图', exact: true }).getByRole('button', { name: '账户曲线', exact: true }).click()
        const ranges = page.getByRole('group', { name: '曲线时间范围', exact: true })
        const infoBox = await page.getByRole('button', { name:'查看曲线计算口径', exact:true }).locator('svg').boundingBox()
        assert.ok(infoBox.width <= 20 && infoBox.height <= 20, `Curve info icon covers the plot: ${JSON.stringify(infoBox)}`)
        for (const [label, value] of [['当日', 'day'], ['7日', 'week'], ['一个月', 'month'], ['半年', 'half_year'], ['一年', 'year']]) {
          await ranges.getByRole('button', { name: label, exact: true }).click()
          await expect(ranges.getByRole('button', { name: label, exact: true })).toHaveAttribute('aria-pressed', 'true')
          await expect.poll(() => row.equity_queries.includes(value)).toBe(true)
          await expect(page.locator('.equity-card svg[role=img]')).toBeVisible()
          await layout(page, row, `${id}-curve-${value}`)
        }
        await ranges.getByRole('button', { name: '当日', exact: true }).click()
        await expect(page.locator('.equity-card')).toContainText('已保存日内估值')
        await ranges.getByRole('button', { name: '一年', exact: true }).click()
        await ranges.getByRole('button', { name: '一个月', exact: true }).click()
        await ranges.getByRole('button', { name: '7日', exact: true }).click()
        await expect(page.locator('.equity-card')).toContainText('日度估值')
        await expect(ranges.getByRole('button', { name: '7日', exact: true })).toHaveAttribute('aria-pressed', 'true')
        await expect(page.locator('.equity-card svg[role=img]')).toHaveAttribute('aria-label', /最新38,000\.00元/)
        await page.getByRole('group', { name: '曲线指标', exact: true }).getByRole('button', { name: '资产', exact: true }).click()
        await expect(page.locator('.equity-card svg[role=img]')).toHaveAttribute('aria-label', /^资产曲线/)
        await page.getByRole('group', { name: '曲线指标', exact: true }).getByRole('button', { name: '盈利', exact: true }).click()
        await page.locator('.equity-card svg[role=img]').focus(); await page.locator('.equity-card svg[role=img]').press('Home')
        await expect(page.locator('.equity-card .cursor-line')).toHaveCount(1)
        await page.locator('.equity-card svg[role=img]').press('End')
        await page.screenshot({ path: path.join(out, `curve-${id}-${width}.png`), fullPage: true })
        await selectTab(nav, '观察名单')
        const lastWatch = page.getByRole('button', { name: '查看 隔离候选24 观察详情', exact: true })
        await revealTail(page, lastWatch, row, `${id}-watch`)
        await expect(width < 768 ? lastWatch : lastWatch.locator('xpath=ancestor::tr')).toContainText('—')
        await page.screenshot({ path: path.join(out, `watch-${id}-${width}.png`), fullPage: true })
        await lastWatch.click()
        const watchDialog = page.locator('[data-agent-detail-dialog]')
        await largeDialog(page, watchDialog, row, `${id}-watch-detail`)
        await expect(watchDialog.locator('.detail-metrics')).toContainText('预期进入价')
        await expect(watchDialog).toContainText('评估全文末尾24')
        await revealTail(page, watchDialog.getByText(account.watchlist.at(-1).exit_condition, { exact: true }).last(), row, `${id}-watch-full`, { requireScroll: false })
        await inViewport(watchDialog.getByRole('heading', { name: /隔离候选24/ }), 'Watch dialog fixed title after scrolling')
        await inViewport(watchDialog.locator('[data-slot=dialog-close]'), 'Watch dialog fixed close after scrolling')
        assert.equal(await watchDialog.evaluate(element => element.scrollTop), 0, 'Watch detail must scroll inside its body')
        await page.screenshot({ path: path.join(out, `watch-detail-${id}-${width}.png`), fullPage: true })
        await page.keyboard.press('Escape')
        const watchScrollTop = await parentScrollTop(lastWatch)
        await selectTab(nav, '研究计划')
        await panelAtTop(page, page.getByText('接续研究计划', { exact: true }), row, `${id}-mouse-watch-to-plan`, watchScrollTop)
        const planBoxes = await Promise.all([page.locator('.studio-plan-main').boundingBox(), page.locator('.studio-plan-recent').boundingBox()])
        if (width >= 768) assert.ok(Math.abs(planBoxes[0].width / planBoxes[1].width - 3) < .15, 'Plan must reserve roughly 75% to research')
        else assert.ok(planBoxes[0].y + planBoxes[0].height <= planBoxes[1].y + 2, 'Mobile plan and recent work must stack')
        let planTail
        if (id === 'falcon-agent') planTail = page.getByText('接续计划完整末尾', { exact: true })
        else {
          await expect(page.locator('.research-plan')).toContainText('研究计划完整末尾')
          assert.equal(await page.locator('.research-plan').evaluate(element => element.scrollHeight <= element.clientHeight + 2), true, 'Legacy plan text was clipped')
          planTail = page.locator('.research-plan')
        }
        if (id === 'falcon-agent') await revealTail(page, planTail, row, `${id}-plan`)
        else await revealTextEnd(page,planTail,'研究计划完整末尾',row,`${id}-legacy-plan`)
        const planScrollTop = await parentScrollTop(planTail)
        await expect(page.locator('.latest-actions .action-tag')).toHaveCount(8)
        await page.locator('.latest-actions .action-tag').last().scrollIntoViewIfNeeded()
        await inViewport(page.locator('.latest-actions .action-tag').last(), 'Latest actions beyond the fifth')
        await expect(page.locator('.latest-actions .action-tag').last()).toContainText('隔离动作08')
        await page.screenshot({ path: path.join(out, `plan-${id}-${width}.png`), fullPage: true })
        await selectTab(nav, '账户与持仓')
        const assetTitle = page.getByText('模拟净资产', { exact: true })
        await panelAtTop(page, assetTitle, row, `${id}-mouse-plan-to-account`, planScrollTop)
        await selectTab(nav, '观察名单')
        await revealTail(page, lastWatch, row, `${id}-keyboard-watch-bottom`)
        const keyboardWatchScrollTop = await parentScrollTop(lastWatch)
        const watchTab = nav.getByRole('tab', { name: /^观察名单/ })
        await watchTab.focus()
        await watchTab.press(width < 768 ? 'ArrowRight' : 'ArrowDown')
        const planTab = nav.getByRole('tab', { name: /^研究计划/ })
        await expect(planTab).toHaveAttribute('aria-selected', 'true')
        await panelAtTop(page, page.getByText('接续研究计划', { exact: true }), row, `${id}-keyboard-watch-to-plan`, keyboardWatchScrollTop)
        if (id === 'falcon-agent') await revealTail(page, planTail, row, `${id}-keyboard-plan-bottom`)
        else await revealTextEnd(page,planTail,'研究计划完整末尾',row,`${id}-keyboard-legacy-plan`)
        const keyboardPlanScrollTop = await parentScrollTop(planTail)
        await planTab.focus()
        await planTab.press('Home')
        await expect(nav.getByRole('tab', { name: /^账户与持仓/ })).toHaveAttribute('aria-selected', 'true')
        await panelAtTop(page, assetTitle, row, `${id}-keyboard-plan-to-account`, keyboardPlanScrollTop)
        row.checks.push(`${id}: mouse and keyboard changes reset shared panel scrollTop/scrollLeft and reveal the new pane heading`)
        await selectTab(nav, '今日日记')
        await expect(page.locator('.diary-row')).toHaveCount(20)
        await expect(page.locator('.history-stats')).toContainText('累计60')
        await expect(page.locator('.history-stats')).toContainText('保留56')
        await expect(page.locator('.history-stats')).toContainText('清理4')
        assert.ok(row.history_queries.some(query => query.kind === 'runs' && query.start === '2026-09-30' && query.end === '2026-09-30'), 'Today diary did not request Beijing date bounds')
        const firstDiary = page.locator('.diary-row').first()
        await expect(firstDiary.locator('.diary-action')).toHaveCount(2)
        await expect(firstDiary.locator('.diary-actions')).toContainText('买入 成交样本')
        await expect(firstDiary.locator('.diary-actions')).toContainText('拒单')
        await expect(firstDiary.locator('.diary-actions')).not.toContainText('观察样本')
        assert.ok((await firstDiary.locator('.diary-summary').textContent()).length <= 180, 'Diary summary is not concise')
        await expect(firstDiary.locator('.diary-summary')).not.toContainText('https://')
        const statsBox = await page.locator('.history-stats').boundingBox(), datesBox = await page.locator('.history-filter__dates').boundingBox()
        if (width >= 768) assert.ok(statsBox.x + statsBox.width <= datesBox.x + 2 && Math.abs(statsBox.y - datesBox.y) < 24, 'Stats must sit to the left of date in the same bar')
        await page.locator('.history-filter__dates .date-field__trigger').click()
        await page.locator('.date-field__popup [data-value="2026-09-29"]:not([data-outside-view])').click()
        await expect(page.locator('.diary-row').first()).toContainText('日记25')
        await expect(page.locator('.history-pagination__total')).toHaveText('共 36 条')
        await page.getByRole('button', { name:'刷新当前历史页', exact:true }).click()
        await expect(page.locator('.diary-row').first()).toContainText('日记25')
        await page.getByRole('button', { name:'今日', exact:true }).click()
        await expect(page.locator('.diary-row').first()).toContainText('日记01')
        await expect(page.locator('.history-pagination__total')).toHaveText('共 24 条')
        await revealTail(page, page.locator('.diary-row').last(), row, `${id}-diary`)
        await page.screenshot({ path: path.join(out, `today-${id}-${width}.png`), fullPage: true })
        const pagination = page.locator('.history-pagination')
        await inViewport(pagination.locator('[data-slot="pagination-next"]'), 'fixed history pagination')
        await pagination.locator('[data-slot="pagination-next"]').click()
        await expect(page.locator('.diary-row')).toHaveCount(4)
        await expect(page.locator('.diary-row').first()).toContainText('日记21')
        await pagination.locator('[data-slot="pagination-previous"]').click()
        await page.locator('.diary-row').first().click()
        const dialog = page.getByRole('dialog', { name: '工作日记详情', exact: true })
        await largeDialog(page, dialog, row, `${id}-modern-diary`, 1120)
        await expect(dialog.locator('.agent-report-assessments .agent-report-stock')).toHaveCount(24)
        await expect(dialog.locator('.agent-report-assessments')).toContainText('已研判 23 / 24 · 未研判 1')
        await expect(dialog.locator('.agent-report-execution')).toContainText('已模拟买入')
        await expect(dialog.locator('.agent-report-decisions')).toContainText('观察管理')
        await expect(dialog.locator('.agent-report-rejects')).toContainText('未执行')
        await dialog.locator('.agent-report-assessments .agent-report-evidence summary').first().click()
        await expect(dialog.locator('.agent-report-assessments .agent-report-evidence code').first()).toBeVisible()
        await page.screenshot({ path: path.join(out, `diary-head-${id}-${width}.png`), fullPage: true })
        await revealTail(page, dialog.getByText('接续计划完整末尾', { exact: true }), row, `${id}-full-diary`)
        await inViewport(dialog.getByRole('heading', { name:'工作日记详情', exact:true }), 'Diary fixed title after scrolling')
        await inViewport(dialog.locator('[data-slot=dialog-close]'), 'Diary fixed close after scrolling')
        await page.screenshot({ path: path.join(out, `diary-${id}-${width}.png`), fullPage: true })
        await page.keyboard.press('Escape')
        await expect(dialog).toHaveCount(0)
        await page.locator('.diary-row').nth(1).click()
        await largeDialog(page, dialog, row, `${id}-legacy-diary`, 1120)
        const original = dialog.locator('.agent-report-original')
        await original.locator(':scope > summary').click()
        const oldBody = original.locator('section').filter({ has: page.getByRole('heading', { name: '原有正文', exact: true }) })
        await revealTail(page, oldBody.getByText('旧全文完整末尾', { exact: false }).first(), row, `${id}-legacy-body`, { requireScroll: false })
        await oldBody.locator('.agent-report-source summary').click()
        await expect(oldBody.locator('pre')).toContainText('旧全文完整末尾')
        assert.equal(await oldBody.locator('pre').evaluate(element => element.scrollHeight <= element.clientHeight + 2), true, 'Saved original source was truncated')
        await expect(dialog.locator('.agent-report-markdown img, .agent-report-markdown script')).toHaveCount(0)
        assert.equal(await page.evaluate(() => window.__diaryAttack), undefined, 'Legacy Markdown executed HTML')
        await page.screenshot({ path: path.join(out, `legacy-diary-${id}-${width}.png`), fullPage: true })
        await page.keyboard.press('Escape')
        await selectTab(nav, '历史日记')
        await expect(page.locator('.diary-row')).toHaveCount(20)
        await expect(page.locator('.history-pagination__total')).toHaveText('共 60 条')
        await pagination.locator('[data-slot="pagination-next"]').click()
        await expect(page.locator('.diary-row').first()).toContainText('日记21')
        await pagination.locator('[data-slot="pagination-next"]').click()
        await expect(page.locator('.diary-row').first()).toContainText('日记41')
        await revealTail(page, page.locator('.diary-row').last(), row, `${id}-full-history`)
        await expect(page.locator('.diary-row').last()).toContainText('日记60')
        assert.ok(row.history_queries.some(query => query.kind === 'runs' && !query.start && !query.end && query.offset === '40'), 'Full history retained the today filter')
        await page.screenshot({ path: path.join(out, `history-${id}-${width}.png`), fullPage: true })
        for (const [tab, label] of [['成交记录', 'trades'], ['资金流水', 'funding']]) {
          await selectTab(nav, tab)
          const last = width < 768 ? page.locator('.ledger-card').last() : page.locator('.ledger-table tbody tr').last()
          await expect(last).toBeVisible()
          if (label === 'trades') await expect(width < 768 ? page.locator('.ledger-card').first() : page.locator('.ledger-table tbody tr').first()).toContainText('隔离成交01')
          await revealTail(page, last, row, `${id}-${label}`)
          await inViewport(page.locator('.history-pagination [data-slot="pagination-next"]'), `${label} pagination`)
        }
        if (id === 'falcon-agent') {
          await selectTab(nav, '经验沉淀')
          const experience = page.getByRole('region', { name: '猎隼经验沉淀', exact: true })
          await expect(experience.locator('.falcon-learning__entry')).toHaveCount(20)
          for (const [title, marker] of [['择时经验12', '反例全文末尾-12'], ['判分建议08', '反例全文末尾-108']]) {
            const entry = experience.locator('.falcon-learning__entry').filter({ has: page.getByRole('heading', { name: title, exact: true }) })
            await revealTail(page, entry.locator('summary'), row, title)
            await entry.locator('summary').click()
            await revealTail(page, entry.getByText(marker, { exact: true }), row, `${title}-evidence`)
          }
          await page.screenshot({ path: path.join(out, `learning-${width}.png`), fullPage: true })
        }
        await layout(page, row, id)
        await page.screenshot({ path: path.join(out, `studio-${id}-${width}.png`), fullPage: true })
        await page.goto(`${base}/agents/${id}?tab=runs`, { waitUntil: 'networkidle' })
        await expect(page.getByRole('navigation', { name: '智能体工作区', exact: true }).getByRole('tab', { name: /^今日日记/ })).toHaveAttribute('aria-selected', 'true')
        await expect(page.locator('.diary-row')).toHaveCount(20)
        await layout(page, row, `${id}-diary-deep-link`)
        if (width === 1440) {
          await page.goto(`${base}/agents/${id}?tab=trades`, { waitUntil: 'networkidle' })
          await expect(page.getByRole('navigation', { name: '智能体工作区', exact: true }).getByRole('tab', { name: /^成交记录/ })).toHaveAttribute('aria-selected', 'true')
          await expect(page.locator('.ledger-table tbody tr')).toHaveCount(20)
          await layout(page, row, `${id}-trades-deep-link`)
        }
      })
      await check('guardian', async () => {
        await page.goto(`${base}/agents/guardian`, { waitUntil: 'networkidle' })
        await expect(page.getByRole('heading', { name: '天才交易员', exact: true })).toBeVisible()
        const nav = await workspaceNavigation(page, row, '交易员工作区', '.guardian-content-area')
        await selectTab(nav, '持仓股')
        const accountTabs = page.getByRole('tablist', { name: '账户明细', exact: true })
        const accountTabNames = await accountTabs.getByRole('tab').allTextContents()
        for (let index = 0; index < accountTabNames.length; index++) {
          const name = accountTabNames[index], tab = accountTabs.getByRole('tab').nth(index)
          await tab.scrollIntoViewIfNeeded(); await inViewport(tab, `guardian account tab ${name}`); await tab.click()
          await expect(tab).toHaveAttribute('aria-selected', 'true')
          await layout(page, row, `guardian ${name}`)
          if (name.startsWith('持仓') && !name.includes('曲线')) {
            const last = width < 768 ? page.locator('.mobile-position').last() : page.locator('.position-card').last()
            const button = last.getByRole('button', { name: /持仓详情/ })
            await revealTail(page, button, row, 'guardian-position-tail')
            await button.click()
            const dialog = page.getByRole('dialog', { name: '持仓详情', exact: true })
            await revealTail(page, dialog.getByText(positions.at(-1).last_review.reason, { exact: true }), row, 'guardian-position-detail')
            await dialog.locator('.record-details-footer').getByRole('button', { name: '关闭', exact: true }).click()
          }
          if (name.startsWith('经验沉淀')) {
            const last = page.locator('.experience-list li').last().getByRole('button')
            await revealTail(page, last, row, 'guardian-experience-tail')
            await last.click()
            const dialog = page.getByRole('dialog', { name: '经验详情', exact: true })
            await revealTail(page, dialog.getByText(guardian.experience.items.at(-1).validation_plan, { exact: true }), row, 'guardian-experience-detail', { requireScroll: false })
            await dialog.locator('.record-details-footer').getByRole('button', { name: '关闭', exact: true }).click()
          }
        }
        await selectTab(nav, '自选股')
        const pool = page.getByRole('region', { name: '股票池', exact: true })
        await expect(pool.locator('.pool-row')).toHaveCount(24)
        await revealTail(page, pool.locator('.pool-row').last(), row, 'guardian-watchlist')
        if (width < 768) await page.getByRole('tab', { name: '今日研判', exact: true }).click()
        const research = page.getByRole('complementary', { name: '交易研判', exact: true })
        await revealTail(page, research.getByText('完整报告末尾 · 离线证据', { exact: true }), row, 'guardian-research')
        await selectTab(nav, '复盘计划')
        const review = page.getByRole('region', { name: '复盘与计划', exact: true })
        await revealTail(page, review.getByText('完整报告末尾 · 离线证据', { exact: true }), row, 'guardian-report')
        await page.screenshot({ path: path.join(out, `guardian-report-${width}.png`), fullPage: true })
        await selectTab(nav, '对话')
        await expect(page.locator('.consult-panel')).toBeVisible()
        await expect(page.getByText('咨询全文末尾-12', { exact: true })).toBeVisible()
        await layout(page, row, 'guardian-consult')
        await page.screenshot({ path: path.join(out, `guardian-consult-${width}.png`), fullPage: true })
      })
      assert.equal(row.writes.length, 0, `Attempted writes: ${row.writes}`)
      assert.equal(row.externalRequests.length, 0, `External requests: ${row.externalRequests}`)
    } catch (error) { row.errors.push(String(error)) }
    finally { await context.close() }
  }
} finally { await browser.close(); if (server) await server.close() }
const sourceAfter = await productHashes()
if (JSON.stringify(sourceBefore) !== JSON.stringify(sourceAfter)) for (const row of results) row.errors.push('Product source changed during acceptance; run again against the final source')
await fs.writeFile(path.join(out, 'results.json'), `${JSON.stringify({ base, fixture: 'offline, GET-only, no models',
  completed_at: new Date().toISOString(), source_sha256: sourceAfter,source_sha256_before:sourceBefore, source_unchanged: JSON.stringify(sourceBefore) === JSON.stringify(sourceAfter),
  filters: { width: process.env.AGENT_WORKSPACE_UI_WIDTH || null, case: process.env.AGENT_WORKSPACE_UI_CASE || null }, results }, null, 2)}\n`)
for (const row of results) console.log(`${row.width}x${row.height}: ${row.checks.length} checks, ${row.errors.length} errors, ${row.writes.length} writes`)
if (results.some(row => row.errors.length)) {
  for (const row of results) for (const error of row.errors) console.error(`${row.width}x${row.height}: ${error}`)
  process.exitCode = 1
}

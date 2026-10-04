import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'
import { createServer } from 'vite'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

// Every API request is intercepted. Creating/configuring/running below changes only
// this in-memory fixture; the test never writes an account or calls a paid model.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = path.join(root, '../.local/falcon-agent-acceptance')
await fs.mkdir(out, { recursive: true })
const server = process.env.FALCON_UI_BASE ? null : await createServer({ root, server: { host: '127.0.0.1', port: 0, open: false } })
if (server) await server.listen()
const base = process.env.FALCON_UI_BASE || server.resolvedUrls.local[0].replace(/\/$/, '')
console.log(`Isolated preview: ${base}`)
const optionFixture = routeFixture(new URL(`${base}/api/ops/stock-agents/options`), 'agents').body
const legacyConfig = { ...optionFixture.templates.custom, name: '旧智能体', temporary_position_limit: 3 }
const falconConfig = {
  ...legacyConfig, name: '猎隼', kind: 'falcon', description: '量化与技能候选 · 自主超短择时',
  prompt: '仅研究系统产出，根据市场环境独立择时。', common_prompt: '超短为默认，不强制开盘买入。',
  premarket_prompt: '准备系统候选的进出场条件。', review_prompt: '沉淀当日进出场经验。',
  weekly_review_prompt: '总结整周经验，验证量化选股和判分的改进建议。',
  schedule: { ...legacyConfig.schedule, weekly_review_enabled: true, weekly_review_time: '20:30' },
}
const lesson = {
  id: 'timing-01', title: '弱环境等待确认', finding: '候选入选后，等待承接确认再决定进场。',
  conditions: '指数偏弱且候选分时承接尚未明确。', status: 'pending',
  evidence_refs: ['run:isolated-20260930:candidate:000001', 'run:isolated-20260929:candidate:000002'], sample_size: 2, sample_basis: 'observed',
  sample_definition: '两个系统候选的当日观察，不含假设收益。', positive_examples: [],
  counter_examples: [{ evidence_ref: 'run:isolated-20260929:candidate:000002', interpretation: '强势环境里等待也可能错失有效信号。' }],
  validation_plan: '继续观察不同市场环境下的承接确认，收集反例。', last_review_date: '2026-09-30',
}
const optimization = {
  ...lesson, id: 'scoring-01', title: '将市场环境纳入判分核验', finding: '静态高分不能直接推出进场时机。',
  target: 'scoring', proposed_change: '对照环境分层的候选表现，评估增加环境因子的价值。',
  status: 'supported', sample_basis: 'executed', sample_size: 3,
  evidence_refs: ['trade:isolated-01', 'trade:isolated-02', 'trade:isolated-03'],
  positive_examples: [{ evidence_ref: 'trade:isolated-01', interpretation: '环境因子与该次模拟成交结果一致。' }],
}
const templateAgent = routeFixture(new URL(`${base}/api/ops/stock-agents/smoke-agent`), 'agent-detail').body
const initial = { ...templateAgent, id: 'falcon-agent', config: { ...falconConfig, enabled: true }, latest_phase: 'weekly_review',
  latest_status: 'success', latest_at: '2026-09-30T12:31:00Z', latest_summary: '复盘已沉淀经验与待验证建议。',
  state: { ...templateAgent.state, falcon_learning: { lessons: [lesson], optimization_proposals: [optimization], last_review_date: '2026-09-30', last_review_phase: 'weekly_review' } },
  schedules: [{ phase: 'review', label: '晚间复盘', time: '20:00', enabled: true }, { phase: 'weekly_review', label: '周复盘', time: '周五 · 20:30', enabled: true }] }
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined, timeout: 30000 })
console.log('Isolated browser started')
const results = []
try {
  for (const [width, appearance] of [[1440, 'day'], [390, 'night']].filter(([width]) => !process.env.FALCON_UI_WIDTH || width === Number(process.env.FALCON_UI_WIDTH))) {
    const context = await browser.newContext({ viewport: { width, height: 960 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
    const page = await context.newPage()
    page.setDefaultTimeout(15000)
    page.setDefaultNavigationTimeout(30000)
    const row = { width, appearance, errors: [], writes: [], checks: [], providerRequests: [] }
    results.push(row)
    page.on('pageerror', error => row.errors.push(String(error)))
    let agent = structuredClone(initial)
    let created = null
    let run = null
    // Let Date.now() advance: Vue's event attachment guard ignores bubbling
    // handlers when a completely frozen clock equals their attachment time.
    await page.clock.install({ time: new Date('2026-09-30T12:31:00Z') })
    await page.addInitScript(value => localStorage.setItem('loci-appearance', value), appearance)
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const api = url.pathname.replace(/^\/api/, '')
      if (api.includes('providers')) row.providerRequests.push(api)
      const fulfill = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
      if (request.method() === 'POST' && api === '/ops/stock-agents') {
        created = request.postDataJSON(); row.writes.push('isolated create')
        agent = { ...agent, config: created }; return fulfill(agent)
      }
      if (request.method() === 'POST' && api === '/ops/stock-agents/falcon-agent/run') {
        run = request.postDataJSON(); row.writes.push(`isolated ${run.phase} run`)
        return fulfill({ status: 'queued', run_id: `isolated-${run.phase}` })
      }
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        row.errors.push(`Unexpected write ${request.method()} ${api}`); return route.abort()
      }
      if (api === '/ops/stock-agents/options') return fulfill({ ...optionFixture, templates: { custom: legacyConfig, leader: { ...legacyConfig, kind: 'leader' }, falcon: falconConfig } })
      if (api === '/providers' || api === '/ops/llm/providers') return fulfill([{ id: 1, name: 'isolated-provider', family: 'mock', is_active: true, models: ['isolated-model'] }])
      if (api === '/ops/stock-agents/falcon-agent') return fulfill(agent)
      if (api === '/ops/stock-agents/legacy-agent') return fulfill({ ...templateAgent, id: 'legacy-agent', config: legacyConfig })
      if (/^\/ops\/stock-agents\/(falcon-agent|legacy-agent)\/equity$/.test(api)) return fulfill({ items: [] })
      if (/^\/ops\/stock-agents\/(falcon-agent|legacy-agent)\/history$/.test(api)) return fulfill({ items: [], total: 0, offset: 0, limit: 20 })
      const fixture = routeFixture(url, 'agents')
      if (!fixture) row.errors.push(`Missing fixture ${api}`)
      return route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? { detail: '隔离夹具未提供' }) })
    })
    try {
      console.log(`Checking ${width}px ${appearance}`)
      await page.goto(`${base}/agents/falcon-agent`, { waitUntil: 'networkidle' })
      await expect(page.getByRole('heading', { name: '猎隼', exact: true })).toBeVisible()
      await page.getByRole('tab', { name: /^经验沉淀/ }).click()
      const learning = page.getByRole('region', { name: '猎隼经验沉淀' })
      await expect(learning.getByText('待验证', { exact: true })).toBeVisible()
      await expect(learning.getByText('有证据支持', { exact: true })).toBeVisible()
      await learning.locator('summary').first().click()
      await expect(learning.getByText(lesson.validation_plan, { exact: true }).first()).toBeVisible()
      await expect(learning.getByText(lesson.counter_examples[0].interpretation, { exact: true }).first()).toBeVisible()
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true)
      await page.screenshot({ path: path.join(out, `learning-${width}-${appearance}.png`), fullPage: true })
      row.checks.push('learning state/evidence/counterexample/validation and no horizontal overflow')

      await page.getByRole('button', { name: width < 768 ? '智能体操作' : '更多操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '运行周复盘', exact: true }).click()
      await page.getByRole('alertdialog', { name: '运行智能体', exact: true }).getByRole('button', { name: '运行一次', exact: true }).click()
      await expect.poll(() => run?.phase).toBe('weekly_review')
      row.checks.push('manual weekly review sends weekly_review')

      // Research is explicitly analysis-only and available at lunch; the ordinary
      // phase selector must still refuse a continuous-trading run at this time.
      await page.clock.setSystemTime(new Date('2026-09-30T04:00:00Z'))
      await page.getByRole('button', { name: width < 768 ? '智能体操作' : '更多操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '按当前时段运行一次', exact: true }).click()
      await expect(page.getByRole('alertdialog')).toHaveCount(0)
      assert.equal(run.phase, 'weekly_review')
      await page.getByRole('button', { name: width < 768 ? '智能体操作' : '更多操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '即时研判', exact: true }).click()
      const researchConfirm = page.getByRole('alertdialog', { name: '即时研判', exact: true })
      await expect(researchConfirm).toContainText('可随时执行')
      await expect(researchConfirm).toContainText('不执行模拟成交')
      await page.screenshot({ path: path.join(out, `research-confirm-${width}-${appearance}.png`), fullPage: true })
      await researchConfirm.getByRole('button', { name: '开始研判', exact: true }).click()
      await expect.poll(() => run?.phase).toBe('research')
      row.checks.push('lunch-time analysis-only research confirmation and exact research POST; ordinary trading phase remains gated')

      await page.goto(`${base}/agents`, { waitUntil: 'networkidle' })
      await page.getByRole('button', { name: '新建智能体', exact: true }).first().click()
      const drawer = page.getByRole('dialog', { name: '新建股票智能体', exact: true })
      await expect(drawer).toBeVisible()
      // The Sheet's enter transition also transfers focus. Complete that focus
      // transfer before opening another modal layer inside it with the mouse.
      await page.waitForTimeout(300)
      await drawer.getByRole('combobox', { name: '模型供应商', exact: true }).click()
      await page.getByRole('option', { name: 'isolated-provider', exact: true }).click()
      await drawer.getByRole('combobox', { name: '模型', exact: true }).click()
      await page.getByRole('option', { name: 'isolated-model', exact: true }).click()
      await drawer.getByRole('button', { name: /猎隼模板/ }).click()
      await expect(drawer.locator('#agent-config-name')).toHaveValue('猎隼')
      await expect(drawer.getByRole('combobox', { name: '模型供应商', exact: true })).toContainText('isolated-provider')
      await expect(drawer.getByRole('combobox', { name: '模型', exact: true })).toContainText('isolated-model')
      await expect(drawer.getByRole('button', { name: '参考工坊战法', exact: true })).toHaveCount(0)
      await drawer.getByRole('tab', { name: '周复盘', exact: true }).click()
      await expect(drawer.getByRole('textbox', { name: '周复盘提示词', exact: true })).toHaveValue(falconConfig.weekly_review_prompt)
      await page.screenshot({ path: path.join(out, `template-${width}-${appearance}.png`), fullPage: true })
      await drawer.getByRole('tab', { name: '账户与日程', exact: true }).click()
      await expect(drawer.locator('#agent-config-weekly-enabled')).toHaveAttribute('aria-checked', 'true')
      await expect(drawer.getByRole('combobox', { name: '周五复盘时间', exact: true })).toContainText('20:30')
      await drawer.locator('#agent-config-weekly-enabled').click()
      await expect(drawer.getByRole('combobox', { name: '周五复盘时间', exact: true })).toBeDisabled()
      await drawer.locator('#agent-config-weekly-enabled').click()
      await drawer.getByRole('combobox', { name: '周五复盘时间', exact: true }).click()
      await page.getByRole('option', { name: '20:35', exact: true }).click()
      await drawer.getByRole('button', { name: '创建智能体', exact: true }).click()
      await expect.poll(() => created?.kind).toBe('falcon')
      assert.equal(created.provider, 'isolated-provider')
      assert.equal(created.model, 'isolated-model')
      assert.equal(created.weekly_review_prompt, falconConfig.weekly_review_prompt)
      assert.equal(created.schedule.weekly_review_enabled, true)
      assert.equal(created.schedule.weekly_review_time, '20:35')
      assert.equal(created.enabled, false)
      row.checks.push('falcon template/provider preservation/prompt/schedule and paused create payload')

      await page.goto(`${base}/agents/legacy-agent`, { waitUntil: 'networkidle' })
      if (width < 768) {
        await page.getByRole('button', { name: '智能体操作', exact: true }).click()
        await page.getByRole('menuitem', { name: '设置', exact: true }).click()
      } else await page.getByRole('button', { name: '设置', exact: true }).click()
      const legacyDrawer = page.getByRole('dialog', { name: '智能体设置', exact: true })
      await legacyDrawer.getByRole('tab', { name: '账户与日程', exact: true }).click()
      await expect(legacyDrawer.locator('#agent-config-weekly-enabled')).toHaveAttribute('aria-checked', 'false')
      await expect(legacyDrawer.getByRole('combobox', { name: '周五复盘时间', exact: true })).toBeDisabled()
      await expect(legacyDrawer.getByRole('combobox', { name: '周五复盘时间', exact: true })).toContainText('20:30')
      await legacyDrawer.getByRole('button', { name: '取消', exact: true }).click()
      await expect(legacyDrawer).not.toBeVisible()
      await expect(page.getByRole('alertdialog')).toHaveCount(0)
      row.checks.push('legacy config weekly defaults off and normalized baseline stays clean')
      assert.deepEqual(row.errors, [])
      row.ok = true
    } catch (error) {
      row.ok = false; row.errors.push(String(error))
      await page.screenshot({ path: path.join(out, `failure-${width}.png`), fullPage: true })
    } finally {
      await context.close()
      console.log(JSON.stringify(row))
      await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results, null, 2))
    }
  }
} finally { await browser.close(); await server?.close() }
console.log(`Evidence: ${out}`)
if (results.some(row => !row.ok)) process.exitCode = 1

/** UI regression acceptance; all API traffic is intercepted.
 * Run from frontend: node e2e/ui-finish.mjs
 * UI_AUDIT_WIDTHS=1440,980,640,390; UI_AUDIT_HEIGHT=900
 * UI_AUDIT_THEMES=night,day,paper,ink; UI_AUDIT_SCENES selects comma-separated scenes.
 * AUDIT_BASE points at a LOCAL production-build preview; omitted starts Vite dev.
 */
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createServer } from 'vite'
import { FIXED_NOW } from './pulse-mocks.mjs'
import { uiPayloadFor } from './ui-finish-mocks.mjs'

if (!process.env.PLAYWRIGHT_BROWSERS_PATH && existsSync('.pw-browsers')) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = resolve('.pw-browsers')
}
const { chromium } = await import('playwright')
const phase = process.env.UI_AUDIT_PHASE || 'verified'
const out = `artifacts/ui-finish/${phase}`
const widths = (process.env.UI_AUDIT_WIDTHS || '1440,980,640,390').split(',').map(Number)
const height = Number(process.env.UI_AUDIT_HEIGHT || 900)
const themes = (process.env.UI_AUDIT_THEMES || 'night').split(',')
const requested = (process.env.UI_AUDIT_SCENES || '').split(',').filter(Boolean)
const scenes = [
  'backtest', 'backtest-busy', 'backtest-cost', 'backtest-horizon', 'backtest-trade',
  'workbench', 'workbench-assist', 'workbench-dock', 'assistant', 'assistant-empty',
  'assistant-sidebars', 'settings',
].filter(name => !requested.length || requested.includes(name))
assert(scenes.length && widths.every(w => w > 0) && height > 0, 'Invalid audit selection')
mkdirSync(out, { recursive: true })
let server
let browser
const results = []
const base = process.env.AUDIT_BASE || 'http://127.0.0.1:4186'
assert(['127.0.0.1', 'localhost', '[::1]'].includes(new URL(base).hostname), 'Audit only a local preview')

async function inspect(page) {
  return page.evaluate(() => {
    const root = document.documentElement
    const visible = el => Boolean(el.getClientRects().length && el.getBoundingClientRect().height)
    const rect = el => {
      const r = el.getBoundingClientRect()
      return { selector: typeof el.className === 'string' ? el.className : el.tagName, x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) }
    }
    const surfaceSelectors = '.page-host, .bt-rail, .workbench-shell, .editor-stage, .editor-stage__status, .report-dock--open, .assistant-panel, .assistant-panel__stage, .assistant-panel__composer, .assistant-session-rail, .assistant-task-sidebar, .el-dialog'
    const dialog = document.querySelector('.assistant-dialog')?.getBoundingClientRect()
    const panel = document.querySelector('.assistant-panel')?.getBoundingClientRect()
    const editor = document.querySelector('.editor-stage')?.getBoundingClientRect()
    const status = document.querySelector('.editor-stage__status')?.getBoundingClientRect()
    return {
      document: { width: root.clientWidth, scrollWidth: root.scrollWidth, height: root.clientHeight, scrollHeight: root.scrollHeight },
      surfaces: [...document.querySelectorAll(surfaceSelectors)].filter(visible).map(rect),
      overflows: [...document.querySelectorAll('.bt-rail, .bt-result, .workbench-shell, .assistant-panel__stage, .assistant-settings')].filter(visible).filter(el => el.scrollWidth > el.clientWidth + 2).map(el => ({ ...rect(el), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth })),
      assistantBottomGap: dialog && panel ? Math.round(dialog.bottom - panel.bottom) : null,
      editorStatusClipped: editor && status ? status.bottom > editor.bottom + 2 || status.bottom > innerHeight : false,
    }
  })
}

async function openAssistant(page, scene) {
  await page.getByRole('button', { name: '打开 Loci 助手', exact: true }).click({ timeout: 30000 })
  await page.locator('.assistant-panel').waitFor()
  if (scene !== 'assistant-empty') await page.getByText('验收示例，不是投资建议', { exact: true }).waitFor()
  else await page.locator('.assistant-empty').waitFor()
}

try {
  if (!process.env.AUDIT_BASE) {
    server = await createServer({ server: { host: '127.0.0.1', port: 4186, strictPort: true, open: false } })
    await server.listen()
  }
  browser = await chromium.launch({ channel: 'chromium', timeout: 20000 })
  for (const theme of themes) for (const width of widths) for (const scene of scenes) {
    const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' })
    page.setDefaultTimeout(10000)
    const errors = []
    const checks = []
    let releaseBacktest
    const holdBacktest = new Promise(resolve => { releaseBacktest = resolve })
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', msg => {
      if (/Failed to resolve component|Unhandled error during/.test(msg.text())) errors.push(msg.text())
    })
    await page.clock.setFixedTime(FIXED_NOW)
    await page.addInitScript(({ theme }) => {
      localStorage.setItem('loci-appearance', theme)
      localStorage.setItem('loci-primary', 'blue')
    }, { theme })
    // Do not glob **/api/**: that also intercepts Vite's /src/shared/api/*.ts.
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const path = new URL(route.request().url()).pathname
      if (scene === 'backtest-busy' && path.endsWith('/backtest')) {
        await holdBacktest
        await route.abort().catch(() => {})
        return
      }
      let request = {}
      try { request = route.request().postDataJSON() || {} } catch { /* GET or a non-JSON request */ }
      await route.fulfill({ json: uiPayloadFor(route.request().url(), scene, request) }).catch(() => {})
    })
    const file = `${out}/${scene}-${theme}-${width}x${height}`
    try {
      const path = scene.startsWith('backtest') ? '/quant?tab=backtest' : scene.startsWith('workbench') ? '/strategy-converter' : '/'
      await page.goto(base + path, { waitUntil: 'domcontentloaded', timeout: 45000 })
      await page.locator('.page-host').waitFor()
      if (scene.startsWith('backtest')) {
        await page.locator('.bt').waitFor()
        if (['backtest-cost', 'backtest-trade'].includes(scene)) {
          await page.locator('.bt-rail .el-radio-button').filter({ hasText: '成交回测' }).click()
          assert(await page.getByRole('radio', { name: '成交回测', exact: true }).isChecked())
        }
        if (scene === 'backtest-cost') {
          await page.getByRole('button', { name: '成本参数', exact: true }).click()
          await page.locator('.bt-cost').waitFor()
        }
        if (['backtest-busy', 'backtest-horizon', 'backtest-trade'].includes(scene)) {
          await page.getByRole('button', { name: '跑回测', exact: true }).click()
          if (scene === 'backtest-busy') {
            await page.locator('.bt[aria-busy="true"]').waitFor()
            await page.getByRole('button', { name: '停止等待', exact: true }).click({ trial: true })
            checks.push('stop-action-reachable')
          } else {
            await page.locator('.bt-result').waitFor()
            if (scene === 'backtest-trade') await page.locator('.tr').waitFor()
            else await page.locator('.bt-horizons').waitFor()
            checks.push('result-rendered')
          }
        }
      }
      if (scene.startsWith('workbench')) {
        await page.locator('.monaco-editor').waitFor({ timeout: 30000 })
        if (scene !== 'workbench') {
          await page.getByRole('button', { name: '展开助手', exact: true }).click()
          await page.locator('#strategy-copilot').waitFor()
        }
        if (scene === 'workbench-dock') {
          await page.getByRole('textbox', { name: '公式名称', exact: true }).fill('界面验收公式')
          await page.getByRole('tab', { name: '策略', exact: true }).click()
          await page.getByPlaceholder('说明入选逻辑、适用阶段、风险与禁用场景。').fill('仅用于界面验收，不作为生产策略。')
          await page.getByRole('tab', { name: '公式', exact: true }).click()
          await page.getByRole('button', { name: '试跑', exact: true }).click()
          await page.locator('.report-dock--open').waitFor()
          await page.locator('.report-dock .el-radio-button').filter({ hasText: '诊断' }).click()
          await page.locator('.report-dock').getByText('无诊断', { exact: true }).waitFor()
          await page.locator('.report-dock .el-radio-button').filter({ hasText: '回测' }).click()
          await page.locator('.report-dock .bt').waitFor()
          checks.push('dock-empty-state-and-backtest')
        }
      }
      if (scene.startsWith('assistant') || scene === 'settings') {
        await openAssistant(page, scene)
        if (scene === 'assistant-sidebars') {
          const expandHistory = page.getByRole('button', { name: '展开历史对话', exact: true })
          if (await expandHistory.isVisible()) await expandHistory.click()
          await page.getByRole('button', { name: '展开任务侧栏', exact: true }).click()
          await page.getByRole('button', { name: '收起任务侧栏', exact: true }).waitFor()
          if (width <= 1100) {
            assert(await page.getByRole('button', { name: '展开历史对话', exact: true }).isVisible(), 'Overlay sidebars must not hide each other')
            const stage = await page.locator('.assistant-panel__stage').boundingBox()
            assert(stage.width >= width * 0.7, `Dialogue squeezed to ${stage.width}px`)
          }
          checks.push('sidebars-preserve-dialogue-width')
        }
        if (scene === 'settings') {
          await page.getByRole('button', { name: '助手设置', exact: true }).first().click()
          await page.locator('.assistant-settings-dialog').waitFor()
          await page.getByRole('textbox', { name: '关于你', exact: true }).waitFor()
        }
      }
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(250) // EP/Monaco/ECharts defer a layout pass after mounting.
      const layout = await inspect(page)
      await page.screenshot({ path: `${file}.png` })
      if (scene === 'backtest-busy') {
        await page.getByRole('button', { name: '停止等待', exact: true }).click()
        await page.locator('.bt[aria-busy="false"]').waitFor()
        checks.push('stop-aborts-wait')
      }
      if (scene === 'workbench-dock') {
        await page.getByRole('button', { name: '收起结果面板', exact: true }).click()
        await page.locator('.report-dock--open').waitFor({ state: 'hidden' })
        checks.push('dock-collapses')
      }
      if (scene === 'settings') {
        await page.getByRole('tab', { name: '记忆', exact: true }).click()
        await page.getByRole('textbox', { name: '工作记忆文档', exact: true }).waitFor()
        await page.screenshot({ path: `${file}-memory.png` })
        await page.keyboard.press('Escape')
        await page.locator('.assistant-settings-dialog').waitFor({ state: 'hidden' })
        assert(await page.locator('.assistant-panel').isVisible(), 'Closing settings must not close the assistant')
        checks.push('settings-tabs-and-escape')
      }
      assert(layout.document.scrollWidth <= layout.document.width + 2, 'Document horizontal overflow')
      assert(layout.document.scrollHeight <= layout.document.height + 2, 'Document vertical overflow')
      assert.equal(layout.overflows.length, 0, `Surface overflow: ${JSON.stringify(layout.overflows)}`)
      assert(layout.assistantBottomGap === null || Math.abs(layout.assistantBottomGap) <= 2, `Assistant leaves ${layout.assistantBottomGap}px unused`)
      assert(!layout.editorStatusClipped, 'Editor status is clipped')
      assert.equal(errors.length, 0, `Runtime errors: ${errors.join('; ')}`)
      results.push({ scene, theme, width, height, errors, checks, ...layout })
      console.log(`PASS ${scene} ${theme} ${width}x${height} ${checks.join(',')}`)
    } catch (error) {
      results.push({ scene, theme, width, height, errors, checks, failure: error.message, layout: await inspect(page).catch(() => null) })
      await page.screenshot({ path: `${file}-error.png` }).catch(() => {})
      console.log(`FAIL ${scene} ${theme} ${width}x${height} ${error.message}`)
      console.log((await page.locator('body').innerText()).slice(0, 1800))
    } finally {
      releaseBacktest()
      await page.close()
      writeFileSync(`${out}/report.json`, JSON.stringify(results, null, 2))
    }
  }
} finally {
  await browser?.close()
  await server?.close()
  writeFileSync(`${out}/report.json`, JSON.stringify(results, null, 2))
}
const failures = results.filter(r => r.failure)
writeFileSync(`${out}/complete.json`, JSON.stringify({ total: results.length, failed: failures.length }))
console.log(`UI acceptance: ${results.length - failures.length}/${results.length}`)
if (failures.length) process.exitCode = 1

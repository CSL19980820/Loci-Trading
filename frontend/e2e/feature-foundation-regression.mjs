import { chromium, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const out = '../.local/shadcn-foundation-20260922'
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = [], apiCalls = [], pages = []
const errors = new WeakMap()
async function open(view, width=1440) {
 const page = await browser.newPage({ viewport: { width, height: 940 } }); pages.push(page)
 page.setDefaultTimeout(12000); errors.set(page, [])
 page.on('pageerror', error => errors.get(page).push(String(error)))
 page.on('console', message => { if (message.type()==='error' || /Failed to resolve component/.test(message.text())) errors.get(page).push(message.text()) })
 await page.route(url => url.pathname.startsWith('/api/'), async route => {
  const path = new URL(route.request().url()).pathname
  apiCalls.push({ path, method: route.request().method() })
  let value = []
  if (path.endsWith('/skills')) value = [{ slug: 'fixture', name: '测试技能', description: '隔离测试技能' }]
  else if (path.endsWith('/screen-skills/catalog')) value = { fields: [], functions: [], snippets: [], operators: [], categories: [] }
  else if (path.endsWith('/universe/stats')) value = { total: 0, boards: {}, industries: [] }
  else if (path.includes('/screen/run')) value = { running: false, runs: [], strategies: {} }
  else if (path.includes('/research/')) value = { items: [], total: 0, resolved: null }
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) })
 })
 await page.goto(`http://127.0.0.1:5174/e2e/fixtures/feature-foundation.html?view=${view}`, { waitUntil: 'networkidle' })
 return page
}
async function check(name, test) {
 try { const page = await test(); assert.deepEqual(errors.get(page), []); results.push({ name, ok: true }) }
 catch (error) { results.push({ name, ok: false, error: String(error), browserErrors: pages.map(page=>errors.get(page)) }); console.error(name, String(error)) }
 finally { await Promise.all(pages.splice(0).map(page=>page.close())) }
}
try {
 await check('assistant-dialog-retention-escape-and-slash', async () => {
  const page = await open('assistant', 1366)
  await page.getByTestId('open-assistant').click()
  const input = page.getByRole('textbox', { name: '消息内容' })
  await expect(input).toBeFocused()
  await input.fill('关闭后保留的草稿')
  await page.getByRole('button', { name: '关闭助手', exact: true }).click()
  await expect(page.getByTestId('assistant-overlay')).not.toBeVisible()
  await expect(page.getByTestId('open-assistant')).toBeFocused()
  await page.getByTestId('outside-control').click()
  await page.evaluate(() => window.__featureFoundation.messages.value.push({ id: 'background', role: 'assistant', status: 'streaming', content: '关闭后继续收到的回复' }))
  assert.notEqual(await page.evaluate(() => getComputedStyle(document.body).pointerEvents), 'none')
  await page.getByTestId('open-assistant').click()
  await expect(input).toHaveValue('关闭后保留的草稿')
  await expect(page.getByText('关闭后继续收到的回复', { exact: true })).toBeVisible()
  await page.getByTestId('assistant-settings').click()
  await expect(page.getByRole('dialog', { name: '测试子设置' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '测试子设置' })).not.toBeVisible()
  await expect(page.getByTestId('assistant-overlay')).toBeVisible()
  await input.fill('/')
  await expect(page.getByTestId('assistant-slash-menu')).toBeVisible()
  await input.press('Escape')
  await expect(page.getByTestId('assistant-slash-menu')).toHaveCount(0)
  await expect(page.getByTestId('assistant-overlay')).toBeVisible()
  await input.fill('/')
  await input.press('ArrowDown')
  assert(await input.evaluate(el => Boolean(document.getElementById(el.getAttribute('aria-activedescendant')))))
  await input.press('Tab')
  await expect(page.getByTestId('assistant-active-skill')).toContainText('/fixture')
  await page.getByRole('button', { name: '取消技能 /fixture', exact: true }).click()
  await input.fill('/comp')
  await expect(page.getByRole('option')).toHaveCount(1)
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  assert.deepEqual(await page.evaluate(() => window.__featureFoundation.commands.value), [])
  await input.press('Enter')
  assert.deepEqual(await page.evaluate(() => window.__featureFoundation.commands.value), ['compact'])
  assert.deepEqual(await page.evaluate(() => window.__featureFoundation.sends.value), [])
  await input.fill('草稿'); await input.press('Shift+Enter'); await input.press('x')
  assert((await input.inputValue()).includes('\n'))
  await page.screenshot({ path: `${out}/feature-assistant-desktop.png`, fullPage: true, animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('assistant-overlay')).not.toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByTestId('open-assistant').click()
  await expect(input).toHaveValue('草稿\nx')
  await expect.poll(async () => (await page.getByTestId('assistant-overlay').boundingBox()).y).toBeLessThan(1)
  await expect.poll(async () => (await page.getByTestId('assistant-overlay').boundingBox()).height).toBeGreaterThan(840)
  await page.getByTestId('assistant-context-usage-trigger').click()
  const usage = page.getByRole('dialog', { name: '上下文用量', exact: true })
  await expect(usage).toHaveCount(1)
  await expect(usage).toBeVisible()
  const usageBox = await usage.boundingBox()
  assert(usageBox.x >= 0 && usageBox.x + usageBox.width <= 391)
  await page.screenshot({ path: `${out}/feature-context-usage-mobile.png`, fullPage: true, animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(usage).not.toBeVisible()
  await expect(page.getByTestId('assistant-overlay')).toBeVisible()
  await page.screenshot({ path: `${out}/feature-assistant-mobile.png`, fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '关闭助手', exact: true }).click()
  await page.getByTestId('outside-control').click()
  return page
 })
 await check('research-cards', async () => {
  const page = await open('research')
  await expect(page.locator('[data-slot=card]')).toHaveCount(2)
  await expect(page.getByText('可查看', { exact: true })).toBeVisible()
  await expect(page.getByText('模拟数据尚未补全', { exact: true })).toBeVisible()
  await expect(page.getByText('历史数据', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${out}/feature-research-desktop.png`, fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: `${out}/feature-research-mobile.png`, fullPage: true, animations: 'disabled' })
  return page
 })
 await check('multi-question-confirmation', async () => {
  const page = await open('confirm', 390)
  await page.getByTestId('assistant-confirm-submit').click()
  await expect(page.getByTestId('assistant-confirm-error')).toBeVisible()
  await page.getByRole('radio', { name: /A股/ }).click()
  assert.equal(await page.evaluate(() => window.__featureFoundation.replies.value.length), 0)
  await page.getByRole('textbox', { name: '补充说明' }).fill('只做观察')
  await page.getByTestId('assistant-confirm-submit').click()
  assert.deepEqual(await page.evaluate(() => window.__featureFoundation.replies.value), ['1. [scope] 选择市场 → A股\n2. [reason] 补充说明 → 只做观察'])
  await page.screenshot({ path: `${out}/feature-confirm-mobile.png`, fullPage: true, animations: 'disabled' })
  return page
 })
 await check('factor-citation-tags', async () => {
  const page = await open('tags', 390)
  const factors = page.getByRole('textbox', { name: '因子清单', exact: true })
  await factors.fill('RSI'); await factors.press('Enter')
  await page.getByRole('button', { name: '移除因子 VOL', exact: true }).click()
  assert.equal(await page.evaluate(() => window.__featureFoundation.draft.factorsText), 'MA, RSI')
  const citations = page.getByRole('textbox', { name: '引用编号', exact: true })
  await citations.fill('ref-c'); await citations.press('Tab')
  assert.equal(await page.evaluate(() => window.__featureFoundation.draft.logic[0].citationsText), 'ref-a, ref-b, ref-c')
  await page.screenshot({ path: `${out}/feature-tags-mobile.png`, fullPage: true, animations: 'disabled' })
  return page
 })
 await check('workbench-resize-keyboard-persistence-mobile', async () => {
  const page = await open('workbench')
  const handle = page.getByRole('separator', { name: '调整编辑器与结果区宽度' })
  await expect(handle).toBeVisible()
  const before = await page.locator('.workbench-editor-pane').boundingBox()
  await handle.focus(); await handle.press('ArrowRight'); await handle.press('ArrowRight')
  await expect.poll(async () => (await page.locator('.workbench-editor-pane').boundingBox()).width).toBeGreaterThan(before.width + 10)
  const keyboardWidth = (await page.locator('.workbench-editor-pane').boundingBox()).width
  const grip = await handle.boundingBox()
  await page.mouse.move(grip.x + grip.width / 2, grip.y + 80)
  await page.mouse.down(); await page.mouse.move(grip.x - 70, grip.y + 80, { steps: 8 }); await page.mouse.up()
  await expect.poll(async () => (await page.locator('.workbench-editor-pane').boundingBox()).width).toBeLessThan(keyboardWidth - 30)
  const resized = await page.locator('.workbench-editor-pane').boundingBox()
  await page.screenshot({ path: `${out}/feature-workbench-resized-desktop.png`, fullPage: true, animations: 'disabled' })
  await page.waitForTimeout(200); await page.reload({ waitUntil: 'networkidle' })
  await expect.poll(async () => Math.abs((await page.locator('.workbench-editor-pane').boundingBox()).width - resized.width)).toBeLessThan(5)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(handle).toHaveCount(0)
  await expect(page.locator('.workbench-editor-pane')).toBeVisible()
  await page.getByRole('tab', { name: '结果', exact: true }).click()
  await expect(page.locator('.workbench-result-pane')).toBeVisible()
  await expect(page.locator('.workbench-editor-pane')).not.toBeVisible()
  await page.getByRole('tab', { name: '编辑器', exact: true }).click()
  await expect(page.locator('.workbench-editor-pane')).toBeVisible()
  await page.screenshot({ path: `${out}/feature-workbench-mobile.png`, fullPage: true, animations: 'disabled' })
  return page
 })
} finally {
 await browser.close()
 await fs.writeFile(`${out}/feature-results.json`, JSON.stringify({ results, apiCalls }, null, 2))
}
console.log(JSON.stringify(results, null, 2))
if (results.some(result => !result.ok)) process.exitCode = 1

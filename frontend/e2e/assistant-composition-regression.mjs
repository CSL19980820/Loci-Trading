import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'

const out = process.env.E2E_ARTIFACT_DIR || '../.local/assistant-nav-refinement-20260922'
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [390, 1440]) for (const theme of ['day', 'night']) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, hasTouch: width === 390 })
    page.setDefaultTimeout(10000)
    const errors = []; const result = { width, theme, ok: false, errors }; results.push(result)
    page.on('pageerror', e => errors.push(String(e)))
    await page.route(url => url.pathname.startsWith('/api/'), route => route.fulfill({ json: [] }))
    try {
      await page.goto(`http://127.0.0.1:5174/e2e/fixtures/assistant-rich.html?theme=${theme}`)
      await page.getByTestId('open-rich').click()
      const footer = page.locator('[data-slot="message-footer"]').first()
      await expect(footer.getByRole('button', { name: '复制', exact: true })).toBeVisible()
      await expect(footer.getByRole('button', { name: '重跑', exact: true })).toBeVisible()
      const thinking = page.getByTestId('assistant-thinking').getByRole('button')
      await expect(thinking).toHaveAttribute('aria-expanded', 'false')
      await thinking.focus(); await page.keyboard.press('Enter')
      await expect(thinking).toHaveAttribute('aria-expanded', 'true')
      await thinking.click()
      const tools = page.getByTestId('assistant-receipts').getByRole('button').first()
      await tools.click()
      await expect(page.getByTestId('assistant-receipt-row').first()).toBeVisible()
      assert.equal(await page.locator('button button').count(), 0, 'Nested buttons must not be introduced by as-child composition')
      await tools.click()
      const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64')
      await page.locator('input[type="file"]').setInputFiles(Array.from({ length: 4 }, (_, i) => ({ name: `fixture-${i}.png`, mimeType: 'image/png', buffer: png })))
      const previews = page.getByTestId('assistant-image-previews')
      await expect(previews.locator('[data-slot="attachment"]')).toHaveCount(4)
      await expect(previews.locator('[data-slot="attachment-action"]')).toHaveCount(4)
      result.attachments = await previews.locator('[data-slot="attachment"]').evaluateAll(nodes => nodes.map(node => ({ width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height, imageWidth: node.querySelector('img').getBoundingClientRect().width })))
      assert(result.attachments.every(a => a.width >= 56 && a.width <= 70 && a.imageWidth > 40))
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      await page.screenshot({ path: `${out}/assistant-${width}-${theme}.png` })
      await previews.getByRole('button', { name: '移除第 2 张图片', exact: true }).click()
      await expect(previews.locator('[data-slot="attachment"]')).toHaveCount(3)
      // Execution phases are distinct from genuine provider reasoning and answer text.
      await page.evaluate(() => {
        window.__assistantRich.messages.value = [{ id: 'phase', role: 'assistant', status: 'streaming', content: '', thinking: '', progress: { phase: 'preparing', label: '读取咨询背景' } }]
        window.__assistantRich.busy.value = true
      })
      await expect(page.getByTestId('assistant-thinking')).toContainText('读取咨询背景')
      await expect(page.getByTestId('assistant-thinking').getByRole('button')).toBeDisabled()
      await expect(page.locator('.assistant-turn__answer')).toHaveCount(0)
      await page.evaluate(() => Object.assign(window.__assistantRich.messages.value[0], { thinking: '这是协议夹具提供的思考片段。', progress: { phase: 'thinking' } }))
      await expect(page.getByTestId('assistant-thinking')).toHaveAttribute('data-status', 'thinking')
      await expect(page.getByTestId('assistant-thinking').getByRole('button')).toBeEnabled()
      await page.evaluate(() => {
        Object.assign(window.__assistantRich.messages.value[0], { status: 'error', progress: { phase: 'error' }, warnings: ['隔离测试中断'] })
        window.__assistantRich.busy.value = false
      })
      await expect(page.getByTestId('assistant-thinking')).toContainText('思考已中断')
      await expect(page.getByTestId('assistant-thinking')).toHaveAttribute('data-status', 'error')
      await expect(page.getByTestId('assistant-thinking')).toHaveAttribute('data-expanded', 'false')
      assert.deepEqual(errors, [])
      result.ok = true
    } catch (e) { result.failure = String(e) }
    finally { await page.close(); console.log(JSON.stringify(result)) }
  }
} finally {
  await browser.close()
  await fs.writeFile(`${out}/assistant-composition-results.json`, JSON.stringify(results, null, 2))
}
if (results.some(r => !r.ok)) process.exitCode = 1

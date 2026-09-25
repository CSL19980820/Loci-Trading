import { chromium, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const out = '../.local/assistant-visual-fix-20260922'
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [390, 600, 1440]) for (const theme of ['day', 'night']) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, hasTouch: width <= 600, reducedMotion: 'reduce' })
    const errors = [], row = { width, theme, ok: false, errors }; results.push(row)
    page.on('pageerror', e => errors.push(String(e)))
    page.on('console', m => { if (m.type() === 'error' || /Failed to resolve component|Unhandled error/.test(m.text())) errors.push(m.text()) })
    await page.route(url => url.pathname.startsWith('/api/'), r => r.fulfill({ contentType: 'application/json', body: '[]' }))
    try {
      await page.goto(`http://127.0.0.1:5174/e2e/fixtures/assistant-rich.html?theme=${theme}`, { waitUntil: 'networkidle' })
      await page.getByTestId('open-rich').click()
      const viewport = page.getByRole('region', { name: '对话记录' })
      const scroller = page.locator('.assistant-conversation__viewport')
      await expect(page.locator('.assistant-turn__answer')).toContainText('结论：先核对趋势')
      await expect(page.locator('.assistant-artifact-host')).toHaveCount(0)
      await expect(page.getByRole('button', { name: /图表与数据 · 3 项/ })).toHaveAttribute('aria-expanded', 'false')
      await expect(page.getByRole('combobox', { name: '思考强度：中' })).toHaveText('推理：中')
      row.geometry = await page.evaluate(() => {
        const user = document.querySelector('.assistant-user-bubble'), text = user.querySelector('p'), answer = document.querySelector('.assistant-turn__answer'), panel = document.querySelector('.assistant-panel')
        return { textColor: getComputedStyle(text).color, bubbleColor: getComputedStyle(user).backgroundColor, answerWidth: answer.getBoundingClientRect().width, panelWidth: panel.getBoundingClientRect().width, overflow: document.documentElement.scrollWidth > innerWidth + 1 }
      })
      assert(!row.geometry.overflow)
      assert(row.geometry.answerWidth / row.geometry.panelWidth > .88, 'Answer should not lose width to an avatar column')
      await scroller.evaluate(el => { el.scrollTop = 0 })
      await page.screenshot({ path: `${out}/rich-${theme}-${width}-answer.png` })
      await page.getByRole('button', { name: /图表与数据 · 3 项/ }).click()
      await expect(page.locator('.assistant-kline-card')).toHaveCount(3)
      await page.locator('.assistant-kline-card').first().scrollIntoViewIfNeeded()
      await expect(page.locator('.assistant-kline-card canvas').first()).toBeVisible()
      await page.screenshot({ path: `${out}/rich-${theme}-${width}-chart.png` })
      // While reading old content, an incoming streaming append must not pull the viewport down.
      const rect = await scroller.boundingBox(); await page.mouse.move(rect.x + 2, rect.y + 10)
      await page.mouse.wheel(0, -5000)
      await page.waitForTimeout(500)
      const before = await scroller.evaluate(el => el.scrollTop)
      await page.evaluate(() => { window.__assistantRich.messages.value.push({ id: 'later', role: 'assistant', status: 'streaming', content: '新增流式消息' }); window.__assistantRich.busy.value = true })
      await page.waitForTimeout(300)
      row.scroll = { before, after: await scroller.evaluate(el => el.scrollTop), state: await scroller.getAttribute('data-scrollable') }; assert(Math.abs(row.scroll.after - before) < 5, 'Incoming message stole history scroll position: '+JSON.stringify(row.scroll))
      assert.deepEqual(errors, [])
      row.ok = true
    } catch (e) { row.failure = String(e); console.error(row.failure) }
    finally { await page.close(); console.log(JSON.stringify(row)) }
  }
} finally { await browser.close(); await fs.writeFile(`${out}/rich-results.json`, JSON.stringify(results, null, 2)) }
if (results.some(r => !r.ok)) process.exitCode = 1

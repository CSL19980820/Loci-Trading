import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.local/shadcn-deploy-20260922', `kline-scroll-${Date.now()}`)
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch()
const results = []
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, hasTouch: true, reducedMotion: 'reduce' })
    const row = { width, errors: [] }; results.push(row)
    page.on('pageerror', error => row.errors.push(String(error)))
    await page.route(url => url.pathname.startsWith('/api/'), route => route.fulfill({ contentType: 'application/json', body: '[]' }))
    await page.goto('http://127.0.0.1:5174/e2e/fixtures/assistant-rich.html?theme=day', { waitUntil: 'networkidle' })
    await page.getByTestId('open-rich').click()
    await page.getByRole('button', { name: /图表与数据 · 3 项/ }).click()
    const chart = page.locator('.assistant-kline-card canvas').first()
    await expect(chart).toBeVisible()
    const scroller = page.locator('.assistant-conversation__viewport')
    const position = async () => {
      await chart.scrollIntoViewIfNeeded()
      await page.waitForTimeout(250)
      const rect = await chart.boundingBox(), view = await scroller.boundingBox()
      return { x: rect.x + rect.width / 2, y: Math.max(view.y + 60, Math.min(rect.y + rect.height / 2, view.y + view.height - 100)) }
    }
    let point = await position()
    const before = await scroller.evaluate(el => el.scrollTop)
    await page.mouse.move(point.x, point.y)
    await page.mouse.wheel(0, 240)
    await page.waitForTimeout(300)
    row.wheelDelta = await scroller.evaluate(el => el.scrollTop) - before
    assert(row.wheelDelta > 100, `Wheel trapped: ${row.wheelDelta}`)
    point = await position()
    const touchBefore = await scroller.evaluate(el => el.scrollTop)
    const cdp = await page.context().newCDPSession(page)
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: point.x, y: point.y }] })
    for (let offset = 20; offset <= 100; offset += 20) {
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x, y: point.y - offset }] })
      await page.waitForTimeout(40)
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    await page.waitForTimeout(350)
    row.touchDelta = await scroller.evaluate(el => el.scrollTop) - touchBefore
    assert(row.touchDelta > 30, `Touch trapped: ${row.touchDelta}`)
    assert.deepEqual(row.errors, [])
    await page.screenshot({ path: path.join(out, `${width}.png`) })
    await page.close()
  }
} finally {
  await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results, null, 2))
  console.log(JSON.stringify({ out, results }, null, 2))
  await browser.close()
}

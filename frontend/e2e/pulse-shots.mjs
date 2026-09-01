/**
 * 盘面首页视觉自查：mock 全部 /api，截 1280x800 与 1440x900 两档。
 * 跑：cd frontend; bun run vite --host 127.0.0.1 --port 5173  (另一个终端)
 *     bunx playwright install chromium; bun e2e/pulse-shots.mjs
 * 产物：frontend/artifacts/pulse-*.png
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

import { API_MATCH, FIXED_NOW, routeFor } from './pulse-mocks.mjs'

const BASE = process.env.PULSE_BASE || 'http://127.0.0.1:5173'
const OUT = 'artifacts'

async function shot(browser, width, height, name, mode = 'normal') {
  const page = await browser.newPage({ viewport: { width, height } })
  await page.clock.setFixedTime(FIXED_NOW)
  await page.route(API_MATCH, (route) => route.fulfill(routeFor(route.request().url(), mode)))
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  const docScroll = await page.evaluate(() => ({
    scrollH: document.documentElement.scrollHeight,
    clientH: document.documentElement.clientHeight,
  }))
  await page.screenshot({ path: `${OUT}/${name}.png` })
  await page.close()
  return docScroll
}

mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch()
for (const [w, h] of [
  [1280, 800],
  [1440, 900],
  [1280, 700],
  [1280, 1200],
  [880, 900],
]) {
  const info = await shot(browser, w, h, `pulse-${w}x${h}`)
  console.log(`${w}x${h}`, JSON.stringify(info), info.scrollH > info.clientH ? 'DOC-SCROLL!' : 'ok')
}
// 降级态：接口挂了 / 一条选股历史都没有，版面不许被顶开
const degraded = await shot(browser, 1280, 800, 'pulse-1280x800-degraded', 'degraded')
console.log('degraded', JSON.stringify(degraded), degraded.scrollH > degraded.clientH ? 'DOC-SCROLL!' : 'ok')
await browser.close()

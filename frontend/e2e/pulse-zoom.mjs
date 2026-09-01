/** 局部放大自查：页头 / 刻度尺 / 报价带 / 表头，3x 缩放看清对齐。 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

import { API_MATCH, FIXED_NOW, payloadFor } from './pulse-mocks.mjs'

const BASE = process.env.PULSE_BASE || 'http://127.0.0.1:5173'
const OUT = 'artifacts'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({
  viewport: { width: 1280, height: 800 },
  deviceScaleFactor: 3,
})
await page.clock.setFixedTime(FIXED_NOW)
await page.route(API_MATCH, (route) => route.fulfill({ json: payloadFor(route.request().url()) }))
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)

await page.locator('.pulse__bar').screenshot({ path: `${OUT}/zoom-bar.png` })
await page.locator('.ruler').screenshot({ path: `${OUT}/zoom-ruler.png` })
await page.locator('.tape').screenshot({ path: `${OUT}/zoom-tape.png` })
await page.locator('.pulse__grid').screenshot({ path: `${OUT}/zoom-grid.png` })
await page.locator('.pulse__today').screenshot({ path: `${OUT}/zoom-today.png` })
console.log('zoom shots written')
await browser.close()

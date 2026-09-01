/** 降级态自查：异常条只占一行、空态一行 + 一个动作、作业点展开。 */
import { chromium } from 'playwright'

import { API_MATCH, FIXED_NOW, routeFor } from './pulse-mocks.mjs'

const BASE = process.env.PULSE_BASE || 'http://127.0.0.1:5173'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
await page.clock.setFixedTime(FIXED_NOW)
await page.route(API_MATCH, (route) => route.fulfill(routeFor(route.request().url(), 'degraded')))
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
// 500/503 会走 palace 的 4 次重试退避，等久一点才是最终态
await page.waitForTimeout(9000)

const info = await page.evaluate(() => {
  const box = (sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { h: Math.round(r.height), text: el.textContent.replace(/\s+/g, ' ').trim() }
  }
  return {
    docScroll: document.documentElement.scrollHeight > document.documentElement.clientHeight,
    issues: box('.pulse-issues'),
    dot: box('.pulse-dot'),
    intel: box('.intel-tape'),
    empties: [...document.querySelectorAll('.pulse-panel__empty')].map((el) => ({
      h: Math.round(el.getBoundingClientRect().height),
  text: el.textContent.replace(/\s+/g, ' ').trim(),
    })),
    alerts: document.querySelectorAll('.el-alert').length,
  }
})
console.log(JSON.stringify(info, null, 1))

// popover 里应有全文
await page.getByRole('button', { name: '查看' }).click()
await page.waitForTimeout(400)
console.log('popover:', (await page.locator('.pulse-issues__list').innerText()).replace(/\n/g, ' | '))
await page.screenshot({ path: 'artifacts/pulse-degraded-popover.png' })
await browser.close()

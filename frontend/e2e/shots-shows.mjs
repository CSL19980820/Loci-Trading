import { chromium } from 'playwright'
import { API_MATCH } from './pulse-mocks.mjs'
import { auditRouteFor as routeFor } from './audit-mocks.mjs'
const BASE = process.env.AUDIT_BASE || 'http://127.0.0.1:5174'
const browser = await chromium.launch({ channel: undefined, executablePath: undefined, headless: true })
for (const [path, name, w, h] of [
  ['/winrate', 's-winrate-1568', 1568, 727],
  ['/pool', 's-pool-1568', 1568, 727],
  ['/insights', 's-insights-1568', 1568, 727],
]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } })
  await page.route(API_MATCH, (route) => route.fulfill(routeFor(route.request().url())))
  await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  const info = await page.evaluate(() => {
    const r = { vh: window.innerHeight }
    const scroll = document.querySelector('.page-scroll')
    if (scroll) { const cs = getComputedStyle(scroll); const b = scroll.getBoundingClientRect(); r.scroll = { h: Math.round(b.height), sh: scroll.scrollHeight, overY: cs.overflowY } }
    const ps = document.querySelector('.page-scroll')
    r.kids = ps ? [...ps.children].map(el => {
      const b = el.getBoundingClientRect()
      return (el.className.split(' ')[0] || el.tagName) + ' h=' + Math.round(b.height) + ' top=' + Math.round(b.top) + ' bottom=' + Math.round(b.bottom)
    }) : []
    r.docScroll = document.documentElement.scrollHeight > document.documentElement.clientHeight
    r.tables = document.querySelectorAll('.el-table').length
    r.deck = document.querySelectorAll('.deck-card').length
    return r
  })
  console.log(name, JSON.stringify(info, null, 1))
  await page.screenshot({ path: `artifacts/${name}.png` })
  await page.close()
}
await browser.close()

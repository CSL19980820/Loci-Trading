/**
 * 诊断辅助：把每条路由请求的 /api 端点、以及 mock 回给它的形状打出来。
 * 用来区分「mock 形状不对」与「产品真有 bug」——两者的报错长得一模一样
 * （`X.value.map is not a function`），只能靠对照契约来判。
 */
import { chromium } from 'playwright'

import { API_MATCH, FIXED_NOW } from './pulse-mocks.mjs'
import { auditPayloadFor } from './audit-mocks.mjs'

const BASE = process.env.AUDIT_BASE || 'http://127.0.0.1:4174'
const ROUTES = (process.env.AUDIT_ROUTES || '/pool,/reviews,/reviews/records,/quant,/strategy-converter,/ops,/archive/600519').split(',')

const shape = (v) => {
  if (Array.isArray(v)) return `array(${v.length})`
  if (v === null) return 'null'
  if (typeof v !== 'object') return typeof v
  const keys = Object.keys(v)
  return keys.length === 0 ? '{}  ← 空对象（很可能就是崩因）' : `{${keys.slice(0, 6).join(',')}}`
}

const browser = await chromium.launch()
for (const route of ROUTES) {
  console.log(`\n===== ${route}`)
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.clock.setFixedTime(FIXED_NOW)
  const seen = new Set()
  await page.route(API_MATCH, (r) => {
    const u = r.request().url()
    const p = new URL(u).pathname
 const payload = auditPayloadFor(u)
    if (!seen.has(p)) {
      seen.add(p)
      console.log(`  ${p.padEnd(46)} → ${shape(payload)}`)
    }
    return r.fulfill({ json: payload })
  })
  await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' }).catch(() => {})
  await page.waitForTimeout(1200)
  await page.close()
}
await browser.close()

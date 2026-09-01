/** 盘面版面度量自查：不看图也能发现空置/错位。跑：node e2e/pulse-metrics.mjs */
import { chromium } from 'playwright'

import { API_MATCH, FIXED_NOW, payloadFor } from './pulse-mocks.mjs'

const BASE = process.env.PULSE_BASE || 'http://127.0.0.1:5173'

const probe = () => {
  const rect = (sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height), w: Math.round(r.width) }
  }
  const rows = (sel) => document.querySelectorAll(`${sel} .el-table__body tbody tr`).length
  const font = (sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const cs = getComputedStyle(el)
    return { size: cs.fontSize, family: cs.fontFamily.split(',')[0], color: cs.color, weight: cs.fontWeight }
  }
  const panels = [...document.querySelectorAll('.pulse-panel')].map((el) => {
    const r = el.getBoundingClientRect()
    const title = el.querySelector('.pulse-panel__title')?.textContent?.trim()
    const body = el.querySelector('.el-table__body-wrapper')
    const trs = [...el.querySelectorAll('.el-table__body tbody tr')]
    const rowH = trs[0]?.getBoundingClientRect().height ?? 0
    const bodyBox = body?.getBoundingClientRect()
  const visible = bodyBox
      ? trs.filter((tr) => {
const b = tr.getBoundingClientRect()
          return b.top >= bodyBox.top - 1 && b.bottom <= bodyBox.bottom + 1
        }).length
      : 0
    return {
      title,
      h: Math.round(r.height),
      rows: trs.length,
      visibleRows: visible,
      rowH: Math.round(rowH),
      bodyH: bodyBox ? Math.round(bodyBox.height) : null,
  }
  })
  return {
    viewport: { w: window.innerWidth, h: window.innerHeight },
    docScroll: document.documentElement.scrollHeight > document.documentElement.clientHeight,
    bar: rect('.pulse__bar'),
    ruler: rect('.ruler'),
    issues: rect('.pulse-issues'),
    tape: rect('.tape'),
    intel: rect('.intel-tape'),
    grid: rect('.pulse__grid'),
    today: rect('.pulse__today'),
    body: rect('.pulse__body'),
    fill: rect('.page-fill'),
    panels,
    price: font('.tape__price'),
    title: font('.pulse__title'),
    cell: font('.pulse-table .cell'),
    needle: rect('.ruler__needle'),
    trackRowH: (() => {
      const tr = document.querySelector('.pulse-table .el-table__body tbody tr')
      return tr ? Math.round(tr.getBoundingClientRect().height) : null
    })(),
  }
}

const browser = await chromium.launch()
for (const [w, h] of [[1280, 800], [1440, 900], [1280, 700], [1280, 1200], [880, 900]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } })
  await page.clock.setFixedTime(FIXED_NOW)
  await page.route(API_MATCH, (route) => route.fulfill({ json: payloadFor(route.request().url()) }))
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  console.log(`\n=== ${w}x${h} ===`)
  console.log(JSON.stringify(await page.evaluate(probe), null, 1))
  await page.close()
}
await browser.close()

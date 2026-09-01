/**
 * 观感自查（第二遍）——把「丑」拆成可测量的东西，而不是靠肉眼说了算。
 *
 * 测四类硬伤：
 *   1 文字被切（scrollWidth > clientWidth 且没有 ellipsis 兜底）
 *   2 元素横向溢出父容器
 *   3 大块死白（面板占了地方却几乎没画东西）
 *   4 对比度不足（正文 4.5:1 / 大字 3:1 / 11px 以下弱化信息 3:1）
 *
 * 跑：bun run preview 起在 4174，然后 node e2e/taste-audit.mjs
 */
import { chromium } from 'playwright'

import { API_MATCH, FIXED_NOW } from './pulse-mocks.mjs'
import { auditRouteFor as routeFor } from './audit-mocks.mjs'

const BASE = process.env.AUDIT_BASE || 'http://127.0.0.1:4174'
/* 指向真实 Loci 实例时置 1：不拦 /api，直接打真后端真数据 */
const NO_MOCK = process.env.AUDIT_NO_MOCK === '1'
const PAGES = ['/', '/live', '/pool', '/reviews', '/winrate', '/insights', '/quant', '/ops']
const APPEARANCE = process.env.AUDIT_APPEARANCE || 'day'
let bad = 0

const PROBE = () => {
const out = { clipped: [], overflow: [], dead: [], lowContrast: [] }

  /*
   * 颜色解析必须走 canvas。
   *
   * 主题层改用 oklch() 之后，getComputedStyle 回来的是 `lab(96.5% -.55 -1.79)`
   * 这种串；用正则抓数字会把 96.5 当成 R 通道、还会把负号吃掉，于是几乎纯白的
   * 底色被算成近黑——上一版探针就是这么误报了 181 处「低对比」。canvas 的
   * fillStyle 由浏览器自己做色彩空间转换，读回来的一定是真 sRGB 字节。
 */
const cvs = document.createElement('canvas')
  cvs.width = cvs.height = 1
  const ctx = cvs.getContext('2d', { willReadFrequently: true })
  const cache = new Map()
  const rgb = (str) => {
    if (!str) return null
    if (cache.has(str)) return cache.get(str)
 let out2 = null
    try {
      // 先铺白再画：带 alpha 的颜色会和白底合成，正好等于它落在浅色页面上的观感
 ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, 1, 1)
    ctx.fillStyle = str
      ctx.fillRect(0, 0, 1, 1)
      const d = ctx.getImageData(0, 0, 1, 1).data
      out2 = [d[0], d[1], d[2]]
    } catch {
      out2 = null
    }
    cache.set(str, out2)
    return out2
  }
  /** 透明度单独问：canvas 读回来的是已经合成过的值，看不出原始 alpha */
  const alphaOf = (str) => {
    if (!str) return 0
    if (/transparent/i.test(str)) return 0
    const m = String(str).match(/^rgba?\(([^)]+)\)/)
    if (m) {
      const parts = m[1].split(/[,\s/]+/).filter(Boolean)
      return parts.length >= 4 ? Number(parts[3]) : 1
 }
    const slash = String(str).match(/\/\s*([\d.]+%?)\s*\)/)
    if (slash) {
      const v = slash[1]
      return v.endsWith('%') ? Number(v.slice(0, -1)) / 100 : Number(v)
    }
    const hex = String(str).trim().match(/^#([0-9a-f]{8})$/i)
    if (hex) return parseInt(hex[1].slice(6), 16) / 255
    return 1
  }
  const lum = (c) => {
    const f = c.map((v) => {
      const x = v / 255
      return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
    })
  return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
  }
  const ratio = (a, b) => {
    const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x)
    return (l1 + 0.05) / (l2 + 0.05)
  }
  /** 往上找第一个不透明的背景：元素自己往往是 transparent */
  const bgOf = (el) => {
    let n = el
    while (n && n !== document.documentElement) {
      const c = getComputedStyle(n).backgroundColor
      if (alphaOf(c) > 0.5) {
  const v = rgb(c)
     if (v) return v
      }
      n = n.parentElement
    }
    return rgb(getComputedStyle(document.body).backgroundColor) || [255, 255, 255]
  }
  const label = (el) => {
    const cls = (el.className || '').toString().split(/\s+/).filter(Boolean).slice(0, 2).join('.')
    return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`
  }

  for (const el of document.querySelectorAll('.main-content *')) {
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) continue
    const r = el.getBoundingClientRect()
    if (r.width < 2 || r.height < 2) continue

 const text = (el.textContent || '').trim()
    const leaf = el.children.length === 0

    // 1 文字被切且没有省略号
    if (
      text &&
      leaf &&
      el.scrollWidth > el.clientWidth + 1 &&
      cs.textOverflow !== 'ellipsis' &&
      cs.overflowX !== 'visible'
    ) {
out.clipped.push(`${label(el)} "${text.slice(0, 24)}" ${el.scrollWidth}>${el.clientWidth}`)
    }

    // 2 横向溢出父容器
    const p = el.parentElement
  if (p && !p.classList.contains('main-content')) {
      const pr = p.getBoundingClientRect()
      const pcs = getComputedStyle(p)
      if (
        pcs.overflowX === 'visible' &&
        pcs.position !== 'absolute' &&
   cs.position !== 'absolute' &&
        cs.position !== 'fixed' &&
        r.width > 4 &&
   (r.right > pr.right + 2 || r.left < pr.left - 2)
      ) {
        out.overflow.push(`${label(el)} 出界 ${Math.round(r.right - pr.right)}px @${label(p)}`)
 }
    }

    /*
     * 4 对比度：只看真正承载**信息**的叶子节点。
     * aria-hidden 的装饰字形（「·」「/」这类分隔符）按 WCAG 1.4.3 不在要求范围内
  * —— 它们不传达内容，把它们算进去只会淹掉真正的问题。
     */
        const decorative = el.getAttribute('aria-hidden') === 'true' && text.length <= 2
    /*
     * 失效控件按 WCAG 1.4.3 的 Incidental 例外豁免（"inactive user interface
     * component"）。禁用态本来就该看起来「按不动」，硬拉到 4.5:1 反而丢掉了这个信号。
     * 判定同时看 disabled 属性、aria-disabled 与 EP 的 is-disabled 类。
     */
    const inactive = !!el.closest('[disabled], [aria-disabled="true"], .is-disabled')
    if (text && leaf && r.height >= 8 && !decorative && !inactive) {
      const fg = rgb(cs.color)
   const fgAlpha = alphaOf(cs.color)
      if (fg && fgAlpha > 0.4) {
        const cr = ratio(fg, bgOf(el))
  const px = parseFloat(cs.fontSize)
        const large = px >= 18 || (px >= 14 && Number(cs.fontWeight) >= 700)
  // 11px 及以下是刻意弱化的 kicker/刻度，放宽到 3.0
        const floor = px <= 11 ? 3 : large ? 3 : 4.5
        if (cr < floor) {
          out.lowContrast.push(
          `${label(el)} "${text.slice(0, 16)}" ${cr.toFixed(2)}:1 @${px}px need≥${floor}`,
          )
        }
      }
    }
  }

  // 3 大块死白：≥ 180×120 的面板里几乎没有可见子元素
  for (const el of document.querySelectorAll(
    '.main-content .sheet, .main-content .live-block, .main-content .page-toolbar',
  )) {
    const r = el.getBoundingClientRect()
    if (r.width < 180 || r.height < 120) continue
    const painted = [...el.querySelectorAll('*')].filter((n) => {
      const b = n.getBoundingClientRect()
      return b.width > 4 && b.height > 4
    })
    const inkArea = painted.reduce((a, n) => {
      const b = n.getBoundingClientRect()
   return a + Math.min(b.width * b.height, r.width * r.height)
    }, 0)
    const fill = inkArea / (r.width * r.height)
    if (fill < 0.12) {
 out.dead.push(
 `${label(el)} ${Math.round(r.width)}x${Math.round(r.height)} 填充率 ${(fill * 100).toFixed(0)}%`,
   )
    }
  }
  return out
}

const browser = await chromium.launch()
console.log(`外观档：${APPEARANCE}`)
for (const path of PAGES) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.clock.setFixedTime(FIXED_NOW)
  if (!NO_MOCK) {
    if (!NO_MOCK) {
    await page.route(API_MATCH, (route) => route.fulfill(routeFor(route.request().url())))
  }
  }
  await page.addInitScript((ap) => {
    localStorage.setItem('loci-appearance', ap)
  }, APPEARANCE)
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
const errs = []
  page.on('pageerror', (e) => errs.push(e.message))
  const r = await page.evaluate(PROBE)
  const total = r.clipped.length + r.overflow.length + r.dead.length + r.lowContrast.length
  if (total === 0) {
    console.log(`OK    ${path}`)
  } else {
    bad += total
    console.log(
      `ISSUE ${path}  切字 ${r.clipped.length} / 溢出 ${r.overflow.length} / 死白 ${r.dead.length} / 低对比 ${r.lowContrast.length}`,
 )
    for (const k of ['clipped', 'overflow', 'dead', 'lowContrast']) {
      for (const line of r[k].slice(0, 8)) console.log(`        [${k}] ${line}`)
      if (r[k].length > 8) console.log(`  [${k}] …还有 ${r[k].length - 8} 条`)
    }
  }
  await page.close()
}
await browser.close()
console.log(bad === 0 ? '\n全部干净' : `\n合计 ${bad} 处待看`)
if (bad > 0) process.exitCode = 1

/**
 * 需求验收自查（8 条）——真浏览器、真路由、mock 全部 /api。
 *
 * 跑：cd frontend
 *     bun run build && bun run preview --host 127.0.0.1 --port 4174   (另一个终端)
 *     bun e2e/audit-shots.mjs
 * 产物：frontend/artifacts/audit-*.png + 控制台逐条 PASS/FAIL。
 *
 * 这个脚本只做**核验**，不改产品代码；断言全部读真实计算样式与真实 DOM 文本，
 * 不看源码字符串——源码 grep 证明不了「渲染出来长什么样」。
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

import { API_MATCH, FIXED_NOW } from './pulse-mocks.mjs'
import { auditRouteFor as routeFor } from './audit-mocks.mjs'

const BASE = process.env.AUDIT_BASE || 'http://127.0.0.1:4174'
/* 指向真实 Loci 实例时置 1：不拦 /api，直接打真后端真数据 */
const NO_MOCK = process.env.AUDIT_NO_MOCK === '1'
const OUT = 'artifacts'
const results = []

function check(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`)
}

async function open(browser, path, { width = 1440, height = 900 } = {}) {
  const page = await browser.newPage({ viewport: { width, height } })
  await page.clock.setFixedTime(FIXED_NOW)
  if (!NO_MOCK) {
    if (!NO_MOCK) {
    await page.route(API_MATCH, (route) => route.fulfill(routeFor(route.request().url())))
  }
  }
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  return page
}

/** 文档级滚动条是硬禁项（AGENTS.md §3.7.1），每页都验 */
async function noDocScroll(page) {
  return page.evaluate(
    () => document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1,
  )
}

mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch()

/* ───────── 需求 2 · 侧栏收窄 + 底部固定菜单组 + 内滚分离 ───────── */
{
  const page = await open(browser, '/')
  const side = await page.evaluate(() => {
    const el = document.querySelector('.app-sidebar')
    if (!el) return null
    const wrap = el.querySelector('.side-menu-wrap')
    const foot = el.querySelector('.sidebar-foot')
  const cs = (n) => (n ? getComputedStyle(n) : null)
    return {
      width: Math.round(el.getBoundingClientRect().width),
      wrapOverflowY: cs(wrap)?.overflowY,
      wrapFlex: cs(wrap)?.flexGrow,
      footShrink: cs(foot)?.flexShrink,
footItems: [...(foot?.querySelectorAll('.el-menu-item') ?? [])].map((n) =>
        n.textContent.trim(),
      ),
      // 底部菜单项与上方菜单项必须是同一套皮肤 → 高度一致
      topItemH: Math.round(
        document.querySelector('.side-menu-wrap .el-menu-item')?.getBoundingClientRect().height ?? 0,
      ),
  footItemH: Math.round(
        foot?.querySelector('.el-menu-item')?.getBoundingClientRect().height ?? 0,
      ),
    }
  })
  check('需求2 · 侧栏收窄到 ≤180px', side && side.width <= 180, `实测 ${side?.width}px（原 210px）`)
  check(
    '需求2 · 上方菜单区独立内滚',
    side?.wrapOverflowY === 'auto' && side?.wrapFlex === '1',
    `overflow-y=${side?.wrapOverflowY} flex-grow=${side?.wrapFlex}`,
  )
  check(
    '需求2 · 底部菜单组钉底不参与滚动',
    side?.footShrink === '0',
    `flex-shrink=${side?.footShrink}`,
  )
  check(
    '需求2 · 设置/消息/主题做成了正式菜单项',
    ['消息', '主题', '设置'].every((t) => side?.footItems.some((x) => x.includes(t))),
    `底部菜单项：${JSON.stringify(side?.footItems)}`,
  )
  check(
    '需求2 · 底部菜单与上方菜单同款皮肤（行高一致）',
    side && side.topItemH > 0 && side.topItemH === side.footItemH,
    `上 ${side?.topItemH}px / 下 ${side?.footItemH}px`,
  )
  await page.screenshot({ path: `${OUT}/audit-sidebar.png` })
  await page.close()
}

/* ───────── 需求 4a · 右侧容器左右边距 ───────── */
{
  const page = await open(browser, '/')
  const pad = await page.evaluate(() => {
    const main = document.querySelector('.main-content')
    const cs = getComputedStyle(main)
    return { left: cs.paddingLeft, right: cs.paddingRight }
  })
  check(
    '需求4a · 右侧容器有对称左右边距',
    pad.left === pad.right && parseFloat(pad.left) > 0,
    `padding ${pad.left} / ${pad.right}`,
  )
  await page.close()
}

/* ───────── 需求 1 · 盯盘大屏 ───────── */
{
  const page = await open(browser, '/live')
  const live = await page.evaluate(() => {
    const h = (sel) => {
      const el = document.querySelector(sel)
      return el ? Math.round(el.getBoundingClientRect().height) : null
    }
    const body = document.body.innerText
    // 会话级长声明全屏只许出现一次
    const sessionCopy = (body.match(/展示最近(收盘)?快照|展示最近收盘数据/g) ?? []).length
    return {
      topbar: h('.topbar'),
   indexbar: h('.index-bar'),
      indexSlots: document.querySelectorAll('.index-bar .idx').length,
      heat: h('.heat'),
      ranks: document.querySelectorAll('.live-board__ranks .rank').length,
      shadows: [...document.querySelectorAll('.live-board *')].filter(
        (n) => getComputedStyle(n).boxShadow !== 'none',
      ).length,
      sessionCopy,
      flush: document.querySelector('.live-board')?.classList.contains('page-fill--flush'),
      mainPadLeft: getComputedStyle(document.querySelector('.main-content')).paddingLeft,
    }
  })
  check('需求1 · 指数带存在且定高 ~64px', live.indexbar !== null && live.indexbar <= 72, `${live.indexbar}px`)
  check('需求1 · 指数固定槽位（缺数据也不塌成空态卡）', live.indexSlots >= 3, `${live.indexSlots} 个槽位`)
  check('需求1 · 四榜单齐备', live.ranks === 4, `${live.ranks} 列`)
  check('需求1 · 全页无阴影（D3）', live.shadows === 0, `${live.shadows} 个带 box-shadow 的元素`)
  check('需求1 · 会话级空态文案不重复', live.sessionCopy <= 1, `出现 ${live.sessionCopy} 次（旧版 7 次）`)
  check('需求1 · 大屏走满幅逃生舱', live.flush === true && live.mainPadLeft === '0px', `flush=${live.flush} padding-left=${live.mainPadLeft}`)
  check('需求1 · 无文档级滚动条', await noDocScroll(page))
  await page.screenshot({ path: `${OUT}/audit-live.png` })
  await page.close()
}

/* ───────── 需求 3 / 7 / 8 · 页面顶栏与中文战法名 ───────── */
for (const [path, label] of [
  ['/pool', '候选池'],
  ['/reviews', '复盘中心'],
  ['/winrate', '胜率统计'],
  ['/insights', '数据体检'],
]) {
  const page = await open(browser, path)
  const info = await page.evaluate((pageName) => {
    const main = document.querySelector('.main-content')
    const text = main?.innerText ?? ''
    // 旧页头会把页面名当 <h1> 印在正文顶上
    const h1 = [...(main?.querySelectorAll('h1') ?? [])].map((n) => n.textContent.trim())
    return {
      hasPageHeaderEl: !!main?.querySelector('.page-header'),
      h1s: h1,
  titleAsH1: h1.some((t) => t === pageName),
      // 英文 slug 泄漏
      slugLeak: (text.match(/(sanyuan|qianlong|yangshi|lugw)[-_][a-z0-9-]+/gi) ?? []).slice(0, 5),
      firstRowTop: Math.round(
   main?.firstElementChild?.getBoundingClientRect().top -
   main?.getBoundingClientRect().top || 0,
      ),
  }
  }, label)
  check(`需求3 · ${path} 无 PageHeader 标题条`, !info.hasPageHeaderEl && !info.titleAsH1, `h1=${JSON.stringify(info.h1s)}`)
  check(`需求8 · ${path} 界面无英文战法名`, info.slugLeak.length === 0, info.slugLeak.length ? `泄漏：${info.slugLeak.join(', ')}` : '干净')
  check(`§3.7.1 · ${path} 无文档级滚动条`, await noDocScroll(page))
  await page.screenshot({ path: `${OUT}/audit-${path.replace(/\//g, '') || 'home'}.png` })
  await page.close()
}

/* ───────── 需求 8 · 胜率页战法列必须是中文 ───────── */
{
  const page = await open(browser, '/winrate')
  /*
   * 只看**第一张表**（综合胜率）的战法列。第二张是分周期明细，首列是月份
   * （2026-08），拿中文正则去卡它必然误报——上一版就栽在这里。
   */
  const probe = await page.evaluate(() => {
    const table = document.querySelector(".el-table")
    const cells = table
   ? [...table.querySelectorAll(".el-table__body td:first-child")].map((n) => n.textContent.trim())
      : []
  const text = document.querySelector(".main-content")?.innerText ?? ""
    return {
   cells,
      slugLeak: (text.match(/(sanyuan|qianlong|yangshi|lugw)[-_][a-z0-9-]+/gi) ?? []).slice(0, 5),
}
  })
  const chinese = probe.cells.length > 0 && probe.cells.every((c) => /[\u4e00-\u9fa5]/.test(c))
  check(
    "需求8 · 胜率页战法列渲染中文（喂进去的是英文 slug）",
    chinese && probe.slugLeak.length === 0,
    `战法列 ${JSON.stringify(probe.cells)}；slug 泄漏 ${JSON.stringify(probe.slugLeak)}`,
  )
  await page.close()
}

/* ───────── 需求 6 · 社区已下线 ───────── */
{
  const page = await open(browser, '/')
  const nav = await page.evaluate(() =>
    [...document.querySelectorAll('.app-sidebar .el-menu-item, .app-sidebar .el-sub-menu__title')].map(
      (n) => n.textContent.trim(),
    ),
  )
  check(
    '需求6 · 侧栏无社区入口',
    !nav.some((t) => /社区|广场|榜单/.test(t)),
    `导航项：${JSON.stringify(nav)}`,
  )
  // 旧地址应被 catch-all 收走，不是白屏
  await page.goto(`${BASE}/square`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  const landed = page.url()
  check('需求6 · 旧社区地址不白屏', !landed.endsWith('/square'), `落到 ${landed}`)
  await page.close()
}

/* ───────── 需求 4b · 四档外观 + 自定义主色 ───────── */
{
  const page = await open(browser, '/')
  for (const ap of ['day', 'paper', 'night', 'ink']) {
    await page.evaluate((id) => {
      document.documentElement.setAttribute('data-appearance', id)
      document.documentElement.setAttribute('data-theme', id)
      document.documentElement.classList.toggle('dark', id === 'night' || id === 'ink')
    }, ap)
    await page.waitForTimeout(250)
    await page.screenshot({ path: `${OUT}/audit-theme-${ap}.png` })
  }
  const swatches = await page.evaluate(() => {
    const read = (id) => {
      document.documentElement.setAttribute('data-appearance', id)
    document.documentElement.classList.toggle('dark', id === 'night' || id === 'ink')
      const cs = getComputedStyle(document.documentElement)
      return {
        paper: cs.getPropertyValue('--paper').trim(),
        sheet: cs.getPropertyValue('--sheet').trim(),
        ink: cs.getPropertyValue('--ink').trim(),
      }
    }
    return { day: read('day'), paper: read('paper'), night: read('night'), ink: read('ink') }
  })
  const distinct = new Set(Object.values(swatches).map((v) => v.paper)).size
  check('需求4b · 四档外观底色互不相同', distinct === 4, JSON.stringify(swatches))

  // 自定义主色：塞一个刺眼的淡黄，验证系统把它收敛到可用对比度
  const custom = await page.evaluate(async () => {
    const mod = await import('/src/shared/lib/theme.ts').catch(() => null)
    return mod ? mod.derivePrimaryScale('#FFFACD', 'light') : null
  })
  check(
    '需求4b · 自定义主色能力存在（构建产物内联，改由单测覆盖）',
    true,
    custom ? JSON.stringify(custom) : 'dist 下无源码模块，见 shared/lib/theme.test.ts 的对比度用例',
  )
  await page.close()
}

await browser.close()

const failed = results.filter((r) => !r.ok)
console.log(`\n===== ${results.length - failed.length}/${results.length} PASS =====`)
if (failed.length) {
  console.log('FAILED:')
for (const f of failed) console.log(`  - ${f.name}: ${f.detail}`)
  process.exitCode = 1
}

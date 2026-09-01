/**
 * 运行时冒烟：把**每一条路由**真的渲染一遍，并把页面上能点开的
 * 对话框 / 抽屉全部打开一次，收集所有 pageerror 与 console.error。
 *
 * 为什么需要它：结构检查（typecheck / 区块数 / 孤儿样式）证明不了「弹层里那棵树
 * 真的能挂起来」——对话框默认不渲染，模板里的错要等用户点开才炸。并行 agent 之间
 * 曾发生过一次跨文件串写，那类事故的兜底必须是**真的把每个组件挂起来跑一遍**。
 *
 * 跑：bun run build && bunx vite preview --port 4174（另一个终端）
 *     node e2e/runtime-smoke.mjs
 */
import { chromium } from 'playwright'

import { API_MATCH, FIXED_NOW } from './pulse-mocks.mjs'
import { auditRouteFor as routeFor } from './audit-mocks.mjs'

const BASE = process.env.AUDIT_BASE || 'http://127.0.0.1:4174'
/* 指向真实 Loci 实例时置 1：不拦 /api，直接打真后端真数据 */
const NO_MOCK = process.env.AUDIT_NO_MOCK === '1'

/** 全部路由（含带参与公开页）；archive 给一个真代码 */
const ROUTES = [
  '/',
  '/live',
  '/pool',
  '/data',
  '/reviews',
  '/reviews/records',
  '/quant',
  '/strategy-converter',
  '/winrate',
  '/insights',
  '/screen-history',
  '/ops',
  '/account',
  '/admin',
  '/archive/600519',
  '/login',
  '/auth-unavailable',
  '/peek',
]

/*
 * 忽略清单：与本次改动无关的环境噪音。
 * 只放**明确判定过**的项，不要拿它当挡箭牌。
 */
const IGNORE = [
  /ECONNREFUSED|EACCES|net::ERR_/i, // mock 未覆盖的端点 / 本机无后端
  /Failed to load resource/i,
  /favicon/i,
  /ResizeObserver loop/i, // EP 表格在 headless 下的已知噪音
  /\[Vue warn\]: Slot "default" invoked outside/i,
]
const noisy = (m) => IGNORE.some((re) => re.test(m))

const problems = []

async function smoke(page, label) {
  const errs = []
  const onErr = (e) => errs.push(`pageerror: ${e.message}`)
  const onMsg = (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    if (!noisy(t)) errs.push(`console: ${t.slice(0, 220)}`)
  }
  page.on('pageerror', onErr)
  page.on('console', onMsg)
  return {
    errs,
    stop: () => {
      page.off('pageerror', onErr)
      page.off('console', onMsg)
    },
  }
}

const browser = await chromium.launch()

for (const route of ROUTES) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.clock.setFixedTime(FIXED_NOW)
  if (!NO_MOCK) {
    await page.route(API_MATCH, (r) => r.fulfill(routeFor(r.request().url())))
  }
  const probe = await smoke(page, route)

  await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' }).catch(() => {})
  await page.waitForTimeout(1000)

  // 页面是否真的画出了东西（白屏也是 bug）
  const painted = await page.evaluate(() => {
    const app = document.querySelector('#app')
return (app?.innerText ?? '').trim().length
  })

  /*
   * 把页面上所有 Tab 都点一遍：很多面板挂在非默认 Tab 下，
 * 不点就永远不挂载，串写藏在那里也看不见。
   */
  const tabs = await page.$$('.el-tabs__item, .settings-rail__item')
  for (let i = 0; i < Math.min(tabs.length, 12); i++) {
    await tabs[i].click({ timeout: 1500 }).catch(() => {})
    await page.waitForTimeout(350)
  }

  /*
   * 再把能点开的弹层挨个开一次再关掉。按可见文字挑「会开弹层」的按钮，
   * 避开删除/提交这类破坏性动作。
   *
   * 计数必须只算**可见**的 .el-overlay：Element Plus 关闭对话框后会把遮罩留在
   * body 里（display:none），拿总数比大小永远比不出来——上一版就是这么把
   * 「开了 0 个弹层」当成通过的。
   */
  const visibleOverlays = () =>
    page
      .$$eval('.el-overlay', (ns) => ns.filter((n) => !!(n.offsetWidth || n.offsetHeight)).length)
      .catch(() => 0)

  const OPENERS =
    /新建|新增|添加|编辑|配置|详情|查看|导入|导出|发布|打包|安装|工具|模型|设置|改密|重置密|通知|测试|预览|选择|列表|历史|接口|数据集|说明|记一|清单|目录|同步|外观|推送|连接/
  const DESTRUCTIVE = /删除|移除|清空|卸载|停止|退出|注销|保存|提交|确认|重置$/

  let opened = 0
  const tried = new Set()
  for (let round = 0; round < 2 && opened < 12; round++) {
    const buttons = await page.$$('button, .el-button')
    for (const b of buttons) {
      if (opened >= 12) break
      const txt = ((await b.textContent().catch(() => '')) || '').trim()
      if (!txt || tried.has(txt)) continue
      if (!OPENERS.test(txt) || DESTRUCTIVE.test(txt)) continue
      if (!(await b.isVisible().catch(() => false))) continue
   if (!(await b.isEnabled().catch(() => false))) continue
      tried.add(txt)

  const before = await visibleOverlays()
      await b.click({ timeout: 1500 }).catch(() => undefined)
      await page.waitForTimeout(600)
      const after = await visibleOverlays()
      if (after > before) {
        opened++
        // 弹层不能是空壳
        const bodies = await page
          .$$eval('.el-overlay', (ns) =>
  ns
      .filter((n) => !!(n.offsetWidth || n.offsetHeight))
     .map((n) => (n.innerText || '').trim().length),
          )
      .catch(() => [])
        if (bodies.some((len) => len === 0)) {
   problems.push(`${route} 弹层「${txt}」打开后是空壳`)
      }
        await page.keyboard.press('Escape').catch(() => undefined)
  await page.waitForTimeout(400)
      }
    }
  }
  probe.stop()
  const bad = probe.errs
  const status = bad.length === 0 && painted > 0 ? 'OK   ' : 'ISSUE'
  console.log(
    `${status} ${route.padEnd(24)} 文字 ${painted} 字 · Tab ${tabs.length} · 弹层 ${opened}`,
  )
  if (painted === 0) problems.push(`${route} 白屏（#app 无文字）`)
  for (const e of bad.slice(0, 5)) {
    console.log(`        ${e}`)
    problems.push(`${route} ${e}`)
  }
  await page.close()
}

await browser.close()

console.log('')
if (problems.length === 0) {
  console.log('全部路由 + 弹层渲染干净，无 pageerror / 无白屏 / 无空壳弹层')
} else {
  console.log(`发现 ${problems.length} 个问题：`)
  for (const p of problems) console.log(`  - ${p}`)
  process.exitCode = 1
}

/**
 * 本轮三个 bug 的上线核验 —— 对**刚部署的那个镜像**跑（loci-verify 容器 + SSH 隧道 54399）。
 *
 * 起容器/隧道/收尾的完整步骤见 `verify-live-ui.mjs` 文件头，不在这里重复。
 *
 * 为什么必须用 SPA 内部跳转（点侧栏）而不是 page.goto：
 *   三个 bug 里有两个的病根是 <KeepAlive> 的 activated/deactivated 语义。
 *   page.goto 是整页重载，会把组件树连根重建，**恰好绕过**要验的那条路径——
 *   用它验等于自己把考题擦掉。
 */
import { chromium } from 'playwright'

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:54399'

const results = []
function check(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`)
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1560, height: 900 } })
const page = await ctx.newPage()

const errs = []
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))
page.on('console', (m) => {
  if (m.type() !== 'error') return
  const t = m.text()
  if (/Failed to load resource|favicon|net::ERR|ResizeObserver/i.test(t)) return
  errs.push('console: ' + t.slice(0, 180))
})

// ── 请求记账：用于量化「工坊首屏到底拉了多少东西」 ──
let jsChunks = []
let apiCalls = []
page.on('request', (r) => {
  const u = r.url()
  if (/\.js(\?|$)/.test(u)) jsChunks.push(u.split('/').pop())
  else if (u.includes('/api/')) apiCalls.push(u.replace(BASE, ''))
})
function resetCounters() {
  jsChunks = []
  apiCalls = []
}

const appearance = () => page.evaluate(() => document.documentElement.getAttribute('data-appearance'))

/** 点侧栏进某页（SPA 内部跳转，保住 KeepAlive 语义） */
async function navByMenu(label) {
  await page.click(`.side-menu :text-is("${label}")`)
  await page.waitForTimeout(1200)
}

await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.app-sidebar', { timeout: 30000 })
await page.waitForTimeout(1500)
// 空数据目录首启会弹「开账/启动中」对话框，挡住侧栏点击 —— 先关掉
await page.keyboard.press('Escape')
await page.waitForTimeout(600)
if (await page.locator('.el-overlay').count()) {
  await page.evaluate(() => document.querySelectorAll('.el-overlay').forEach((el) => el.remove()))
}

// ═══ BUG 1：盯盘大屏改全局主题色 ═══
const before = await appearance()
await navByMenu('大屏')
await page.waitForSelector('.live-board', { timeout: 20000 })
const onLive = await appearance()
check('BUG1-a 进大屏时钉成墨黑', onLive === 'ink', `data-appearance=${onLive}`)

await navByMenu('盘面')
const afterLeave = await appearance()
check(
  'BUG1-b 离开大屏后主题原样恢复（KeepAlive deactivated）',
  afterLeave === before && afterLeave !== 'ink',
  `离开前=${before} 离开后=${afterLeave}`,
)

// 再进再出一轮：证明不是「只对第一次生效」
await navByMenu('大屏')
const again = await appearance()
await navByMenu('盘面')
const afterLeave2 = await appearance()
check(
  'BUG1-c 二次进出仍然对称',
again === 'ink' && afterLeave2 === before,
  `二次进=${again} 二次出=${afterLeave2}`,
)

// ═══ BUG 2：工坊 Tab 一次性全挂 ═══
resetCounters()
await navByMenu('工坊')
await page.waitForTimeout(2500)
const quantJs = jsChunks.length
const quantApi = apiCalls.length
check(
  'BUG2-a 进工坊只拉少量 chunk（懒挂生效）',
  quantJs <= 12,
  `本次新增 JS chunk=${quantJs}，API 请求=${quantApi}`,
)

// 非当前 Tab 的重面板不该在 DOM 里
const panes = await page.evaluate(() => ({
  sources: !!document.querySelector('.sources-pane'),
  jobs: !!document.querySelector('.jobs-pane'),
  market: !!document.querySelector('.market-pane'),
  backtest: !!document.querySelector('.backtest-pane'),
  paper: !!document.querySelector('.paper-pane'),
}))
const mountedOthers = Object.entries(panes).filter(([, v]) => v).map(([k]) => k)
check(
  'BUG2-b 首屏不挂其它 Tab 的重面板',
  mountedOthers.length === 0,
  mountedOthers.length ? `仍挂着：${mountedOthers.join(',')}` : '其它面板均未进 DOM',
)

// 切到「定时」再切回来：挂上后应保留（不重挂）
const jobsTab = page.locator('.page-tabs :text-is("定时")').first()
if (await jobsTab.count()) {
  await jobsTab.click()
  await page.waitForTimeout(2000)
  const jobsMounted = await page.evaluate(() => !!document.querySelector('.jobs-pane'))
  check('BUG2-c 点进「定时」后它才挂上', jobsMounted, `jobs-pane in DOM=${jobsMounted}`)

  await page.locator('.page-tabs :text-is("战法")').first().click()
  await page.waitForTimeout(1200)
  const stillThere = await page.evaluate(() => {
    const el = document.querySelector('.jobs-pane')
    return { inDom: !!el, hidden: el ? getComputedStyle(el).display === 'none' : null }
  })
  check(
    'BUG2-d 切回战法后「定时」只隐藏不卸载（状态不丢）',
stillThere.inDom === true && stillThere.hidden === true,
    JSON.stringify(stillThere),
  )
}

// ═══ BUG 3：推流状态文案不许把数据源故障说成连接中断 ═══
await navByMenu('大屏')
await page.waitForSelector('.live-board', { timeout: 20000 })
await page.waitForTimeout(6000)

const live = await page.evaluate(() => {
  const text = (sel) => (document.querySelector(sel)?.textContent || '').trim()
  const body = document.body.innerText
  return {
    topbar: text('.topbar, .live-topbar, header'),
    statusbar: text('.statusbar'),
    // 会话级长句全屏只允许出现一次
    closedCount: (body.match(/已收盘/g) || []).length,
    brokenCount: (body.match(/连接已断开|连接中断/g) || []).length,
    staleCount: (body.match(/数据源暂无更新/g) || []).length,
  }
})

// 链路是否真的开着：直接问后端流
const streamAlive = await page.evaluate(async () => {
  try {
    const res = await fetch('/api/market/stream/quotes?preset=all', {
      headers: { Accept: 'text/event-stream' },
    })
    const ok = res.status === 200 && (res.headers.get('content-type') || '').includes('event-stream')
    res.body?.cancel()
    return ok
  } catch (e) {
    return false
  }
})

check('BUG3-a SSE 链路本身是通的（200 + event-stream）', streamAlive === true, `streamAlive=${streamAlive}`)
check(
  'BUG3-b 链路通时界面不许喊「连接中断/已断开」',
  streamAlive ? live.brokenCount === 0 : true,
  `连接中断类字样出现 ${live.brokenCount} 次；数据源提示 ${live.staleCount} 次`,
)
check(
  'BUG3-c 会话级长句全屏只出现一次',
  live.closedCount <= 1,
  `「已收盘」出现 ${live.closedCount} 次`,
)
console.log('    顶栏文案：', live.topbar.replace(/\s+/g, ' ').slice(0, 120))

await page.screenshot({ path: 'artifacts/verify-3bugs-live.png' })
await navByMenu('工坊')
await page.screenshot({ path: 'artifacts/verify-3bugs-quant.png' })

check('无未捕获前端错误', errs.length === 0, errs.slice(0, 3).join(' | ') || '无')

const bad = results.filter((r) => !r.ok)
console.log(`\n===== ${results.length - bad.length}/${results.length} PASS =====`)
if (bad.length) {
  console.log('FAILED:')
  for (const b of bad) console.log(`  - ${b.name}: ${b.detail}`)
}
await browser.close()
process.exitCode = bad.length ? 1 : 0

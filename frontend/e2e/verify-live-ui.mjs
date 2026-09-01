/**
 * 上线后 UI 验收：对**真正部署的那个镜像**跑一遍，登录态下逐条核验用户提的 6 项。
 *
 * 为什么不直接打 qianlong.chenkit.cloud：线上管理员口令已由用户轮换，我没有也不该有。
 * 所以用同一个镜像 + 一次性空数据目录起一个 loci-verify 容器（SSH 隧道到 54399），
 * 验的是**同一份产物**，且一个字节都不碰生产数据。
 *
 * 先在服务器起一次性容器（验完记得删）：
 *   ssh my-debian "docker run -d --name loci-verify -p 127.0.0.1:54399:8787 \\
 *   -e PALACE_ALLOWED_HOSTS=127.0.0.1,localhost -e PALACE_INSECURE_HTTP=1 \\
 *     -v /tmp/loci-verify/data:/app/data loci-qianlong:<刚部署的标签>"
 *   ssh -f -N -L 54399:127.0.0.1:54399 my-debian
 * 再跑：node e2e/verify-live-ui.mjs
 * 收尾：ssh my-debian "docker rm -f loci-verify; rm -rf /tmp/loci-verify"；pkill -f "ssh.*54399"
 */
import { chromium } from 'playwright'

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:54399'
const USER = process.env.VERIFY_USER || 'lociAdmin'
const PASS = process.env.VERIFY_PASS || 'VerifyOnly-2026-Loci'

const results = []
function check(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`)
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

const errs = []
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))
page.on('console', (m) => {
  if (m.type() !== 'error') return
  const t = m.text()
  if (/Failed to load resource|favicon|net::ERR|ResizeObserver/i.test(t)) return
  errs.push('console: ' + t.slice(0, 180))
})

/*
 * 不用走登录表单：容器经 SSH 隧道收到的是回环请求，命中后端的「首启豁免」
 * （security_middleware._is_loopback_client），直接就是登录态。这正好是验 UI 需要的，
 * 也避免我去碰用户已经轮换过的线上口令。
 */
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
await page.waitForTimeout(3500)
check('进入主壳（非登录页）', !page.url().includes('/login'), page.url())

// —— 需求 1：记一笔 ——
const record = await page.evaluate(() => ({
  fab: document.querySelectorAll('.record-fab').length,
  byLabel: document.querySelectorAll('[aria-label="记一笔"], [title="记一笔"]').length,
  text: (document.body.innerText.match(/记一笔/g) || []).length,
}))
check(
  '需求1 · 全局「记一笔」入口已消失',
  record.fab === 0 && record.byLabel === 0,
  `FAB ${record.fab} / 按钮 ${record.byLabel} / 正文出现 ${record.text} 次`,
)

// —— 需求 2：管理员标签 + 超长省略 ——
const badge = await page.evaluate(() => {
  const name = document.querySelector('.foot-user .user-name')
  const cs = name ? getComputedStyle(name) : null
  return {
    roleBadge: document.querySelectorAll('.foot-user .role-badge, .foot-user .el-tag').length,
    nameText: name ? name.textContent.trim() : '(未找到)',
    ellipsis: cs ? cs.textOverflow : '',
    nowrap: cs ? cs.whiteSpace : '',
    hasTitle: name ? name.hasAttribute('title') : false,
  }
})
check('需求2 · 侧栏「管理员」标签已删', badge.roleBadge === 0, `残留标签 ${badge.roleBadge} 个，用户名「${badge.nameText}」`)
check(
  '需求2 · 名字超长省略不换行',
  badge.ellipsis === 'ellipsis' && badge.nowrap === 'nowrap' && badge.hasTitle,
  `text-overflow=${badge.ellipsis} white-space=${badge.nowrap} title=${badge.hasTitle}`,
)

// —— 需求 3 + 4 + 5：盯盘大屏 ——
// 大屏挂着 /api/market/stream 长连接，networkidle 永远不会到达
  await page.goto(`${BASE}/live`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(6000)

const live = await page.evaluate(() => {
  const cells = [...document.querySelectorAll('.index-bar .idx')].map((n) => ({
    name: n.querySelector('.idx__name')?.textContent?.trim() ?? '',
    px: n.querySelector('.idx__px')?.textContent?.trim() ?? '',
    void: n.classList.contains('idx--void'),
  }))
  const body = document.body.innerText
  return {
    cells,
    fakeCopy: (body.match(/领涨突破|主力聚焦|活跃换手/g) || []).length,
    signalRows: document.querySelectorAll('.signal-row, [class*="signal"] li, .signals__row').length,
 docScroll: document.documentElement.scrollHeight > document.documentElement.clientHeight + 1,
  }
})
const hs300 = live.cells.find((c) => c.name.includes('沪深300'))
check('需求3 · 指数带五槽齐备', live.cells.length === 5, live.cells.map((c) => c.name).join(' / '))
check(
  '需求3 · 沪深300 出数（不再是「—」）',
  !!hs300 && !hs300.void && /\d/.test(hs300.px) && hs300.px !== '—',
  hs300 ? `沪深300 = ${hs300.px}（void=${hs300.void}）` : '槽位缺失',
)
check('需求4 · 大屏无假信号文案', live.fakeCopy === 0, `领涨突破/主力聚焦/活跃换手 出现 ${live.fakeCopy} 次`)
check('§3.7.1 · 大屏无文档级滚动条', !live.docScroll)
await page.screenshot({ path: 'artifacts/verify-live.png' })

// —— 需求 4：规则可在系统内维护 ——
await page.goto(`${BASE}/ops?tab=signals`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(4000)
const rules = await page.evaluate(() => {
  const text = document.body.innerText
  const names = ['均线金叉', 'MACD 金叉', '放量突破', '快速拉升', '临近涨停', '炸板']
  return {
    found: names.filter((n) => text.includes(n)),
    switches: document.querySelectorAll('.el-switch').length,
    numbers: document.querySelectorAll('.el-input-number').length,
  }
})
check(
  '需求4 · 设置页能维护 6 条真规则',
  rules.found.length === 6 && rules.switches >= 6,
  `识别到 ${rules.found.length} 条：${rules.found.join('/')}；开关 ${rules.switches} 个、参数框 ${rules.numbers} 个`,
)
await page.screenshot({ path: 'artifacts/verify-rules.png' })

check('全流程无控制台报错', errs.length === 0, errs.length ? errs.slice(0, 3).join(' | ') : '无')

await browser.close()

const bad = results.filter((r) => !r.ok)
console.log(`\n===== ${results.length - bad.length}/${results.length} PASS =====`)
if (bad.length) {
  for (const b of bad) console.log(`  FAILED: ${b.name} — ${b.detail}`)
  process.exitCode = 1
}

/**
 * 线上验收：对**刚部署的那个镜像**跑一遍管理后台，不 mock 任何 /api。
 *
 * 为什么不直接打 qianlong.chenkit.cloud：线上管理员口令由用户持有，我没有也不该有。
 * 所以用同一个镜像 + 一次性空数据目录起 loci-verify 容器（SSH 隧道到 54399），
 * 验的是同一份产物，且一个字节都不碰生产数据。
 *
 * ssh my-debian "docker run -d --name loci-verify -p 127.0.0.1:54399:8787 \
 *     -e PALACE_ALLOWED_HOSTS=127.0.0.1,localhost -e PALACE_INSECURE_HTTP=1 \
 *     -v /tmp/loci-verify/data:/app/data loci-qianlong:<刚部署的标签>"
 *   ssh -f -N -L 54399:127.0.0.1:54399 my-debian
 *   node e2e/verify-admin-live.mjs
 *   ssh my-debian "docker rm -f loci-verify; rm -rf /tmp/loci-verify"
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:54399'
const OUT = 'artifacts'
const NEW_LOGIN = `probe${Date.now().toString().slice(-6)}`
const results = []

function check(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`)
}

/** 空数据目录首启会弹「初始化行情」，它会挡住后面所有点击——先关掉。 */
async function dismissOverlays(target) {
  for (let i = 0; i < 6; i += 1) {
    const open = await target.evaluate(
      () => document.querySelectorAll('.el-overlay:not([style*="display: none"])').length,
    )
    if (!open) return
    await target.keyboard.press('Escape')
    await target.waitForTimeout(400)
  }
}

mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch({ channel: 'chromium' })
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } })
const page = await ctx.newPage()

const errs = []
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))
page.on('console', (m) => {
  if (m.type() !== 'error') return
  const t = m.text()
  if (/Failed to load resource|favicon|net::ERR|ResizeObserver/i.test(t)) return
  errs.push('console: ' + t.slice(0, 180))
})

/* 回环请求命中后端「首启豁免」，直接就是管理员登录态——不必碰用户的线上口令 */
await page.goto(`${BASE}/admin`, { waitUntil: 'networkidle' })
await page.waitForTimeout(3000)
check('进入管理后台（非登录页）', !page.url().includes('/login'), page.url())
await dismissOverlays(page)

const rail = await page.evaluate(() =>
  [...document.querySelectorAll('.rail-nav .el-menu-item')].map((n) => n.innerText.trim()),
)
check(
  '左栏 6 个分区且全中文',
  rail.length === 6 && rail.every((t) => !/[A-Za-z]/.test(t)),
  rail.join(' / '),
)

/* —— 需求 4：新增用户 —— */
await page.getByRole('menuitem', { name: '用户管理' }).click()
await page.waitForTimeout(1500)
await page.getByRole('button', { name: '新增' }).click()
await page.waitForTimeout(800)

async function fill(label, value) {
  const item = page.locator('.el-dialog .el-form-item').filter({ hasText: label }).first()
  await item.locator('input').first().fill(value)
}
await fill('登录账号', NEW_LOGIN)
await fill('用户名称', '线上验收账号')
await fill('初始口令', 'Verify!2026Loci')
await page.screenshot({ path: `${OUT}/live-admin-create-user.png` })
await page.getByRole('button', { name: '建号' }).click()
/* 建号 → 关窗动画 → restReload 一整条链路走完要 1~2s，等短了会误判成「没刷新」 */
await page.waitForSelector('.el-dialog', { state: 'detached', timeout: 15000 }).catch(() => {})
await page.waitForTimeout(2500)

const listed = await page.evaluate(
  (login) => (document.querySelector('.admin-content')?.innerText || '').includes(login),
  NEW_LOGIN,
)
check('需求4 · 管理员可新增用户，且立刻出现在列表', listed, NEW_LOGIN)

/* 新账号能真登录：另开一个 context 走登录表单 */
const guest = await browser.newContext({ viewport: { width: 1280, height: 800 } })
const gp = await guest.newPage()
await gp.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await gp.waitForTimeout(1200)
await dismissOverlays(gp)
const noSignup = await gp.evaluate(() => !document.body.innerText.includes('没有账号？'))
check('需求4 · 登录页不再有自助注册入口', noSignup)
await gp.screenshot({ path: `${OUT}/live-admin-login.png` })

const loginRes = await gp.evaluate(
  async ([base, u, p]) => {
    const r = await fetch(`${base}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    })
    return { status: r.status, body: (await r.text()).slice(0, 160) }
  },
  [BASE, NEW_LOGIN, 'Verify!2026Loci'],
)
check('需求4 · 新建账号可直接登录', loginRes.status === 200, JSON.stringify(loginRes))

const signupRes = await gp.evaluate(async (base) => {
  const r = await fetch(`${base}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'probe@example.com', password: 'Probe!2345678' }),
  })
  return r.status
}, BASE)
check('需求4 · 自助注册端点已关闭', signupRes === 403, `HTTP ${signupRes}`)
await guest.close()

/* —— 需求 5/6/7：中文枚举、拆列、公共表格 + 分页 —— */
const MACHINE_CODES =
  /\b(admin\.(set_role|set_status|set_quota|reset_password|create_user|announcement)|account\.(login|social_login|change_password|create_api_key)|__primary__)\b|(^|[^A-Za-z])(Active|Pending|Disabled|Info|Warn|Critical)([^A-Za-z]|$)/

const TABS = [
  ['平台总览', 'overview'],
  ['用户管理', 'users'],
  ['配额管理', 'quota'],
  ['登录日志', 'logins'],
  ['审计日志', 'audit'],
  ['全站公告', 'announcements'],
]

for (const [label, slug] of TABS) {
  await page.getByRole('menuitem', { name: label }).click()
  await page.waitForTimeout(1600)
  await page.screenshot({ path: `${OUT}/live-admin-${slug}.png` })

  const text = await page.evaluate(() => document.querySelector('.admin-content')?.innerText || '')
  const bad = text.match(MACHINE_CODES)
  check(`需求5 · ${label} 界面无英文机器码`, !bad, bad ? bad[0] : '')

  const noDocScroll = await page.evaluate(
    () => document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1,
  )
  check(`${label} · 无文档级滚动条`, noDocScroll)

  if (['users', 'logins', 'audit', 'announcements'].includes(slug)) {
    const pager = await page.evaluate(
      () => document.querySelectorAll('.admin-content .el-pagination').length,
    )
    check(`需求7 · ${label} 带分页器`, pager === 1, `pagination=${pager}`)
  }
}

/* 登录日志真读到了刚才那次登录，且按时间倒序 */
await page.getByRole('menuitem', { name: '登录日志' }).click()
await page.waitForTimeout(1800)
const loginRows = await page.evaluate(() =>
  [...document.querySelectorAll('.admin-content .el-table__body tr')].map((tr) =>
    [...tr.querySelectorAll('td .cell')].map((c) => c.innerText.trim()),
  ),
)
check('需求7 · 登录日志有真实记录', loginRows.length > 0, `${loginRows.length} 行`)
check(
  '需求7 · 登录日志按时间倒序',
  loginRows.length < 2 || loginRows[0][0] >= loginRows[loginRows.length - 1][0],
  `${loginRows[0]?.[0]} → ${loginRows[loginRows.length - 1]?.[0]}`,
)
check(
  '需求5 · 登录方式渲染为中文',
  loginRows.every((r) => /账号登录|第三方登录/.test(r[2] || '')),
  loginRows[0]?.join(' | '),
)

/* 审计日志读到了刚才的建号动作，且动作名是中文 */
await page.getByRole('menuitem', { name: '审计日志' }).click()
await page.waitForTimeout(1800)
const auditText = await page.evaluate(
  () => document.querySelector('.admin-content')?.innerText || '',
)
check('需求7 · 审计日志记下了「新增用户」', auditText.includes('新增用户'))

/* 操作列收敛 + 分列 */
await page.getByRole('menuitem', { name: '用户管理' }).click()
await page.waitForTimeout(1600)
const headers = await page.evaluate(() =>
  [...document.querySelectorAll('.admin-content .el-table__header th .cell')].map((n) =>
    n.innerText.trim(),
  ),
)
check(
  '需求6 · 用户名称/登录账号、注册时间/最后登录时间各自成列',
  ['用户名称', '登录账号', '注册时间', '最后登录时间'].every((h) => headers.includes(h)),
  headers.join(' | '),
)
const rowActions = await page.evaluate(() => {
  const cell = document.querySelector('.admin-content .row-actions')
  if (!cell) return null
  return {
    buttons: cell.querySelectorAll(':scope > .row-actions__slot > .el-button').length,
    more: cell.querySelector('.el-dropdown .el-button')?.innerText.trim() || '',
  }
})
check(
  '需求5 · 操作列只留启用/停用，其余进「更多」',
  rowActions && rowActions.buttons === 1 && rowActions.more === '更多',
  JSON.stringify(rowActions),
)

/* 需求1：装饰性左竖条 */
const bars = await page.evaluate(() =>
  [...document.querySelectorAll('body *')]
    .filter((el) => {
      const cs = getComputedStyle(el)
      const w = parseFloat(cs.borderLeftWidth) || 0
      if (w < 2 || cs.borderLeftStyle === 'none') return false
      const others =
        (parseFloat(cs.borderTopWidth) || 0) +
        (parseFloat(cs.borderRightWidth) || 0) +
        (parseFloat(cs.borderBottomWidth) || 0)
      if (others > 0) return false
      return !/transparent|rgba\(0, 0, 0, 0\)/.test(cs.borderLeftColor)
    })
    .map((el) => `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 50)}`)
    .slice(0, 8),
)
check('需求1 · 管理后台无装饰性左竖条', bars.length === 0, bars.join(' | '))

check('控制台无未处理错误', errs.length === 0, errs.slice(0, 3).join(' | '))

await browser.close()

const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} PASS`)
if (failed.length) {
  console.log('FAILED:\n' + failed.map((f) => `  - ${f.name} ${f.detail || ''}`).join('\n'))
  process.exit(1)
}

/**
 * 管理后台改版自查：真浏览器、真路由、mock 全部 /api，逐个分区截图 + 断言。
 *
 * 跑：cd frontend
 *     bun run build && bun run preview --host 127.0.0.1 --port 4174   (另一个终端)
 *  bun e2e/admin-shots.mjs
 * 产物：frontend/artifacts/admin-*.png + 控制台逐条 PASS/FAIL。
 *
 * 这个脚本只做**核验**，不改产品代码：断言读的是真实 DOM 文本与真实计算样式，
 * 源码 grep 证明不了「渲染出来长什么样」。
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const BASE = process.env.ADMIN_BASE || 'http://127.0.0.1:4174'
const OUT = process.env.AUDIT_OUT || 'artifacts'
const FIXED_NOW = new Date(2026, 7, 29, 10, 42, 5)
const results = []

function check(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`)
}

const admin = {
  id: 'u-admin',
  username: 'lociAdmin',
  display_name: '平台管理员',
  avatar_url: '',
  bio: '',
  role: 'admin',
  created_at: '2026-08-27T00:00:00',
  email: 'admin@example.com',
  email_verified: true,
  status: 'active',
  tenant_id: '__primary__',
  must_change_password: false,
  has_password: true,
}

const QUOTA = {
  llm_monthly_tokens: 300000,
  llm_daily_calls: 200,
  strategy_slots: 20,
  publish_slots: 5,
  job_slots: 5,
  storage_mb: 2048,
}

function makeUser(i) {
  const disabled = i % 5 === 4
  return {
    id: `u-${i}`,
    tenant_id: i === 0 ? '__primary__' : `u-${i}`,
    username: i === 0 ? 'lociAdmin' : `trader${String(i).padStart(2, '0')}`,
    email: i % 3 === 0 ? '' : `trader${i}@example.com`,
    display_name: i === 0 ? '平台管理员' : `交易员 ${i}`,
    role: i === 0 ? 'admin' : 'member',
    status: disabled ? 'disabled' : i % 7 === 3 ? 'pending' : 'active',
    avatar_url: '',
    bio: '',
    email_verified_at: i % 2 === 0 ? '2026-08-27T02:11:00' : null,
    created_at: `2026-0${(i % 8) + 1}-1${i % 9}T08:12:00`,
    updated_at: '2026-08-28T09:00:00',
    last_login_at: i % 4 === 1 ? null : `2026-08-2${i % 9}T21:03:11`,
    must_change_password: false,
    quota: i === 0 ? { ...QUOTA, llm_monthly_tokens: -1 } : QUOTA,
    usage: { llm_tokens: i * 1731 },
  }
}

const USERS = Array.from({ length: 23 }, (_, i) => makeUser(i))

const AUDIT_ACTIONS = [
  'admin.set_role',
  'admin.set_status',
  'admin.set_quota',
  'admin.reset_password',
  'admin.create_user',
  'admin.announcement',
  'account.change_password',
  'account.create_api_key',
]

function makeAudit(i) {
  return {
    id: `aud_${i}`,
    occurred_at: `2026-08-2${9 - (i % 9)}T1${i % 9}:2${i % 6}:0${i % 9}`,
    actor_id: 'u-admin',
    actor_name: i % 6 === 5 ? '' : 'lociAdmin',
    action: AUDIT_ACTIONS[i % AUDIT_ACTIONS.length],
    target: i % 4 === 3 ? '' : `u-${i % 23}`,
    outcome: i % 9 === 4 ? 'failed' : 'ok',
    detail_json: i % 3 === 0 ? '{}' : JSON.stringify({ role: 'member', status: 'active' }),
    ip: `10.0.${i % 5}.${i + 12}`,
  }
}

const AUDIT = Array.from({ length: 42 }, (_, i) => makeAudit(i))

function makeLogin(i) {
  return {
    id: `aud_login_${i}`,
    occurred_at: `2026-08-2${9 - (i % 9)}T0${i % 9}:1${i % 6}:4${i % 9}`,
    actor_id: `u-${i % 23}`,
    actor_name: i === 0 ? 'lociAdmin' : `trader${String(i % 23).padStart(2, '0')}`,
    action: i % 5 === 2 ? 'account.social_login' : 'account.login',
    target: '',
    outcome: i % 4 === 1 ? 'failed' : 'ok',
    detail_json: i % 5 === 2 ? JSON.stringify({ provider: 'wechat_web' }) : '{}',
    ip: i % 6 === 0 ? '2408:8256:3082:1f2a::b1' : `123.45.${i % 9}.${i + 3}`,
  }
}

const LOGINS = Array.from({ length: 37 }, (_, i) => makeLogin(i))

const ANNOUNCEMENTS = [
  {
    id: 'an_1',
    title: '8 月 30 日 02:00 例行维护，预计 20 分钟不可用',
    body_md: '## 维护范围\n\n- 行情库重建索引\n- 策略广场只读\n\n维护期间不影响已下发的选股结果。',
    level: 'warn',
    published_at: '2026-08-28T10:00:00',
    expires_at: '2026-08-31T00:00:00',
    created_by: 'lociAdmin',
    created_at: '2026-08-28T09:55:00',
    updated_at: '2026-08-28T09:55:00',
  },
  {
    id: 'an_2',
    title: '新增「登录日志」分区，可按账号与来源 IP 追溯',
    body_md: '登录日志支持分页与倒序，失败登录整行标注。',
    level: 'info',
    published_at: '2026-08-29T08:00:00',
    expires_at: null,
    created_by: 'lociAdmin',
    created_at: '2026-08-29T07:58:00',
    updated_at: '2026-08-29T07:58:00',
  },
  {
    id: 'an_3',
    title: '发现异地登录请立即修改口令并注销其他设备',
    body_md: '若发现非本人登录，请在「设置 → 账号安全」注销其他会话。',
    level: 'critical',
    published_at: '2026-08-26T19:30:00',
    expires_at: '2026-09-30T00:00:00',
    created_by: 'lociAdmin',
    created_at: '2026-08-26T19:28:00',
    updated_at: '2026-08-26T19:28:00',
  },
]

function page1(list, url) {
  const q = new URL(url).searchParams
  const limit = Number(q.get('limit') || 20)
  const offset = Number(q.get('offset') || 0)
  const keyword = (q.get('keyword') || '').trim()
  const outcome = q.get('outcome') || ''
  const action = q.get('action') || ''
  const status = q.get('status') || ''
  const hit = list.filter((row) => {
    if (status && row.status !== status) return false
    if (outcome && row.outcome !== outcome) return false
    if (action && !String(row.action || '').startsWith(action)) return false
    if (!keyword) return true
    return JSON.stringify(row).includes(keyword)
  })
  return { items: hit.slice(offset, offset + limit), total: hit.length }
}

function payloadFor(url) {
  const path = new URL(url).pathname
  if (path.includes('/auth/session'))
    return { authenticated: true, username: admin.username, user: admin }
  if (path.includes('/auth/me')) {
    return { user: admin, identities: [], quota: QUOTA, sessions: [], unread: 0 }
  }
  if (path.includes('/auth/notifications')) return { items: [], unread: 0, announcements: [] }
  if (path.includes('/auth/options')) return { email_signup: false, providers: [] }
  if (path.endsWith('/admin/overview')) {
    return {
      users: USERS.length,
      admins: 1,
      top_llm_usage: USERS.slice(1, 11).map((u, i) => ({
        user_id: u.id,
        period: '2026-08',
        metric: 'llm_tokens',
        value: (11 - i) * 12345,
        updated_at: '2026-08-29T09:00:00',
        username: u.username,
        display_name: u.display_name,
      })),
      recent_audit: AUDIT.slice(0, 20),
      announcements: ANNOUNCEMENTS,
      tenants: USERS.map((u) => u.tenant_id),
    }
  }
  if (path.endsWith('/admin/users')) return page1(USERS, url)
  if (path.endsWith('/admin/audit')) return page1(AUDIT, url)
  if (path.endsWith('/admin/logins')) return page1(LOGINS, url)
  if (path.endsWith('/admin/announcements')) return { items: ANNOUNCEMENTS }
  if (path.startsWith('/api/admin/')) return { ok: true }
  return {}
}

async function open(browser, path) {
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
  await page.clock.setFixedTime(FIXED_NOW)
  await page.route(
    (url) => new URL(url).pathname.startsWith('/api/'),
    (route) => {
      const endpoint = new URL(route.request().url()).pathname
      // 登录页必须以未登录会话打开，否则实际上检查的是被重定向后的盘面。
      if (path === '/login' && endpoint.endsWith('/auth/session')) {
        return route.fulfill({ json: { authenticated: false, user: null } })
      }
      return route.fulfill({ json: payloadFor(route.request().url()) })
    },
  )
  const errs = []
  page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    if (/Failed to load resource|favicon|net::ERR|ResizeObserver/i.test(t)) return
    errs.push('console: ' + t.slice(0, 180))
  })
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  page.__errs = errs
  return page
}

/** 文档级滚动条是硬禁项（AGENTS.md §3.7.1） */
async function noDocScroll(page) {
  return page.evaluate(
    () => document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1,
  )
}

/*
 * 「装饰性左竖条」的机器判据：只有左边框、另外三边为 0、且左边框 >= 2px 有颜色。
 * 结构性列分隔（指数带、行情格）都是 1px 且成组出现，不落进这个判据。
 */
async function decorativeLeftBars(page) {
  return page.evaluate(() =>
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
      .map((el) => `${el.tagName.toLowerCase()}.${el.className?.toString().slice(0, 60)}`)
      .slice(0, 8),
  )
}

/** 界面上一个后端机器码都不许露 */
const MACHINE_CODES =
  /\b(admin\.(set_role|set_status|set_quota|reset_password|create_user|announcement)|account\.(login|social_login|change_password|create_api_key)|__primary__)\b|(^|[^A-Za-z])(Active|Pending|Disabled|Info|Warn|Critical)([^A-Za-z]|$)/

mkdirSync(OUT, { recursive: true })
// headless shell 在这台开发机上连不上调试端口（launch 超时），改用完整 chromium
const browser = await chromium.launch({ channel: 'chromium' })

const TABS = [
  ['平台总览', 'overview'],
  ['用户管理', 'users'],
  ['配额管理', 'quota'],
  ['登录日志', 'logins'],
  ['审计日志', 'audit'],
  ['全站公告', 'announcements'],
]

{
  const page = await open(browser, '/admin')
  const rail = await page.evaluate(() =>
    [...document.querySelectorAll('.rail-nav .el-menu-item')].map((n) => n.innerText.trim()),
  )
  check(
    '左栏 6 个分区且全中文',
    rail.length === 6 && rail.every((t) => !/[A-Za-z]/.test(t)),
    rail.join(' / '),
  )

  // 左侧竖条：选中项不许再有 2px 的 border-inline-start
  const activeBorder = await page.evaluate(() => {
    const el = document.querySelector('.rail-nav .el-menu-item.is-active')
    if (!el) return null
    const cs = getComputedStyle(el)
    return { left: cs.borderInlineStartWidth, right: cs.borderInlineEndWidth, top: cs.borderTopWidth, bottom: cs.borderBottomWidth, bg: cs.backgroundColor }
  })
  check(
    '分区选中态无单独左竖条（允许完整细边框）',
    activeBorder && parseFloat(activeBorder.left) <= 1 && ['right', 'top', 'bottom'].every(side => activeBorder[side] === activeBorder.left),
    JSON.stringify(activeBorder),
  )

  for (const [label, slug] of TABS) {
    await page.getByRole('menuitem', { name: label }).click()
    await page.waitForTimeout(1200)
    await page.screenshot({ path: `${OUT}/admin-${slug}.png`, fullPage: false })

    const text = await page.evaluate(
      () => document.querySelector('.admin-content')?.innerText || '',
    )
    const bad = text.match(MACHINE_CODES)
    check(`${label} · 界面无英文机器码`, !bad, bad ? bad[0] : '')
    check(`${label} · 无文档级滚动条`, await noDocScroll(page))

    const bars = await decorativeLeftBars(page)
    check(`${label} · 无装饰性左竖条`, bars.length === 0, bars.join(' | '))

    /*
     * 行高判据看的是「有没有单元格折行」，不是行的绝对像素：
     * 一行文字 19px、`el-tag--small` 28px、行内文字按钮 30px 都是全站既有控件高度，
     * 折成两行才会跳到 37px 以上——那才是密度被破坏。
     */
    const cellHeights = await page.evaluate(() => {
      const tr = document.querySelector('.admin-content .el-table__body tr')
      if (!tr) return null
      const cells = [...tr.querySelectorAll('td .cell')].map((c) =>
        Math.round(c.getBoundingClientRect().height),
      )
      return { row: Math.round(tr.getBoundingClientRect().height), max: Math.max(...cells, 0) }
    })
    if (cellHeights) {
      check(
        `${label} · 表格单元格未折行`,
        cellHeights.max <= 32,
        `行 ${cellHeights.row}px / 最高单元格 ${cellHeights.max}px`,
      )
    }

    if (['users', 'logins', 'audit', 'announcements'].includes(slug)) {
      const pager = await page.evaluate(
        () => document.querySelectorAll('.admin-content .el-pagination').length,
      )
      check(`${label} · 带分页器`, pager === 1, `pagination=${pager}`)
    }
  }

  // 操作列只留 1 颗常驻按钮 + 更多
  await page.getByRole('menuitem', { name: '用户管理' }).click()
  await page.waitForTimeout(1200)
  const rowActions = await page.evaluate(() => {
    const row = [...document.querySelectorAll('.admin-content .el-table__body tr')].find(el => el.getBoundingClientRect().height > 0)
    const cell = row?.querySelector('td:last-child .cell')
    if (!cell) return null
    const buttons = [...cell.querySelectorAll('button')].filter(el => el.getBoundingClientRect().height > 0)
    const more = buttons.filter(el => el.closest('.el-dropdown'))
    return {
      buttons: buttons.filter(el => !el.closest('.el-dropdown')).length,
      more: more.length === 1 ? more[0].innerText.trim() : '',
    }
  })
  check(
    '用户管理 · 操作列只留 1 颗常驻按钮 + 「更多」',
    rowActions && rowActions.buttons === 1 && rowActions.more === '更多',
    JSON.stringify(rowActions),
  )

  const headers = await page.evaluate(() =>
    [...document.querySelectorAll('.admin-content .el-table__header th .cell')].map((n) =>
      n.innerText.trim(),
    ),
  )
  check(
    '用户管理 · 用户名称/登录账号 与 注册时间/最后登录时间 各自成列',
    ['用户名称', '登录账号', '注册时间', '最后登录时间'].every((h) => headers.includes(h)),
    headers.join(' | '),
  )

  // 新增用户入口
  const createButton = page.getByRole('button', { name: '新增', exact: true })
  check('用户管理 · 有新增账号入口', await createButton.isVisible())

  await createButton.click()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}/admin-create-user.png` })
  const dialogLabels = await page.evaluate(() =>
    [...document.querySelectorAll('.el-dialog .el-form-item__label')].map((n) =>
      n.innerText.trim(),
    ),
  )
  check(
    '新增用户弹窗 · 六个中文字段',
    ['登录账号', '用户名称', '初始口令', '邮箱', '角色', '账号状态'].every((l) =>
      dialogLabels.some((x) => x.includes(l)),
    ),
    dialogLabels.join(' / '),
  )

  check('控制台无未处理错误', page.__errs.length === 0, page.__errs.slice(0, 3).join(' | '))
  await page.close()
}

// 全站抽查：装饰性左竖条不应再出现在任何主路由上
for (const route of ['/', '/pool', '/ops', '/quant', '/research', '/insights', '/winrate']) {
  const page = await open(browser, route)
  const bars = await decorativeLeftBars(page)
  check(`全站 ${route} · 无装饰性左竖条`, bars.length === 0, bars.join(' | '))
  await page.close()
}

// 登录页不许再有「注册」入口
{
  const page = await open(browser, '/login')
  await page.locator('#auth-main').waitFor({ state: 'visible', timeout: 10000 })
  check('登录页 · 未被重定向', new URL(page.url()).pathname === '/login')
  const hasSignup = await page.evaluate(() => document.body.innerText.includes('没有账号？'))
  check('登录页 · 已撤下自助注册入口', !hasSignup)
  await page.screenshot({ path: `${OUT}/admin-login.png` })
  await page.close()
}

await browser.close()

const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} PASS`)
if (failed.length) {
  console.log('FAILED:\n' + failed.map((f) => `  - ${f.name} ${f.detail || ''}`).join('\n'))
  process.exit(1)
}

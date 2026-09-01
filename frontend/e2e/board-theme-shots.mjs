import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const BASE = process.env.BOARD_BASE || 'http://127.0.0.1:4174'
const OUT = 'artifacts'
const results = []
function check(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
}

const user = {
  id: 'u1', username: 'shot', display_name: '自查用户', avatar_url: '', bio: '',
  role: 'member', created_at: '2026-01-01T00:00:00', email: 's@e.c', email_verified: true,
  status: 'active', must_change_password: false, has_password: true,
}
function payloadFor(url) {
  const p = new URL(url).pathname
  if (p.includes('/auth/session')) return { authenticated: true, username: 'shot', user }
  if (p.includes('/auth/me')) return { user, identities: [], quota: {}, sessions: [], unread: 0 }
  if (p.includes('/auth/notifications')) return { items: [], unread: 0, announcements: [] }
  if (p.includes('/market/bootstrap')) return { needed: false, kind: 'none' }
  return {}
}

mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch({ channel: 'chromium' })

async function open(appearance) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } })
  await ctx.addInitScript((a) => {
localStorage.setItem('loci-appearance', a)
    localStorage.setItem('loci-primary', 'seal')
    // 不要在这里清 loci-live-ink：addInitScript 每次导航都会重跑，会把「偏好记住」这条用例的前提抹掉
  }, appearance)
  const page = await ctx.newPage()
  await page.route((u) => new URL(u).pathname.startsWith('/api/'), (r) => r.fulfill({ json: payloadFor(r.request().url()) }))
  await page.goto(BASE + '/live', { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  return { ctx, page }
}

function readRoot(page) {
  return page.evaluate(() => ({
    appearance: document.documentElement.getAttribute('data-appearance'),
    dark: document.documentElement.classList.contains('dark'),
    boardBg: getComputedStyle(document.querySelector('.live-board')).backgroundColor,
    sidebarBg: getComputedStyle(document.querySelector('.app-sidebar') || document.body).backgroundColor,
  }))
}

for (const appearance of ['day', 'paper', 'ink']) {
  const { ctx, page } = await open(appearance)
  const state = await readRoot(page)
  check(`外观 ${appearance} · 大屏不改 <html>`, state.appearance === appearance, JSON.stringify(state))
  await page.screenshot({ path: `${OUT}/board-${appearance}.png` })

  if (appearance === 'day') {
    // 打开「暗色」：只影响本页，且刷新后仍记住
    await page.getByRole('button', { name: '暗色' }).click()
    await page.waitForTimeout(600)
    const on = await readRoot(page)
    check('点「暗色」后本页钉墨黑', on.appearance === 'ink' && on.dark, JSON.stringify(on))
    await page.screenshot({ path: `${OUT}/board-day-inkon.png` })

    // 离开大屏 → 必须还给 day
    await page.getByRole('button', { name: '返回' }).click()
    await page.waitForTimeout(1500)
const back = await readRoot(page).catch(() => null)
    const after = await page.evaluate(() => document.documentElement.getAttribute('data-appearance'))
    check('离开大屏还原用户外观', after === 'day', String(after))
    await page.screenshot({ path: `${OUT}/board-back-to-pulse.png` })

    // 再进大屏：偏好被记住
    await page.goto(BASE + '/live', { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    const again = await page.evaluate(() => document.documentElement.getAttribute('data-appearance'))
    check('偏好记住：再进大屏仍是墨黑', again === 'ink', String(again))
    void back
  }
  await ctx.close()
}

await browser.close()
const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} PASS`)
if (failed.length) process.exit(1)

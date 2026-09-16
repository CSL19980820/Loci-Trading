/**
 * 一次性视觉验收：截登录 / 主壳 / 盯盘 / 工坊 / 主题弹窗。
 * 前置：bun run preview 起在 4174。
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const BASE = process.env.AUDIT_BASE || 'http://127.0.0.1:4174'
const OUT = 'artifacts'
mkdirSync(OUT, { recursive: true })

const user = {
  id: 'u1',
  username: 'shot',
  display_name: '自查用户',
  avatar_url: '',
  bio: '',
  role: 'member',
  created_at: '2026-01-01T00:00:00',
  email: 's@e.c',
  email_verified: true,
  status: 'active',
  must_change_password: false,
  has_password: true,
}

function payloadFor(url) {
  const p = new URL(url).pathname
  if (p.includes('/auth/session')) return { authenticated: true, username: 'shot', user }
  if (p.includes('/auth/me')) return { user, identities: [], quota: {}, sessions: [], unread: 0 }
  if (p.includes('/auth/notifications')) return { items: [], unread: 0, announcements: [] }
  if (p.includes('/market/bootstrap')) return { needed: false, kind: 'none' }
  return {}
}

const browser = await chromium.launch()
const shots = []

async function shot(name, path, { auth = true, after } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await ctx.addInitScript(() => {
    localStorage.setItem('loci-appearance', 'day')
    localStorage.setItem('loci-primary', 'seal')
  })
  const page = await ctx.newPage()
  if (auth) {
    await page.route((u) => new URL(u).pathname.startsWith('/api/'), (r) =>
      r.fulfill({ json: payloadFor(r.request().url()) }),
    )
  }
  await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)
  if (after) await after(page)
  const file = `${OUT}/evo-${name}.png`
  await page.screenshot({ path: file, fullPage: false })
  const tokens = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement)
    return {
      appearance: document.documentElement.getAttribute('data-appearance'),
      primary: document.documentElement.getAttribute('data-primary'),
      paper: cs.getPropertyValue('--paper').trim(),
      sheet: cs.getPropertyValue('--sheet').trim(),
      ink: cs.getPropertyValue('--ink').trim(),
      seal: cs.getPropertyValue('--seal').trim(),
      up: cs.getPropertyValue('--up').trim(),
      down: cs.getPropertyValue('--down').trim(),
      radius: cs.getPropertyValue('--radius').trim(),
    }
  })
  shots.push({ name, file, url: page.url(), tokens })
  console.log(`SHOT  ${name}  ${page.url()}  appearance=${tokens.appearance} seal=${tokens.seal}`)
  await ctx.close()
}

await shot('login', '/login', { auth: false })
await shot('pulse', '/')
await shot('live', '/live')
await shot('pool', '/pool')
await shot('quant', '/quant')
await shot('ops', '/ops')
await shot('theme', '/ops', {
  after: async (page) => {
    const clicked = await page.evaluate(() => {
      const theme = document.querySelector('.foot-menu-item--theme')
      if (theme) {
        theme.click()
        return 'foot-theme'
      }
      const hit = [...document.querySelectorAll('button, .el-menu-item')].find((el) =>
        /主题/.test(el.textContent || el.getAttribute('aria-label') || ''),
      )
      if (hit) {
        hit.click()
        return hit.textContent || hit.getAttribute('aria-label')
      }
      return null
    })
    await page.waitForTimeout(600)
    const open = await page.locator('.theme-dialog, .el-overlay, .el-dialog').count()
    console.log(`THEME  click=${clicked} overlays=${open}`)
  },
})

const nightCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await nightCtx.addInitScript(() => {
  localStorage.setItem('loci-appearance', 'night')
  localStorage.setItem('loci-primary', 'seal')
})
const night = await nightCtx.newPage()
await night.route((u) => new URL(u).pathname.startsWith('/api/'), (r) =>
  r.fulfill({ json: payloadFor(r.request().url()) }),
)
await night.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' })
await night.waitForTimeout(1200)
await night.screenshot({ path: `${OUT}/evo-pulse-night.png` })
const nightTokens = await night.evaluate(() => ({
  appearance: document.documentElement.getAttribute('data-appearance'),
  paper: getComputedStyle(document.documentElement).getPropertyValue('--paper').trim(),
  ink: getComputedStyle(document.documentElement).getPropertyValue('--ink').trim(),
  up: getComputedStyle(document.documentElement).getPropertyValue('--up').trim(),
}))
shots.push({ name: 'pulse-night', file: `${OUT}/evo-pulse-night.png`, tokens: nightTokens })
console.log(`SHOT  pulse-night  appearance=${nightTokens.appearance} up=${nightTokens.up}`)
await nightCtx.close()

await browser.close()
console.log(JSON.stringify(shots.map((s) => ({ name: s.name, tokens: s.tokens })), null, 2))

import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

const base = process.env.ROUTE_SMOKE_BASE || 'http://127.0.0.1:5174'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const out = path.join(root, '.local/shadcn-deploy-20260922', `mobile-more-${Date.now()}`)
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch()
const results = []
try {
  for (const width of [390, 600]) for (const theme of ['day', 'night']) {
    const context = await browser.newContext({ viewport: { width, height: 844 }, hasTouch: true, reducedMotion: 'reduce', serviceWorkers: 'block' })
    await context.addInitScript(theme => localStorage.setItem('loci-appearance', theme), theme)
    const page = await context.newPage()
    const row = { width, theme, errors: [], gaps: [] }
    results.push(row)
    page.on('pageerror', error => row.errors.push(String(error)))
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (request.method() !== 'GET') return route.fulfill({ status: 405, body: '{}' })
      const assistant = {
        '/api/ai/tools': { provider_configured: true, tools: [] },
        '/api/ai/sessions': [], '/api/ai/memories': [],
        '/api/ai/profile': { content: '', updated_at: null },
      }
      const fixture = url.pathname in assistant ? { body: assistant[url.pathname] } : routeFixture(url, 'pulse')
      if (!fixture) row.gaps.push(url.pathname)
      return route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? {}) })
    })
    await page.goto(base, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: '更多导航' }).tap()
    const menu = page.locator('.mobile-more-drawer')
    await menu.waitFor({ state: 'visible' })
    await page.waitForTimeout(450)
    row.items = await menu.locator('.more-link').evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect(), icon = node.querySelector('.more-link__icon-wrap').getBoundingClientRect(), label = node.querySelector('.more-link__label').getBoundingClientRect()
      return { text: node.textContent.trim(), x: box.x, y: box.y, width: box.width, height: box.height, iconWidth: icon.width, iconHeight: icon.height, labelHeight: label.height, labelFits: label.bottom <= box.bottom && label.top >= box.top }
    }))
    row.overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    row.drawer = await menu.evaluate(el => {
      const drawer = el.getBoundingClientRect(), body = el.querySelector('.more-drawer-body').getBoundingClientRect()
      return { height: drawer.height, bottomGap: innerHeight - drawer.bottom, trailingSpace: drawer.bottom - body.bottom }
    })
    row.screenshot = path.join(out, `${width}-${theme}.png`)
    await page.screenshot({ path: row.screenshot })
    if (!process.env.MENU_SMOKE_OBSERVE) {
      assert.deepEqual(row.items.map(item => item.text), ['AI 助手', '胜率', '工坊', '行情', '策稿'])
      for (const item of row.items) {
        assert.equal(item.iconHeight, 48, `${item.text} icon squashed`)
        assert.equal(item.iconWidth, 48)
        assert.ok(item.labelHeight >= 14 && item.labelFits, `${item.text} label clipped`)
        assert.ok(item.width >= 44 && item.height >= 44)
      }
      assert.ok(row.items.slice(0, 4).every(item => Math.abs(item.y - row.items[0].y) < 1))
      assert.ok(row.items[4].y > row.items[0].y)
      assert.equal(row.overflow, false)
      assert.ok(row.drawer.height < 500, `Menu drawer has excessive empty height: ${row.drawer.height}`)
      assert.ok(Math.abs(row.drawer.bottomGap) <= 1, 'Bottom drawer is not bottom anchored')
      assert.ok(row.drawer.trailingSpace < 30, `Excessive trailing space: ${row.drawer.trailingSpace}`)
      await menu.getByRole('button', { name: 'AI 助手', exact: true }).tap()
      await menu.waitFor({ state: 'hidden' })
      await page.getByRole('dialog').waitFor({ state: 'visible' })
      row.assistantOpened = true
      await page.getByRole('button', { name: '关闭助手', exact: true }).tap()
      await page.getByRole('dialog').waitFor({ state: 'hidden' })
      await page.getByRole('button', { name: '更多导航' }).tap()
      await menu.getByRole('link', { name: '工坊', exact: true }).tap()
      await page.waitForURL('**/quant')
      await menu.waitFor({ state: 'hidden' })
      row.navigationPassed = true
      assert.deepEqual(row.errors, [])
      assert.deepEqual(row.gaps, [])
    }
    await context.close()
  }
} finally {
  await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results, null, 2))
  console.log(JSON.stringify({ out, results }, null, 2))
  await browser.close()
}

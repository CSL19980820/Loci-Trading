import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'

// Real application routes, all API traffic intercepted; no server-side state is used.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const base = process.env.ROUTE_SMOKE_BASE || 'http://127.0.0.1:5174'
const out = path.join(root, '.local/shadcn-foundation-20260922', `routes-${new Date().toISOString().replace(/[:.]/g, '-')}`)
await fs.mkdir(out, { recursive: true })
const routes = [
  ['pulse', '/'], ['pool', '/pool'], ['data', '/data'], ['agents', '/agents'],
  ['agent-detail', '/agents/smoke-agent'], ['quant', '/quant'], ['strategy-converter', '/strategy-converter'],
  ['winrate', '/winrate'], ['screen-history', '/screen-history'], ['ops', '/ops'],
  ['archive', '/archive/000001'], ['account', '/account'], ['admin', '/admin'],
  ['login', '/login'], ['auth-unavailable', '/auth-unavailable'], ['peek', '/peek'],
]
const chosen = process.env.ROUTE_SMOKE_ONLY?.split(',')
const widths = process.env.ROUTE_SMOKE_WIDTHS?.split(',').map(Number) || [1440, 390]
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of widths) for (const [name, urlPath] of routes.filter(([name]) => !chosen || chosen.includes(name))) {
    const context = await browser.newContext({ viewport: { width, height: 960 }, serviceWorkers: 'block', reducedMotion: 'reduce' })
    const page = await context.newPage()
    const row = { name, width, urlPath, errors: [], componentWarnings: [], fixtureGaps: [], blockedWrites: [], blockedExternal: [], api: [], tabs: [], screenshots: [] }
    results.push(row)
    page.on('pageerror', error => row.errors.push(String(error)))
    page.on('console', message => {
      if (/Failed to resolve component|Unhandled error|Invalid vnode|Invalid prop/.test(message.text())) row.componentWarnings.push(message.text())
    })
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) { row.blockedExternal.push(url.href); return route.abort() }
      if (!url.pathname.startsWith('/api/')) return route.continue()
      row.api.push(`${request.method()} ${url.pathname}`)
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        row.blockedWrites.push(`${request.method()} ${url.pathname}`)
        return route.fulfill({ status: 405, contentType: 'application/json', body: JSON.stringify({ detail: '隔离验收禁止写操作' }) })
      }
      const fixture = routeFixture(url, name)
      if (!fixture) row.fixtureGaps.push(url.pathname)
      await route.fulfill({ status: fixture?.status || (fixture ? 200 : 404), contentType: 'application/json', body: JSON.stringify(fixture?.body ?? { detail: `隔离夹具未提供 ${url.pathname}，请重试` }) })
    })
    try {
      // Archive closes via browser history; seed a real application origin page.
      if (name === 'archive') await page.goto(`${base}/`, { waitUntil: 'networkidle', timeout: 45000 })
      await page.goto(`${base}${urlPath}`, { waitUntil: 'networkidle', timeout: 45000 })
      await page.locator('#app').waitFor({ state: 'visible' })
      await page.waitForTimeout(350)
      row.location = new URL(page.url()).pathname
      row.text = (await page.locator('#app').innerText()).slice(0, 1600)
      row.initial = await inspect(page)
      if (['pulse', 'agent-detail', 'ops', 'account', 'admin', 'login', 'archive'].includes(name)) {
        const filename = `${name}-${width}-initial.png`
        await page.screenshot({ path: path.join(out, filename), fullPage: true })
        row.screenshots.push(filename)
      }
      if (row.location !== urlPath.split('?')[0]) row.errors.push(`Unexpected redirect: ${row.location}`)
      if (row.text.trim().length < 8) row.errors.push('Application rendered no meaningful text')
      // Read-only section navigation only; do not click commands or mutation buttons.
      const tabIds = await page.locator('[role="tab"]:visible').evaluateAll(nodes => nodes.map(node => node.id).filter(Boolean))
      for (const id of tabIds.slice(0, 8)) {
        const tab = page.locator(`[id=${JSON.stringify(id)}]`)
        if (!await tab.isVisible()) continue
        await tab.click()
        await page.waitForTimeout(200)
        row.tabs.push({ id, ...(await inspect(page)) })
      }
      if (['pulse', 'agent-detail', 'ops', 'account', 'admin', 'login', 'archive'].includes(name) || row.errors.length || row.componentWarnings.length) {
        const filename = `${name}-${width}.png`
        await page.screenshot({ path: path.join(out, filename), fullPage: true })
        row.screenshots.push(filename)
      }
      if (name === 'archive') {
        const dialog = page.getByRole('dialog', { name: '个股档案', exact: true })
        await dialog.waitFor({ state: 'visible' })
        await dialog.getByRole('button', { name: /^选股记录/ }).click()
        const history = page.getByRole('dialog', { name: /隔离样本 · 选股记录/ })
        await history.waitFor({ state: 'visible' })
        await page.keyboard.press('Escape')
        await history.waitFor({ state: 'hidden' })
        if (new URL(page.url()).pathname !== '/archive/000001') throw new Error('Nested dialog Escape also closed the archive route')
        await dialog.waitFor({ state: 'visible' })
        row.archiveNestedEscape = true
        await page.keyboard.press('Escape')
        await page.waitForURL(url => url.pathname === '/', { timeout: 5000 })
        await dialog.waitFor({ state: 'hidden' })
        row.archiveEscapeReturn = new URL(page.url()).pathname
        await page.goto(`${base}${urlPath}`, { waitUntil: 'networkidle' })
        await dialog.getByRole('button', { name: /^返回/ }).first().click()
        await page.waitForURL(url => url.pathname === '/', { timeout: 5000 })
        await dialog.waitFor({ state: 'hidden' })
        row.archiveButtonReturn = new URL(page.url()).pathname
      }
      if (name === 'auth-unavailable') {
        await page.getByRole('button', { name: '重试', exact: true }).click()
        await page.waitForURL(url => url.pathname === '/', { timeout: 5000 })
        row.authRecoveryReturn = new URL(page.url()).pathname
        row.authRecovery = await inspect(page)
        row.errors.push(...row.authRecovery.issues)
      }
      row.ok = !row.errors.length && !row.componentWarnings.length && !row.initial.issues.length && row.tabs.every(tab => !tab.issues.length)
    } catch (error) { row.errors.push(String(error)); row.ok = false }
    finally {
      row.fixtureGaps = [...new Set(row.fixtureGaps)]
      row.api = [...new Set(row.api)]
      await context.close()
      await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results, null, 2))
      console.log(JSON.stringify({ name, width, ok: row.ok, errors: row.errors, warnings: row.componentWarnings, issues: [...(row.initial?.issues || []), ...row.tabs.flatMap(tab => tab.issues)], fixtureGaps: row.fixtureGaps }))
    }
  }
} finally { await browser.close() }
console.log(`Evidence: ${out}`)
if (results.some(result => !result.ok)) process.exitCode = 1

async function inspect(page) {
  return page.evaluate(() => {
    const visible = node => Boolean(node.getClientRects().length) && getComputedStyle(node).visibility !== 'hidden'
    const issues = []
    if (document.documentElement.scrollWidth > innerWidth + 1) issues.push(`Document horizontal overflow ${document.documentElement.scrollWidth} > ${innerWidth}`)
    const tabs = [...document.querySelectorAll('[role="tab"]')].filter(visible)
    for (const tab of tabs) {
      const controls = tab.getAttribute('aria-controls')
      if (!controls || !document.getElementById(controls)) issues.push(`Tab ${tab.id || tab.textContent} has dangling aria-controls ${controls}`)
    }
    const panels = [...document.querySelectorAll('[role="tabpanel"]')].filter(visible)
    for (const panel of panels) {
      const labelled = panel.getAttribute('aria-labelledby')
      if (!labelled || !labelled.split(/\s+/).every(id => document.getElementById(id))) issues.push(`Panel ${panel.id} has dangling aria-labelledby ${labelled}`)
    }
    for (const node of [...document.querySelectorAll('[role="tabpanel"],.auth-card,.studio-tab-panel,.admin-content,.ops-content,.acct-body')].filter(visible)) {
      const box = node.getBoundingClientRect()
      if (box.x < -1 || box.right > innerWidth + 1) issues.push(`Content outside viewport: ${node.id || node.className} ${Math.round(box.x)}..${Math.round(box.right)}`)
    }
    const ids = [...document.querySelectorAll('[id]')].map(node => node.id).filter(Boolean)
    const duplicates = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))]
    if (duplicates.length) issues.push(`Duplicate ids: ${duplicates.join(', ')}`)
    const duplicateNodes = duplicates.map(id => ({ id, nodes: [...document.querySelectorAll('[id]')].filter(node => node.id === id).map(node => ({ html: node.outerHTML.slice(0, 700), parent: node.parentElement?.outerHTML.slice(0, 1500) })) }))
    return { issues, duplicateNodes, visibleTabs: tabs.length, visiblePanels: panels.length, width: innerWidth, scrollWidth: document.documentElement.scrollWidth }
  })
}

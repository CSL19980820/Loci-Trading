import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'
const out = `../.local/sidebar-20260922-${Date.now()}`
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch()
const results = []
try {
  for (const theme of ['day', 'night']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
    const row = { theme, errors: [] }; results.push(row)
    page.on('pageerror', e => row.errors.push(String(e)))
    await page.addInitScript(theme => localStorage.setItem('loci-appearance', theme), theme)
    await page.route(url => url.pathname.startsWith('/api/'), route => {
      const f = routeFixture(new URL(route.request().url()), 'pulse')
      return route.fulfill({ status: f?.status || (f ? 200 : 404), contentType: 'application/json', body: JSON.stringify(f?.body ?? {}) })
    })
    await page.goto('http://127.0.0.1:5174', { waitUntil: 'networkidle' })
    const sidebar = page.getByLabel('侧边导航', { exact: true })
    await expect(sidebar.getByRole('link', { name: '盘面', exact: true })).toHaveAttribute('aria-current', 'page')
    row.brand = await sidebar.locator('.brand-mark').evaluate(el => ({ color: getComputedStyle(el).color, token: getComputedStyle(el).getPropertyValue('--on-primary').trim(), oldToken: getComputedStyle(el).getPropertyValue('--primary-foreground').trim() }))
    assert.equal(row.brand.color, 'rgb(255, 255, 255)')
    row.expanded = await sidebar.evaluate(el => ({ width: el.getBoundingClientRect().width, links: el.querySelectorAll('.nav-item').length, overflow: el.scrollWidth > el.clientWidth, active: el.querySelectorAll('.nav-item[aria-current=page]').length, groupIcons: [...el.querySelectorAll('.nav-group-trigger>svg:first-child')].map(n => n.outerHTML), itemIcons: [...el.querySelectorAll('.nav-item-icon>svg')].map(n => n.outerHTML) }))
    assert.equal(row.expanded.links, 8); assert.equal(row.expanded.overflow, false); assert.equal(row.expanded.active, 1)
    assert.notEqual(row.expanded.groupIcons[0], row.expanded.itemIcons[0])
    delete row.expanded.groupIcons; delete row.expanded.itemIcons
    await page.screenshot({ path: `${out}/${theme}-expanded.png` })
    await sidebar.getByRole('button', { name: '市场', exact: true }).click()
    await expect(sidebar.getByRole('link', { name: '盘面', exact: true })).toBeHidden()
    await sidebar.getByRole('button', { name: '收起侧栏', exact: true }).click()
    await expect(sidebar.getByRole('link', { name: '盘面', exact: true })).toBeVisible()
    await page.waitForTimeout(250)
    row.collapsed = await sidebar.evaluate(el => ({ width: el.getBoundingClientRect().width, overflow: el.scrollWidth > el.clientWidth, icons: [...el.querySelectorAll('.nav-item-icon')].every(n => n.getBoundingClientRect().width >= 24), labelsHidden: [...el.querySelectorAll('.nav-item-label')].every(n => getComputedStyle(n).display === 'none') }))
    assert.equal(row.collapsed.overflow, false); assert.equal(row.collapsed.icons, true); assert.equal(row.collapsed.labelsHidden, true)
    await page.screenshot({ path: `${out}/${theme}-collapsed.png` })
    await sidebar.getByRole('button', { name: '展开侧栏', exact: true }).click()
    await expect(sidebar.getByRole('link', { name: '盘面', exact: true })).toBeHidden()
    await sidebar.getByRole('button', { name: '市场', exact: true }).click()
    await sidebar.getByRole('link', { name: '工坊', exact: true }).click()
    await expect(sidebar.getByRole('link', { name: '工坊', exact: true })).toHaveAttribute('aria-current', 'page')
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.getByRole('button', { name: '更多导航' })).toBeVisible()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.deepEqual(row.errors, [])
    row.passed = true
    await page.close()
  }
} finally {
  console.log(JSON.stringify({ out, results }, null, 2))
  await fs.writeFile(`${out}/results.json`, JSON.stringify(results, null, 2))
  await browser.close()
}

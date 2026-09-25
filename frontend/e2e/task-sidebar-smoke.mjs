import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.local', `task-sidebar-${Date.now()}`)
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch()
const results = []
try {
  for (const mode of ['assistant', 'guardian']) {
    const page = await browser.newPage({ viewport: { width: 900, height: 760 } })
    const row = { mode, errors: [] }; results.push(row)
    page.on('pageerror', e => row.errors.push(String(e)))
    await page.goto(`http://127.0.0.1:5174/e2e/fixtures/session-rail.html?inspector=1&mode=${mode}`, { waitUntil: 'networkidle' })
    const rail = page.getByTestId('assistant-task-sidebar')
    await expect(rail.getByRole('tab')).toHaveCount(mode === 'guardian' ? 2 : 5)
    const initial = mode === 'guardian' ? '来源' : '计划'
    await expect(rail.getByRole('tab', { name: new RegExp(initial) })).toHaveAttribute('aria-selected', 'true')
    await page.getByTestId('add-agent').click()
    await expect(rail.getByRole('tab', { name: new RegExp(mode === 'guardian' ? '来源' : '子进程') })).toHaveAttribute('aria-selected', 'true')
    await rail.getByRole('tab', { name: '上下文', exact: true }).click()
    await expect(rail.getByRole('tab', { name: '上下文', exact: true })).toHaveAttribute('aria-selected', 'true')
    if (mode === 'guardian') {
      await expect(rail.getByTestId('guardian-cabin')).toBeVisible()
      await expect(rail.getByRole('button', { name: '助手设置' })).toHaveCount(0)
      await expect(rail).toHaveAttribute('aria-label', '咨询详情')
    } else {
      await expect(rail.getByRole('button', { name: '助手设置' })).toBeVisible()
    }
    await page.waitForTimeout(250)
    await page.screenshot({ path: path.join(out, `${mode}.png`) })
    assert.deepEqual(row.errors, [])
    row.passed = true
    await page.close()
  }
} finally { await browser.close(); await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results,null,2)); console.log(JSON.stringify({out,results},null,2)) }

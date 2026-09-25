import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.local', `session-rail-${Date.now()}`)
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch()
const results = []
try {
  for (const mode of ['assistant', 'guardian']) for (const theme of ['day', 'night']) {
    const page = await browser.newPage({ viewport: { width: 900, height: 760 }, reducedMotion: 'reduce' })
    const row = { mode, theme, errors: [] }; results.push(row)
    page.on('pageerror', e => row.errors.push(String(e)))
    page.on('console', message => { if (message.type() === 'error') row.errors.push(message.text()) })
    const url = `http://127.0.0.1:5174/e2e/fixtures/session-rail.html?mode=${mode}&theme=${theme}`
    await page.goto(url, { waitUntil: 'networkidle' })
    const rail = page.getByTestId('assistant-session-rail'), output = page.getByTestId('event')
    await rail.getByRole('button', { name: '第二条历史', exact: true }).click()
    await expect(output).toHaveText('select:second')
    await rail.getByRole('textbox').fill('第一')
    await expect(rail.locator('.assistant-session-row')).toHaveCount(1)
    await rail.getByRole('textbox').fill('')
    await rail.getByRole('button', { name: mode === 'guardian' ? '新建话题' : '新建对话', exact: true }).click()
    await expect(output).toHaveText('create')
    await rail.getByRole('button', { name: '第二条历史的操作', exact: true }).click()
    if (mode === 'guardian') {
      await expect(page.getByRole('menuitem')).toHaveCount(1)
      await expect(rail.getByRole('button', { name: '多选对话' })).toHaveCount(0)
      await expect(rail.getByRole('button', { name: '助手设置' })).toHaveCount(0)
    } else {
      await expect(page.getByRole('menuitem', { name: '归档', exact: true })).toBeVisible()
    }
    await page.getByRole('menuitem', { name: '删除', exact: true }).click()
    await expect(output).toHaveText('remove:second')
    if (mode === 'assistant') {
      await rail.getByRole('button', { name: '多选对话' }).click()
      await rail.getByRole('checkbox', { name: '选择对话 第一条历史' }).check()
      await rail.getByTestId('session-rail-batch').getByRole('button', { name: '归档', exact: true }).click()
      await expect(output).toHaveText('batch:archive:first')
      await rail.getByRole('button', { name: '助手设置' }).click()
      await expect(output).toHaveText('settings')
    }
    await page.screenshot({ path: path.join(out, `${mode}-${theme}.png`) })
    await rail.getByTestId('session-rail-collapse').click()
    await expect(rail.getByTestId('session-rail-expand')).toBeVisible()
    if (mode === 'guardian') await expect(rail.getByRole('button', { name: '助手设置' })).toHaveCount(0)
    await rail.getByTestId('session-rail-expand').click()
    await page.goto(`${url}&empty=1`, { waitUntil: 'networkidle' })
    await expect(rail).toContainText(mode === 'guardian' ? '还没有话题' : '还没有对话')
    assert.deepEqual(row.errors, [])
    row.passed = true
    await page.close()
  }
} finally { await browser.close(); await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results, null, 2)); console.log(JSON.stringify({out,results},null,2)) }

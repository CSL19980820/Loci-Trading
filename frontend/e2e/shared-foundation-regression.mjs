import { chromium, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const out = '../.local/shadcn-foundation-20260922'
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [1440, 390]) for (const theme of ['day', 'paper', 'night', 'ink']) {
    const page = await browser.newPage({ viewport: { width, height: 1100 }, reducedMotion: 'reduce' })
    page.setDefaultTimeout(10000)
    const errors = [], row = { width, theme, errors, ok: false }; results.push(row)
    page.on('pageerror', e => errors.push(String(e)))
    page.on('console', msg => { if (/Failed to resolve component|Unhandled error/.test(msg.text())) errors.push(msg.text()) })
    await page.route('**/api/**', r => r.abort())
    try {
      await page.goto('http://127.0.0.1:5174/e2e/fixtures/shared-foundation.html', { waitUntil: 'networkidle' })
      await page.evaluate(theme => { document.documentElement.dataset.appearance = theme; document.documentElement.classList.toggle('dark', ['night','ink'].includes(theme)) }, theme)
      await page.locator('input').and(page.getByLabel('密码', { exact: true })).fill('test')
      await page.getByRole('button', { name: '显示密码', exact: true }).click()
      await expect(page.locator('input').and(page.getByLabel('密码', { exact: true }))).toHaveAttribute('type', 'text')
      await page.getByRole('button', { name: '清空输入', exact: true }).click()
      await expect(page.locator('input').and(page.getByLabel('密码', { exact: true }))).toBeFocused()
      await expect(page.locator('input').and(page.getByLabel('密码', { exact: true }))).toHaveValue('')
      await page.getByRole('textbox', { name: '备注', exact: true }).fill('一\n二\n三\n四')
      await expect(page.getByRole('textbox', { name: '备注', exact: true })).toHaveAttribute('aria-invalid', 'true')
      await page.getByRole('button', { name: '下一页', exact: true }).click()
      await expect(page.getByTestId('page')).toHaveText('2 / 10')
      if (width > 640) {
        await page.getByRole('spinbutton', { name: '跳转页码' }).fill('5')
        await page.getByRole('spinbutton', { name: '跳转页码' }).press('Enter')
        await expect(page.getByTestId('page')).toHaveText('5 / 10')
        await expect(page.getByTestId('changes')).toHaveText('2')
      }
      await page.getByRole('button', { name: '切换加载' }).click()
      await expect(page.locator('.busy-overlay')).toHaveCount(0)
      await page.getByRole('button', { name: '切换加载' }).click()
      await expect(page.locator('.busy-overlay [data-slot="spinner"]')).toHaveCount(1)
      await page.getByRole('button', { name: '研究时间', exact: true }).click()
      const times = page.locator('.date-field__times input')
      await expect(times).toHaveCount(2)
      assert.notEqual(await times.nth(0).getAttribute('id'), await times.nth(1).getAttribute('id'))
      await times.nth(0).fill('10:45')
      await page.getByRole('button', { name: '取消', exact: true }).click()
      await page.getByRole('button', { name: '研究时间', exact: true }).click()
      await expect(times.nth(0)).toHaveValue('09:30')
      await page.keyboard.press('Escape')
      const catalog = page.getByRole('listbox', { name: '战法与技能' })
      await catalog.focus(); await page.keyboard.press('End'); await page.keyboard.press('Enter')
      await expect(page.getByTestId('selection')).toHaveText('b / a')
      const jobs = page.getByRole('listbox', { name: '任务列表' })
      await jobs.focus(); await page.keyboard.press('End'); await page.keyboard.press('Enter')
      await expect(page.getByTestId('selection')).toHaveText('b / b')
      const problems = await page.evaluate(() => {
        const ids = [...document.querySelectorAll('[id]')].map(n => n.id)
        return { duplicates: ids.filter((id, i) => ids.indexOf(id) !== i), overflow: document.documentElement.scrollWidth > innerWidth + 1 }
      })
      assert.deepEqual(problems, { duplicates: [], overflow: false }); assert.deepEqual(errors, [])
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({ path: `${out}/shared-${theme}-${width}.png`, fullPage: true })
      row.ok = true
    } catch (error) { row.failure = String(error); console.error(width, theme, row.failure) }
    finally { await page.close(); console.log(JSON.stringify(row)) }
  }
} finally { await browser.close(); await fs.writeFile(`${out}/shared-results.json`, JSON.stringify(results, null, 2)) }
if (results.some(row => !row.ok)) process.exitCode = 1

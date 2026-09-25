import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const out = '../.local/shadcn-foundation-20260922'
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1200, height: 850 } })
const errors = []
page.on('pageerror', error => errors.push(String(error)))
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
await page.route(url => url.pathname.startsWith('/api/'), route => route.fulfill({ json: [] }))
const results = []
async function render(source) {
 return page.evaluate(source => {
  const node = document.createElement('div')
  node.innerHTML = window.__markdownAudit.render(source)
  return { html: node.innerHTML, text: node.textContent, links: [...node.querySelectorAll('a')].map(a => a.getAttribute('href')), strong: [...node.querySelectorAll('strong')].map(node=>node.textContent), unsafe: Boolean(node.querySelector('script,style,iframe,[onerror],[onclick],[style]')) }
 }, source)
}
async function check(name, run) {
 try { await run(); results.push({ name, ok: true }) }
 catch (error) { results.push({ name, ok: false, error: String(error) }) }
}
try {
 await page.goto('http://127.0.0.1:5174/e2e/fixtures/assistant-markdown.html', { waitUntil: 'networkidle' })
 await check('valid-and-legacy-markdown', async () => {
  const valid = await render('**众泰汽车 [000980](https://example.test/q/000980?date=2026-09-21&source=report)** 收 2.24）')
  assert.deepEqual(valid.strong, ['众泰汽车 000980'])
  assert.deepEqual(valid.links, ['https://example.test/q/000980?date=2026-09-21&source=report'])
  const historical = await render('**众泰汽车 [000980]([URL] 收 2.24）')
  assert.equal(historical.text.trim(), '众泰汽车 000980（链接已隐藏） 收 2.24）')
  assert.deepEqual(historical.links, [])
  const masked = await render('**众泰汽车 [000980]([URL])** 收 2.24')
  assert.deepEqual(masked.links, [])
  assert.deepEqual(masked.strong, ['众泰汽车 000980（链接已隐藏）'])
 })
 await check('chromium-sanitization-boundary', async () => {
  const result = await render('[脚本](javascript:alert(1)) <a href="data:text/html,bad">数据</a> <img src="https://example.test/image.png" onerror="alert(1)"><script>alert(1)</script><style>body{display:none}</style><iframe srcdoc="bad"></iframe><b style="color:red" onclick="alert(1)">保留文字</b>')
  assert.equal(result.unsafe, false)
  assert(result.links.every(href => !/^(javascript|data):/i.test(href || '')))
  assert(result.text.includes('保留文字'))
 })
 await check('streaming-remains-literal-until-settled', async () => {
  const incomplete = '**众泰汽车 [000980](https://example.test/q/000980'
  await page.evaluate(content => { window.__markdownAudit.message.value = { id: 'markdown-fixture', role: 'assistant', status: 'streaming', content } }, incomplete)
  await expect(page.locator('.assistant-turn__content')).toHaveText(incomplete)
  await expect(page.locator('.assistant-turn__content a, .assistant-turn__content strong')).toHaveCount(0)
  await page.evaluate(() => { window.__markdownAudit.message.value = { id: 'markdown-fixture', role: 'assistant', status: 'done', content: '**众泰汽车 [000980](https://example.test/q/000980)** 收 2.24' } })
  await expect(page.locator('.assistant-turn__content strong')).toHaveText('众泰汽车 000980')
  await expect(page.locator('.assistant-turn__content a')).toHaveAttribute('href', 'https://example.test/q/000980')
  await page.evaluate(() => { window.__markdownAudit.message.value = { id: 'history-fixture', role: 'assistant', status: 'done', content: '**众泰汽车 [000980]([URL] 收 2.24）' } })
  await expect(page.locator('.assistant-turn__content')).toHaveText('众泰汽车 000980（链接已隐藏） 收 2.24）')
  await page.screenshot({ path: `${out}/markdown-historical-degradation.png`, fullPage: true, animations: 'disabled' })
 })
 assert.deepEqual(errors, [])
} finally {
 await fs.writeFile(`${out}/markdown-results.json`, JSON.stringify({ results, errors }, null, 2))
 await browser.close()
}
console.log(JSON.stringify({ results, errors }, null, 2))
if (results.some(result=>!result.ok)) process.exitCode = 1

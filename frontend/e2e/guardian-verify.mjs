/** 仅对同镜像的一次性验收容器执行，不指向生产账号。 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const base = process.env.VERIFY_BASE || 'http://127.0.0.1:54409'
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw new Error('只允许本机隧道验收地址')
const out = new URL('../../artifacts/guardian/', import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1')
mkdirSync(out, { recursive: true })
const browser = await chromium.launch()
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  const login = await context.request.post(`${base}/api/auth/login`, {
    data: { username: 'guardian_verify', password: process.env.VERIFY_PASS || 'GuardianVerify-2026-Only' },
  })
  if (!login.ok()) throw new Error(`验收账号登录失败 ${login.status()} ${await login.text()}`)
  const page = await context.newPage()
  // 空验收库不启动与守护无关的全市场回填；守护接口仍走真实服务。
  await page.route('**/api/market/bootstrap', async route => {
    if (route.request().method() !== 'GET') return route.fulfill({ status: 200, json: { status: 'idle', needed: false } })
    const response = await route.fetch()
    return route.fulfill({ response, json: { ...await response.json(), needed: false, status: 'idle' } })
  })
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto(`${base}/ops?tab=guardian`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '守护设置', exact: true }).waitFor()
  const bootstrap = page.getByRole('button', { name: '后台继续', exact: true })
  if (await bootstrap.isVisible()) {
    await bootstrap.click()
    await page.locator('.boot-dialog').waitFor({ state: 'hidden' })
  }
  await page.screenshot({ path: `${out}/desktop.png`, fullPage: true, animations: 'disabled' })
  await page.locator('.guardian-workspace').screenshot({ path: `${out}/workspace.png`, animations: 'disabled' })
  const candidate = page.locator('[aria-label="守护股票池"]').getByText('样例·精选A', { exact: true })
  if (await candidate.count()) {
    await page.locator('.guardian-pool-toolbar .el-radio-button__inner').filter({ hasText: /^持有$/ }).click()
    await candidate.waitFor({ state: 'hidden' })
    await page.locator('.guardian-pool-toolbar .el-radio-button__inner').filter({ hasText: /^全部$/ }).click()
    await candidate.waitFor({ state: 'visible' })
  }
  await page.getByRole('button', { name: '守护设置', exact: true }).click()
  const prompt = page.getByRole('textbox', { name: '守护提示词', exact: true })
  await prompt.fill('验收提示词：结合所选战法和真实行情管理模拟仓。')
  await page.screenshot({ path: `${out}/settings.png`, fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '保存配置', exact: true }).click()
  await page.getByRole('dialog', { name: '守护设置', exact: true }).waitFor({ state: 'hidden' })
  const saved = await context.request.get(`${base}/api/ops/guardian`)
  const data = await saved.json()
  if (data.config.prompt !== '验收提示词：结合所选战法和真实行情管理模拟仓。') throw new Error('提示词未保存到真实 API')
  await page.getByRole('button', { name: '守护设置', exact: true }).click()
  await page.getByRole('button', { name: '恢复内置提示词', exact: true }).click()
  await page.getByRole('button', { name: '保存配置', exact: true }).click()
  await page.getByRole('dialog', { name: '守护设置', exact: true }).waitFor({ state: 'hidden' })
  for (const width of [980, 640]) {
    await page.setViewportSize({ width, height: 900 })
    await page.screenshot({ path: `${out}/width-${width}.png`, fullPage: true, animations: 'disabled' })
    const overflow = await page.evaluate(() => ({
      x: document.documentElement.scrollWidth > innerWidth,
      y: document.documentElement.scrollHeight > innerHeight,
    }))
    if (overflow.x || overflow.y) throw new Error(`文档级溢出 ${width}: ${JSON.stringify(overflow)}`)
  }
  if (errors.length) throw new Error(errors.join('\n'))
  console.log(JSON.stringify({ status: 'passed', screenshots: out, widths: [1440, 980, 640], saveAndRestorePrompt: true, pageErrors: errors }))
} finally {
  await browser.close()
}

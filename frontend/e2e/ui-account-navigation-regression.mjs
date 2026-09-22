import { chromium, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'

// All requests are intercepted. These fixtures never connect to a production account.
const out = '../.local/ui-components-20260921/evidence'
await fs.mkdir(out, { recursive:true })
const browser = await chromium.launch({ headless:true })
const results = []
const tradeRows = ['模拟甲','模拟乙'].map((name,i) => ({
  id:`trade-${i}`,code:`00098${i}`,name,side:'buy',action:'buy',quantity:1000,
  price_cents:300,gross_cents:300000,fees_cents:500,commission_cents:490,stamp_tax_cents:0,
  transfer_cents:10,realized_pnl_cents:0,allocated_cost_cents:0,before_quantity:0,after_quantity:1000,
  cash_after_cents:9700000,reason:'模拟成交依据。'.repeat(40),holding_plan:'模拟持仓计划',
  quote_source:'隔离夹具',quote_at:'2026-09-21T14:50:00+08:00',occurred_at:'2026-09-21T14:50:00+08:00',
}))
async function setup(width, view) {
  const page = await browser.newPage({ viewport:{width,height:900} })
  page.setDefaultTimeout(9000)
  const errors=[], requests=[]
  page.on('pageerror',e => errors.push(String(e)))
  page.on('console',m => {if(m.type()==='error') errors.push(m.text())})
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url()); requests.push(url)
    let data=[]
    if(url.pathname.endsWith('/trades')) {
      const term=(url.searchParams.get('keyword') || '').trim()
      const items=tradeRows.filter(row => row.code.includes(term) || row.name.includes(term))
      data={items,total:items.length,offset:0,limit:20}
    }
    await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
  })
  await page.goto(`http://127.0.0.1:5174/e2e/fixtures/ui-audit.html?view=${view}`, {waitUntil:'networkidle'})
  return {page,errors,requests}
}
async function test(name, run) {
  let context
  try {
    context=await run(); assert.deepEqual(context.errors,[])
    results.push({name,ok:true})
  } catch(error) { results.push({name,ok:false,error:String(error)}); console.error(name,String(error)) }
  finally { if(context) await context.page.close() }
}
async function inspectDialog(page,title,kind,width) {
  const dialog=page.getByRole('dialog',{name:title,exact:true})
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveCSS('opacity','1')
  assert(await dialog.locator('dt').count() >= 4)
  const bounds=await dialog.boundingBox()
  assert(bounds.x>=0 && bounds.x+bounds.width<=width+1)
  assert(bounds.y>=0 && bounds.y+bounds.height<=901)
  const body=dialog.locator('.record-details-body')
  await expect(dialog).toHaveCSS('display','flex')
  const bodyBox=await body.boundingBox()
  const footerBox=await dialog.locator('.record-details-footer').boundingBox()
  assert(bodyBox.y+bodyBox.height<=footerBox.y+1,'Detail body must not run behind the footer')
  assert(footerBox.y+footerBox.height<=bounds.y+bounds.height+1)
  assert(await body.evaluate(el=>el.scrollWidth<=el.clientWidth+1))
  await page.screenshot({path:`${out}/${kind}-details-${width}.png`})
  await dialog.locator('.record-details-footer').getByRole('button',{name:'关闭',exact:true}).click()
  await expect(dialog).toHaveCount(0)
}
try {
  for(const width of [1366,390]) {
    await test(`positions-and-experience-descriptions-${width}`,async()=>{
      const context=await setup(width,'account'); const {page}=context
      const cards=page.locator(width>767 ? '.position-card' : '.mobile-position')
      await expect(cards).toHaveCount(2)
      const heights=await cards.evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().height))
      assert(Math.abs(heights[0]-heights[1])<1)
      await page.screenshot({path:`${out}/positions-${width}.png`})
      await page.getByRole('button',{name:width>767?'查看模拟甲持仓详情':'持仓详情',exact:true}).first().click()
      await inspectDialog(page,'持仓详情','position',width)
      await page.getByRole('tab',{name:/经验沉淀/}).click()
      const rows=page.locator('.experience-row');await expect(rows).toHaveCount(3)
      const rh=await rows.evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().height))
      assert(rh.every(h=>Math.abs(h-rh[0])<1));assert.equal(rh[0],width>767?88:142)
      await rows.first().click();await inspectDialog(page,'经验详情','experience',width)
      return context
    })
    await test(`trades-dialog-search-reset-${width}`,async()=>{
      const context=await setup(width,'account');const {page,requests}=context
      await page.getByRole('tab',{name:'成交明细',exact:true}).click()
      const details=page.locator('button[aria-label="查看模拟甲成交详情"]:visible')
      await expect(details).toHaveCount(1);await details.click();await inspectDialog(page,'成交详情','trade',width)
      assert.equal(await page.locator('details').count(),0)
      const input=page.getByRole('textbox',{name:'名称或代码'})
      await input.fill('模拟甲');await page.getByRole('button',{name:'查询',exact:true}).click()
      await expect.poll(()=>requests.filter(url=>url.pathname.endsWith('/trades')).at(-1)?.searchParams.get('keyword')).toBe('模拟甲')
      await expect(page.locator('button[aria-label="查看模拟乙成交详情"]:visible')).toHaveCount(0)
      await page.getByRole('button',{name:'重置',exact:true}).click();await expect(input).toHaveValue('')
      await expect(page.locator('button[aria-label="查看模拟乙成交详情"]:visible')).toHaveCount(1)
      await page.screenshot({path:`${out}/trades-search-${width}.png`})
      return context
    })
    await test(`sidebar-and-appearance-${width}`,async()=>{
      const context=await setup(width,'navigation'); const {page}=context
      const swatches=page.locator('.sys-rows [data-slot="toggle-group-item"]')
      assert(await swatches.count()>4)
      await swatches.nth(1).click();await expect(swatches.nth(1)).toHaveAttribute('data-state','on')
      await page.getByRole('button',{name:'验收侧栏开关'}).click()
      if(width<768) {
        await expect(page.getByRole('dialog')).toBeVisible()
        await expect(page.getByRole('dialog').getByRole('navigation',{name:'功能导航'}).getByRole('link').first()).toBeVisible()
        await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0)
      } else {
        await expect(page.locator('[data-slot="sidebar"]').first()).toHaveAttribute('data-state','collapsed')
        await page.getByRole('button',{name:'验收侧栏开关'}).click()
        await expect(page.locator('[data-slot="sidebar"]').first()).toHaveAttribute('data-state','expanded')
      }
      await page.screenshot({path:`${out}/sidebar-appearance-${width}.png`})
      return context
    })
  }
} finally {
  await fs.writeFile(`${out}/account-navigation-regression.json`,JSON.stringify(results,null,2))
  await browser.close()
}
console.log(JSON.stringify(results,null,2))
if(results.some(row=>!row.ok))process.exitCode=1

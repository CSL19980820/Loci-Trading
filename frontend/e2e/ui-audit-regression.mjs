import { chromium, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const out='../.local/ui-components-20260921/evidence'
await fs.mkdir(out,{recursive:true})
const browser=await chromium.launch({headless:true})
const results=[]
const errors=new WeakMap()
async function pageFor(width=1440,height=900,view='assistant',wide=true){
 const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1})
 page.setDefaultTimeout(8000)
 errors.set(page,[])
 page.on('pageerror',e=>errors.get(page).push(String(e)))
 page.on('console',m=>{if(m.type()==='error')errors.get(page).push(m.text())})
 await page.route(url=>url.pathname.startsWith('/api/'),route=>route.fulfill({contentType:'application/json',body:JSON.stringify(route.request().url().includes('/market/search')?[{code:'000980',name:'示例标的甲'}]:[])}))
 await page.addInitScript(wide=>{localStorage.setItem('loci.assistant.wide',wide?'1':'0');localStorage.setItem('loci.assistant.historyOpen','0');localStorage.setItem('loci.assistant.taskSidebarOpen','0')},wide)
 await page.goto(`http://127.0.0.1:5174/e2e/fixtures/ui-audit.html?view=${view}`,{waitUntil:'networkidle'})
 await page.waitForTimeout(600)
 return page
}
async function check(name,fn){
 let page
 try {page=await fn();if(page)assert.deepEqual(errors.get(page),[]);results.push({name,ok:true})}
 catch(e){results.push({name,ok:false,error:String(e)});console.error(name,String(e))}
 finally {if(page)await page.close()}
}
async function dimensions(page){return page.evaluate(()=>{
 const box=s=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,sw:e.scrollWidth,cw:e.clientWidth}}
 return {panel:box('.assistant-panel'),stage:box('.assistant-panel__stage'),card:box('.assistant-kline-card'),canvas:box('.kline-chart__canvas'),sender:box('.assistant-sender'),screen:innerWidth}
})}
try {
 for(const [width,height,wide] of [[1800,960,true],[1366,768,true],[1440,900,false],[390,844,true],[320,740,true]])await check(`layout-${width}-${wide?'wide':'float'}`,async()=>{
  const p=await pageFor(width,height,'assistant',wide)
  await expect(p.locator('.assistant-kline-card')).toHaveCount(1)
  await expect(p.locator('.kline-identity')).toContainText('示例标的甲')
  const d=await dimensions(p);assert(d.canvas.w>d.card.w*.80);assert(d.card.sw<=d.card.cw+2,JSON.stringify(d));assert(d.sender.x>=0&&d.sender.x+d.sender.w<=width+1,JSON.stringify(d))
  if(width<=640)assert(d.card.w>width*.75,JSON.stringify(d))
  if(wide&&width>1000)assert(d.card.w>d.stage.w*.85)
  await p.screenshot({path:`${out}/assistant-${width}-${wide?'wide':'float'}.png`})
  await fs.writeFile(`${out}/assistant-${width}-${wide?'wide':'float'}.json`,JSON.stringify(d,null,2))
  await p.locator('[data-slot=toggle-group-item]').filter({hasText:/^KDJ$/}).click()
  await expect(p.locator('.kline-chart__canvas')).toHaveAttribute('aria-label',/KDJ/)
  return p
 })
 await check('tool-history-task-disclosure',async()=>{
  const p=await pageFor()
  const sc=p.locator('.assistant-conversation__viewport');await sc.evaluate(el=>el.scrollTop=0)
  await p.locator('.assistant-receipts__toggle').click();await expect(p.locator('.assistant-receipt-row')).toBeVisible()
  await p.locator('.assistant-receipt-row__head').click();await expect(p.locator('.assistant-receipt-row__body')).toContainText('000980')
  await p.getByTestId('assistant-task-toggle').click()
  await p.getByRole('tab',{name:/产物/}).click();await expect(p.getByTestId('task-sidebar-pane').locator('li')).toHaveCount(1)
  await p.getByRole('tab',{name:/产物/}).press('ArrowRight');await expect(p.getByTestId('task-sidebar-pane')).toContainText('关于你')
  await p.getByTestId('assistant-history-toggle').click();await expect(p.locator('.assistant-session-rail__search')).toBeVisible()
  await p.locator('.assistant-session-rail__search input').fill('长标题');await expect(p.locator('.assistant-session-row')).toHaveCount(1)
  return p
 })
 await check('sender-enter-newline-composition-attachment',async()=>{
  const p=await pageFor();const input=p.getByRole('textbox',{name:'消息内容'})
  await input.fill('第一行');await input.press('Shift+Enter');await input.press('a');assert((await input.inputValue()).includes('\n'))
  await input.fill('中文输入');await input.dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true});assert.equal(await p.evaluate(()=>window.__uiAudit.calls.value.filter(c=>c.event==='send').length),0)
  await input.press('Enter');assert.equal(await p.evaluate(()=>window.__uiAudit.calls.value.filter(c=>c.event==='send').length),1)
  await p.locator('input[type=file]').setInputFiles({name:'fixture.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j6c0AAAAASUVORK5CYII=','base64')})
  await expect(p.getByTestId('assistant-image-previews')).toBeVisible()
  await p.getByRole('button',{name:'移除第 1 张图片'}).click();await expect(p.getByTestId('assistant-image-previews')).toHaveCount(0)
  await input.fill('/');await expect(p.getByTestId('assistant-slash-menu')).toBeVisible();await input.press('Escape');await expect(p.getByTestId('assistant-slash-menu')).toHaveCount(0)
  return p
 })
 await check('terminal-error-stops-loading',async()=>{
  const p=await pageFor();await p.evaluate(()=>window.__uiAudit.setMode('error'))
  await expect(p.locator('.artifact-error')).toContainText('本轮已结束')
  await expect(p.locator('.artifact-loading')).toHaveCount(0)
  await p.screenshot({path:`${out}/assistant-terminal-error.png`})
  return p
 })
 await check('scroll-preserves-reading-and-returns-to-end',async()=>{
  const p=await pageFor();await p.evaluate(()=>{for(let i=0;i<10;i++)window.__uiAudit.append(`历史消息 ${i}\n`+'模拟文字 '.repeat(40))})
  await p.waitForTimeout(400);const sc=p.locator('.assistant-conversation__viewport');await sc.hover();await p.mouse.wheel(0,-10000);await p.waitForTimeout(500)
  const before=await sc.evaluate(el=>el.scrollTop)
  await p.evaluate(()=>window.__uiAudit.append('新增消息，不应把阅读位置拉到底部'))
  await p.waitForTimeout(400);assert(Math.abs(await sc.evaluate(el=>el.scrollTop)-before)<10)
  await p.getByRole('button',{name:'回到最新消息',exact:true}).click();await p.waitForTimeout(800)
  assert(await sc.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)<85)
  return p
 })
 await check('mobile-filter-cancel-validation-and-select',async()=>{
  const p=await pageFor(390,844,'controls');await p.getByRole('button',{name:'日期与分页筛选'}).click()
  await p.getByLabel('开始日期',{exact:true}).fill('2026-09-22');await expect(p.getByRole('button',{name:'查询',exact:true})).toBeDisabled()
  await p.getByRole('button',{name:'取消',exact:true}).click();assert.equal(await p.evaluate(()=>window.__uiAudit.calls.value.filter(c=>c.event==='range').length),0)
  await p.getByRole('button',{name:'日期与分页筛选'}).click();await expect(p.getByLabel('开始日期',{exact:true})).toHaveValue('2026-09-01')
  await p.getByRole('combobox',{name:'每页条数'}).click();await p.getByRole('option',{name:'50 条'}).click()
  await p.screenshot({path:`${out}/mobile-filter.png`})
  await p.getByRole('button',{name:'查询',exact:true}).click();assert.equal(await p.evaluate(()=>window.__uiAudit.calls.value.find(c=>c.event==='range').value.limit),50)
  return p
 })
 await check('theme-toggle-and-shared-input',async()=>{
  const p=await pageFor(1366,900,'controls')
  await p.getByRole('button',{name:'主题与外观'}).click()
  const tiles=p.locator('.appearance-card');assert(await tiles.count()>1)
  await tiles.nth(1).click();await p.waitForTimeout(350);assert((await tiles.first().boundingBox()).height>110);await p.screenshot({path:`${out}/theme-components.png`});await p.keyboard.press('Escape')
  await p.getByRole('button',{name:'清空输入',exact:true}).click();await expect(p.locator('.text-field input')).toHaveValue('')
  return p
 })
}finally{
 await fs.writeFile(`${out}/browser-regression.json`,JSON.stringify(results,null,2));await browser.close()
 console.log(JSON.stringify({passed:results.filter(x=>x.ok).length,total:results.length,results},null,2))
 if(results.some(x=>!x.ok))process.exitCode=1
}

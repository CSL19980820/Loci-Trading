import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const out = '../.local/shadcn-foundation-20260922'
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = [], errors = [], requests = []
const longAnswer = '## 先核对实际执行\n\n这是隔离验收的模拟回答，所有数值仅用于排版。**先核对成本和仓位**，再判断后续操作。\n\n' + '长文本用于检查窄屏换行、历史滚动和流式续写。'.repeat(30) + '\n\n| 项目 | 模拟记录 |\n| --- | --- |\n| 实际成本 | 未提供 |\n| 执行偏差 | 待核对 |'
const history = Array.from({ length: 8 }, (_, index) => ({ id: `turn-${index}`, question: `第 ${index + 1} 个模拟问题：` + '我的实际买入和模拟操作存在差异，请结合我的描述讨论。'.repeat(3), status: 'completed', created: 1000 + index, result: { answer: longAnswer, model: 'fixture-model', as_of: '2026-09-22T15:00:00+08:00' } }))
async function open(width, theme, mode='normal', model='fixture-model') {
 const page = await browser.newPage({ viewport: { width, height: 900 } }); page.setDefaultTimeout(8000)
 page.on('pageerror', error => errors.push(String(error)))
 page.on('console', message => { if (message.type()==='error' && !message.text().includes('503')) errors.push(message.text()) })
 await page.addInitScript(theme => {
  localStorage.setItem('loci-appearance', theme)
  const original = window.fetch.bind(window)
  window.fetch = (input, options) => {
   const url = typeof input === 'string' ? input : input.url
   if (url.includes('/ops/guardian/consultations/') && url.endsWith('/stream')) {
    return Promise.resolve(new Response(new ReadableStream({ start(controller) { window.__consultStream = controller } }), { headers: { 'content-type': 'text/event-stream' } }))
   }
   return original(input, options)
  }
 }, theme)
 const turns = structuredClone(history)
 turns[0].result.thinking='先核对用户提供的实际背景，再查询证据。'
 turns[0].result.tool_receipts=[{call_id:'fixture-tool',name:'get_account',status:'done',summary:'模拟证据已返回',elapsed_ms:25}]
 turns[0].result.phase='done'
 turns.push(mode==='stream' ? {id:'stream',question:'本轮模拟追问',status:'running',created:1010,result:{answer:'**正在逐步分析',model:'fixture-model'}} : {id:'failed',question:'重试这个模拟问题',status:'failed',created:1010,result:{error:'模拟网络中断，请重新提问'}})
 const detail = {id:'fixture-topic',title:'模拟话题 · 实际执行与策略偏差',notes:'隔离验收的持仓背景，不是真实账户',created:1000,updated:1010,turns}
 const second={id:'second-topic',title:'第二个模拟话题',notes:'第二话题背景',created:1000,updated:1001,turns:[{id:'second-turn',question:'第二话题问题',status:'completed',created:1001,result:{answer:'第二话题回答'}}]}
 let deleted=false
 let failures = mode==='retry' ? 1 : 0
 await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
  const url = new URL(route.request().url()), method = route.request().method()
  requests.push({ path: url.pathname, method, body: method==='POST' ? route.request().postDataJSON() : undefined })
  if (url.pathname==='/api/ops/guardian/consultations' && method==='POST') {
   if (failures-- > 0) return route.fulfill({status:503,json:{detail:'模拟暂时无法发送'}})
   const body = route.request().postDataJSON()
   detail.turns.push({id:body.request_id,question:body.message,status:'completed',created:1011,result:{answer:'模拟请求已处理'}})
   return route.fulfill({json:{conversation_id:body.conversation_id,request_id:body.request_id,status:'queued'}})
  }
  if(method==='DELETE'){deleted=true;return route.fulfill({json:{ok:true}})}
  if (url.pathname==='/api/ops/guardian/consultations') return route.fulfill({json:{conversations:deleted?[detail]:[detail,second]}})
  if (url.pathname==='/api/ops/guardian/consultations/second-topic') return route.fulfill({json:second})
  if (url.pathname==='/api/ops/guardian/consultations/fixture-topic') return route.fulfill({json:detail})
  return route.fulfill({json:[]})
 })
 await page.goto(`http://127.0.0.1:5174/e2e/fixtures/guardian-consult.html?model=${model}`, {waitUntil:'networkidle',timeout:30000})
 await expect(page.getByTestId('assistant-turn')).toHaveCount(18)
 return page
}
async function check(name, test) {
 let page
 try { page = await test(); results.push({name,ok:true}) }
 catch(error) {results.push({name,ok:false,error:String(error)});console.error(name,String(error))}
 finally { if(page) await page.close() }
}
try {
 for (const [width,theme] of [[1280,'day'],[1280,'night'],[390,'day'],[390,'night']]) await check(`layout-${width}-${theme}`,async()=>{
  const page = await open(width,theme)
  assert.equal(await page.getByTestId('assistant-turn').count(),18)
  await page.getByRole('button',{name:'重新编辑提问',exact:true}).click()
  await expect(page.getByRole('textbox',{name:'咨询问题'})).toHaveValue('重试这个模拟问题')
  await expect(page.getByRole('textbox',{name:'咨询问题'})).toBeFocused()
  await page.locator('.assistant-conversation__viewport').evaluate(el=>{el.scrollTop=0})
  await page.waitForTimeout(120)
  const dims=await page.locator('.consult-panel').evaluate(el=>({width:el.clientWidth,scrollWidth:el.scrollWidth,answerWidth:Math.max(...Array.from(el.querySelectorAll('.assistant-turn__answer'),row=>row.getBoundingClientRect().width))}))
  assert(dims.scrollWidth<=dims.width+1,JSON.stringify(dims))
  if(width===390) assert(dims.answerWidth>330,JSON.stringify(dims))
  if(width===1280){
   await expect(page.getByRole('complementary',{name:'咨询详情'})).toBeVisible()
   await page.getByRole('tab',{name:'上下文'}).click()
   await expect(page.getByRole('textbox',{name:'实际持仓背景'})).toHaveValue('隔离验收的持仓背景，不是真实账户')
  }
  await page.screenshot({path:`${out}/consult-${width}-${theme}.png`,fullPage:true,animations:'disabled'})
  return page
 })
 await check('real-thinking-tools-and-responsive-sidebars',async()=>{
  const page=await open(1280,'day')
  const viewport=page.locator('.assistant-conversation__viewport')
  await viewport.evaluate(el=>{el.scrollTop=0})
  await page.getByRole('button',{name:/思考完成/}).click()
  await expect(page.getByText('先核对用户提供的实际背景，再查询证据。',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:/调用了 1 个工具/}).click()
  await expect(page.getByTestId('assistant-receipt-row')).toBeVisible()
  await expect(page.getByTestId('assistant-receipt-row')).toContainText('模拟证据已返回')
  await page.screenshot({path:`${out}/consult-thinking-tools.png`,animations:'disabled'})
  await page.getByTestId('session-rail-collapse').click()
  assert.equal(Math.round(await page.getByTestId('assistant-session-rail').evaluate(el=>el.getBoundingClientRect().width)),48)
  await page.getByTestId('session-rail-expand').click()
  await page.locator('#app > div').evaluate(el=>{el.style.width='900px';el.style.marginLeft='224px';el.style.marginRight='0'})
  await expect(page.getByRole('button',{name:'打开咨询详情'})).toBeVisible()
  assert((await page.locator('.consult-main').boundingBox()).width>=480)
  await page.screenshot({path:`${out}/consult-shell-width900.png`,animations:'disabled'})
  await page.getByRole('button',{name:'打开咨询详情'}).click()
  const detail=page.getByRole('dialog',{name:'咨询详情'})
  await detail.getByRole('tab',{name:'上下文'}).click()
  await expect(detail.getByRole('textbox',{name:'实际持仓背景'})).toBeVisible()
  await page.screenshot({path:`${out}/consult-detail-sheet.png`,animations:'disabled'})
  await detail.getByRole('textbox',{name:'实际持仓背景'}).press('Escape')
  await expect(detail).not.toBeVisible()
  await page.locator('#app > div').evaluate(el=>{el.style.width='100%';el.style.margin='auto'})
  await page.setViewportSize({width:390,height:900})
  await page.getByRole('button',{name:'打开咨询历史'}).click()
  await expect(page.getByRole('dialog',{name:'咨询话题'})).toBeVisible()
  await page.screenshot({path:`${out}/consult-mobile-history.png`,animations:'disabled'})
  return page
 })
 await check('failed-send-reuses-request-and-keeps-context',async()=>{
  const page=await open(390,'day','retry')
  const input=page.getByRole('textbox',{name:'咨询问题'})
  await input.fill('新的模拟追问')
  await input.press('Control+Enter')
  await expect(page.getByText('模拟暂时无法发送',{exact:true})).toBeVisible()
  await expect(input).toHaveValue('新的模拟追问')
  await page.getByRole('button',{name:'发送问题',exact:true}).click()
  await expect(input).toHaveValue('')
  const posts=requests.filter(row=>row.method==='POST').slice(-2)
  assert.equal(posts[0].body.request_id,posts[1].body.request_id)
  assert.equal(posts[1].body.real_context,'隔离验收的持仓背景，不是真实账户')
  assert.equal(posts[1].body.conversation_id,'fixture-topic')
  return page
 })
 await check('streaming-preserves-reader-position-and-finishes-markdown',async()=>{
  const page=await open(390,'night','stream')
  const viewport=page.locator('.assistant-conversation__viewport')
  await expect(page.locator('.assistant-turn__answer .assistant-turn__content').last()).toHaveText('**正在逐步分析')
  await expect(page.getByRole('button',{name:'正在研究',exact:true})).toBeDisabled()
  await viewport.hover();await page.mouse.wheel(0,-1700)
  await page.waitForTimeout(180)
  const before=await viewport.evaluate(el=>el.scrollTop)
  await page.evaluate(()=>window.__consultStream.enqueue(new TextEncoder().encode('event: snapshot\ndata: '+JSON.stringify({id:'stream',question:'本轮模拟追问',status:'running',created:1010,result:{answer:'**正在逐步分析'+ '新增片段。'.repeat(150)}})+'\n\n')))
  await expect(page.locator('.assistant-turn__answer .assistant-turn__content').last()).toContainText('新增片段')
  assert(Math.abs(await viewport.evaluate(el=>el.scrollTop)-before)<8)
  await page.getByRole('button',{name:'回到最新消息',exact:true}).click()
  await expect.poll(()=>viewport.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(85)
  await page.evaluate(()=>{window.__consultStream.enqueue(new TextEncoder().encode('event: snapshot\ndata: '+JSON.stringify({id:'stream',question:'本轮模拟追问',status:'completed',created:1010,result:{answer:'**研究完成**\n\n这是最终模拟回复。'}})+'\n\n'));window.__consultStream.close()})
  await expect(page.locator('.assistant-turn__content.is-markdown strong').last()).toHaveText('研究完成')
  await expect(page.getByText('这是最终模拟回复。',{exact:false})).toBeVisible()
  return page
 })
 await check('topic-search-switch-confirm-delete-and-new',async()=>{
  const page=await open(390,'day')
  await page.getByRole('button',{name:'打开咨询历史'}).click()
  const sheet=page.getByRole('dialog',{name:'咨询话题'})
  await expect(sheet).toBeVisible()
  const search=sheet.getByRole('textbox',{name:'搜索咨询话题'})
  await search.fill('第二个')
  await sheet.getByText('第二个模拟话题',{exact:true}).click()
  await expect(sheet).not.toBeVisible()
  await expect(page.getByText('第二话题回答',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'打开咨询详情'}).click()
  await page.getByRole('dialog',{name:'咨询详情'}).getByRole('tab',{name:'上下文'}).click()
  await expect(page.getByRole('textbox',{name:'实际持仓背景'})).toHaveValue('第二话题背景')
  await page.getByRole('textbox',{name:'实际持仓背景'}).press('Escape')
  await page.getByRole('button',{name:'打开咨询历史'}).click()
  await sheet.getByRole('button',{name:'第二个模拟话题的操作'}).click()
  await page.getByRole('menuitem',{name:'删除'}).click()
  const confirm=page.getByRole('alertdialog')
  await expect(confirm).toBeVisible()
  const before=requests.filter(r=>r.method==='DELETE').length
  await confirm.getByRole('button',{name:'取消',exact:true}).click()
  assert.equal(requests.filter(r=>r.method==='DELETE').length,before)
  await sheet.getByRole('button',{name:'第二个模拟话题的操作'}).click()
  await page.getByRole('menuitem',{name:'删除'}).click()
  await page.getByRole('alertdialog').getByRole('button',{name:'删除话题',exact:true}).click()
  await expect.poll(()=>requests.filter(r=>r.method==='DELETE').length).toBe(before+1)
  assert.equal(requests.filter(r=>r.method==='DELETE').at(-1).path,'/api/ops/guardian/consultations/second-topic')
  await expect(page.getByTestId('assistant-turn')).toHaveCount(18)
  await page.getByRole('button',{name:'打开咨询历史'}).click()
  await sheet.getByRole('button',{name:'新话题',exact:true}).click()
  await expect(page.getByText('把你的真实情况告诉交易员')).toBeVisible()
  await page.getByRole('button',{name:'打开咨询详情'}).click()
  await page.getByRole('dialog',{name:'咨询详情'}).getByRole('tab',{name:'上下文'}).click()
  await expect(page.getByRole('textbox',{name:'实际持仓背景'})).toHaveValue('')
  return page
 })
 await check('keyboard-respects-disabled-model-and-composition',async()=>{
  const before=requests.filter(row=>row.method==='POST').length
  const page=await open(390,'day','normal','')
  const input=page.getByRole('textbox',{name:'咨询问题'})
  await input.fill('暂不发送')
  await input.dispatchEvent('keydown',{key:'Enter',ctrlKey:true,isComposing:true})
  await input.press('Control+Enter')
  assert.equal(requests.filter(row=>row.method==='POST').length,before)
  await expect(page.getByRole('button',{name:'发送问题',exact:true})).toBeDisabled()
  return page
 })
}finally{
 await browser.close()
 await fs.writeFile(`${out}/consult-results.json`,JSON.stringify({results,errors,requests},null,2))
}
console.log(JSON.stringify({results,errors},null,2))
if(results.some(row=>!row.ok)||errors.length)process.exitCode=1

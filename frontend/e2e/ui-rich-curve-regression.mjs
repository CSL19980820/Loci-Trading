import { chromium, expect } from '@playwright/test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const out='../.local/ui-components-20260921/evidence'
const browser=await chromium.launch({headless:true})
const result=[]
const points=Array.from({length:24},(_,i)=>({at:`2026-09-${String(1+Math.floor(i/2)).padStart(2,'0')}T${i%2?'14':'10'}:00:00+08:00`,nav:i===12?null:1+i*.002+Math.sin(i)*.02,pnl_cents:i===12?null:Math.round((i*.002+Math.sin(i)*.02)*10000000),drawdown_pct:i===12?null:-Math.abs(Math.sin(i)*2),kind:i===12?'unavailable':'valuation',quality:i===12?'unavailable':'verified',equity_cents:10000000+i*1000,source:'fixture'}))
const curve={code:'',name:'模拟账户',scope:'account',as_of:'2026-09-21T15:00:00+08:00',start:'2026-09-01',end:'2026-09-21',opened_at:null,method:'account_equity_v1',points,protection:[{code:'000980',name:'模拟标的',quantity:1000,available_quantity:800,locked_quantity:200,protected_quantity:800,unprotected_quantity:200,stale:false,invalid_plans:0,stops:[{price:2.7,quantity:800,valid_until:'2026-09-23T15:00:00+08:00',reached:false}]}],excluded_points:1,coverage:{sampled:true,missing_snapshots:1},summary:{current_drawdown_pct:-1,max_drawdown_pct:-2,last_valid_drawdown_pct:-1,last_valid_at:points.at(-1).at,last_valid_pnl_cents:300000,peak_at:points[10].at,max_drawdown_peak_at:points[10].at,max_drawdown_at:points[15].at,valid_points:23,latest_nav:1.03,latest_pnl_cents:300000,recovery_pct:1}}
async function page(view,width=1366){const p=await browser.newPage({viewport:{width,height:900}});p.setDefaultTimeout(7000);const errors=[];p.on('pageerror',e=>errors.push(String(e)));await p.route(u=>u.pathname.startsWith('/api/'),r=>r.fulfill({contentType:'application/json',body:JSON.stringify(r.request().url().includes('holding-curve')?curve:[])}));await p.addInitScript(()=>{localStorage.setItem('loci.assistant.wide','1');localStorage.setItem('loci.assistant.historyOpen','0');localStorage.setItem('loci.assistant.taskSidebarOpen','0')});await p.goto(`http://127.0.0.1:5174/e2e/fixtures/ui-audit.html?view=${view}`,{waitUntil:'networkidle'});return {p,errors}}
async function run(name,fn){try{await fn();result.push({name,ok:true})}catch(e){result.push({name,ok:false,error:String(e)})}}
try{
 await run('all-rich-artifact-kinds',async()=>{
  const {p,errors}=await page('assistant')
  const artifacts=[
   {kind:'table',title:'模拟价格表',data:{columns:[{key:'name',label:'名称'},{key:'price',label:'价格 / 元'}],rows:[{name:'模拟甲',price:2.98},{name:'模拟乙',price:12.34}]}},
   {kind:'echarts',title:'模拟统计图',data:{option:{xAxis:{type:'category',data:['甲','乙','丙']},yAxis:{type:'value'},series:{type:'bar',data:[3,5,2]}}}},
   {kind:'equity_curve',title:'模拟净值含缺测',data:{dates:['09-01','09-02','09-03','09-04'],values:[1,1.02,null,1.01]}},
   {kind:'candidate_verdict',title:'模拟候选',data:{candidates:[{code:'000980',name:'模拟甲',decision:'观察',score:70,reason:'这是回归测试数据，不是投资建议。'}]}},
   {kind:'source_strip',title:'模拟来源',data:{sources:[{label:'测试夹具',detail:'隔离模拟数据，不访问生产账本',date:'2026-09-21'}]}},
   {kind:'code',title:'模拟代码',data:{language:'python',text:'print("fixture only")'}},
   {kind:'unknown_fixture',title:'兼容未知类型',data:{value:'fixture'}}
  ].map((a,i)=>({...a,id:`fixture-${i}`,status:'ready'}))
  await p.evaluate(a=>window.__uiAudit.setMessages([{id:'rich',role:'assistant',status:'done',content:'所有卡片均为模拟数据。',artifacts:a}]),artifacts)
  await expect(p.getByTestId('assistant-artifact')).toHaveCount(7)
  await expect(p.locator('.assistant-echarts-card canvas')).toHaveCount(1)
  await expect(p.locator('.assistant-equity-card canvas')).toHaveCount(1)
  await expect(p.locator('.assistant-artifact-host .artifact-error')).toHaveCount(0)
  for(const [i,card] of (await p.getByTestId('assistant-artifact').all()).entries()){await card.scrollIntoViewIfNeeded();await card.screenshot({path:`${out}/rich-artifact-${i}.png`})}
  assert.deepEqual(errors,[]);await p.close()
 })
 await run('active-loading-timeout-and-image-preview',async()=>{
  const {p,errors}=await page('assistant')
  await p.clock.install()
  await p.evaluate(()=>window.__uiAudit.setMessages([{id:'timeout',role:'assistant',status:'streaming',content:'模拟读取中',artifacts:[{id:'pending',kind:'kline',title:'等待测试',status:'loading',data:{}}]}]))
  await expect(p.locator('.artifact-loading')).toBeVisible();await p.clock.fastForward(61000)
  await expect(p.locator('.artifact-error')).toContainText('图表数据尚未返回')
  await p.clock.resume()
  const image='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="120"><text y="30">fixture</text></svg>')
  await p.evaluate(image=>window.__uiAudit.setMessages([{id:'image',role:'user',status:'done',content:'模拟附图',images:[image]}]),image)
  await p.getByRole('button',{name:'放大附图 1'}).click();await expect(p.getByRole('dialog',{name:'查看附图'})).toBeVisible();await p.keyboard.press('Escape')
  assert.deepEqual(errors,[]);await p.close()
 })
 for(const width of [1366,390])await run(`curve-${width}-modes-warning-and-protection`,async()=>{
  const {p,errors}=await page('curve',width)
  await expect(p.locator('.holding-curve canvas')).toHaveCount(1)
  await p.screenshot({path:`${out}/holding-curve-${width}.png`})
  await p.locator('.curve-modes [data-slot=toggle-group-item]').filter({hasText:'盈亏金额'}).click()
  await p.getByRole('button',{name:'查看最高值时点'}).click()
  await p.getByRole('button',{name:'曲线操作'}).click();await p.getByRole('menuitem',{name:/预警阈值/}).click()
  await p.getByLabel('预警阈值（%）',{exact:true}).fill('0');await expect(p.getByRole('button',{name:'应用',exact:true})).toBeDisabled()
  await p.getByLabel('预警阈值（%）',{exact:true}).fill('3.5');await p.getByRole('button',{name:'应用',exact:true}).click()
  assert.equal(await p.evaluate(()=>localStorage.getItem('loci.holding-curve.warning')),'3.5')
  await p.getByRole('button',{name:'曲线操作'}).click();await p.getByRole('menuitem',{name:'止损保护',exact:true}).click()
  await expect(p.getByRole('dialog',{name:'止损保护'})).toContainText('模拟标的')
  await p.screenshot({path:`${out}/holding-protection-${width}.png`})
  assert.deepEqual(errors,[]);await p.close()
 })
}finally{await fs.writeFile(`${out}/rich-curve-regression.json`,JSON.stringify(result,null,2));await browser.close();console.log(JSON.stringify(result,null,2));if(result.some(x=>!x.ok))process.exitCode=1}

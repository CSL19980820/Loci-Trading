/** Compiled UI checks with isolated read APIs; no production credentials or writes. */
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
import { chromium, expect } from '@playwright/test'
import { routeFixture } from './fixtures/shadcn-route-api.mjs'
const base = process.env.SLIM_BASE || 'http://127.0.0.1:5189'
const output = process.env.SLIM_OUT || path.resolve('../.local/slimming/ui')
await fs.mkdir(output, { recursive: true })
const strategy = { slug: 'slim-fixture', name: '瘦身验收战法', description: '隔离浏览器夹具', params: {}, required_fields: [], min_bars: 20, entry_timing: 'next_open' }
const providers = [
  { id: 'tdx', label: '通达信', lanes: ['hist_daily','spot_batch','minute_bars'] },
  { id: 'sina', label: '新浪直连', lanes: ['hist_daily','spot_batch','minute_bars','adjust_factor','capital_flow'] },
  { id: 'exchange_list', label: '交易所列表', lanes: ['instruments'] },
].map(p => ({...p, enabled:true, disabled_lanes:[], kind:'adapter', description:'验收保留源'}))
const activity = { items:[{ key:'fixture-cycle',agentId:'guardian',agentName:'天才交易员',to:'/agents/guardian',at:'2026-09-29T15:00:00+08:00',phaseLabel:'盘后复盘',statusLabel:'完成',summary:'聚合接口验收记录',failed:false }], partial_errors:[] }
const browser = await chromium.launch({headless:true})
const results = []
try {
 for (const [name,route,width] of [
   ['home-desktop','/',1440],['home-mobile','/',390],
   ['strategy-desktop','/quant',1440],['strategy-mobile','/quant',390],
   ['sources-desktop','/ops?tab=sources',1440],['sources-mobile','/ops?tab=sources',390],
   ['jobs','/ops?tab=jobs',1440],['alerts','/ops?tab=alerts',390],
   ['agents','/agents',1440],['pool','/pool',390],
 ]) {
  const context = await browser.newContext({viewport:{width,height:960},serviceWorkers:'block',reducedMotion:'reduce'})
  const page = await context.newPage()
  const requests=[],gaps=[],errors=[],writes=[]
  let releaseSkills
  const skillsGate = new Promise(resolve => {releaseSkills=resolve})
  let skillsReleased = !name.startsWith('strategy')
  page.on('pageerror', error=>errors.push(String(error)))
  await context.route('**/*',async handler=>{
   const request=handler.request(), url=new URL(request.url())
   if(url.origin!==new URL(base).origin) return handler.abort()
   if(!url.pathname.startsWith('/api/')) {
    // Public-server document auth stays intact; only this browser uses a fixture.
    if(!base.includes('127.0.0.1') && request.isNavigationRequest() && url.pathname!=='/login') {
      const document=await context.request.get(`${base}/login`)
      return handler.fulfill({response:document})
    }
    return handler.continue()
   }
   requests.push(url.pathname)
   if(!['GET','HEAD','OPTIONS'].includes(request.method())) {
    writes.push(request.method()+' '+url.pathname)
    return handler.fulfill({status:405,contentType:'application/json',body:'{}'})
   }
   let fixture
   if(url.pathname==='/api/strategies') fixture={body:[strategy]}
   else if(url.pathname==='/api/screen/history/batch') fixture={body:{strategies:[strategy.slug],histories:[]}}
   else if(url.pathname==='/api/ops/stock-agents/activity') fixture={body:activity}
   else if(url.pathname==='/api/ops/lanes') fixture={body:{providers,lanes:[],policies:[],summary:{ok:3,degraded:0,down:0}}}
   else {
    if(url.pathname==='/api/skills' && !skillsReleased) await skillsGate
    fixture=routeFixture(url,'slimming')
   }
   if(!fixture) gaps.push(url.pathname)
   await handler.fulfill({status:fixture?.status || (fixture?200:404),contentType:'application/json',body:JSON.stringify(fixture?.body ?? {})})
  })
  try {
   await page.goto(base+route,{waitUntil:'domcontentloaded',timeout:45000})
   if(name.startsWith('strategy')) {
    await expect(page.getByText('瘦身验收战法',{exact:true}).first()).toBeVisible({timeout:15000})
    assert.equal(skillsReleased,false,'strategy must render before unrelated skills request resolves')
    skillsReleased=true; releaseSkills()
   }
   await page.waitForLoadState('networkidle',{timeout:25000})
   if(name.startsWith('home')) {
    if(width<600) await page.getByRole('tab',{name:'智能体研判',exact:true}).click()
    await expect(page.getByText('聚合接口验收记录',{exact:true})).toBeVisible()
    assert.equal(requests.filter(p=>p==='/api/ops/stock-agents/activity').length,1)
    assert.equal(requests.filter(p=>/stock-agents\/[^/]+\/history/.test(p)).length,0)
   }
   if(name.startsWith('sources')) {
    for(const text of ['通达信','新浪直连','交易所列表']) await expect(page.getByText(text,{exact:true}).first()).toBeVisible()
   }
   assert.deepEqual(errors,[]); assert.deepEqual(gaps,[]); assert.deepEqual(writes,[])
   assert.equal(requests.some(p=>/akshare|paper-cabins|community|hithink/.test(p)),false)
   const bounds=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,text:document.body.innerText.length}))
   assert.ok(bounds.width<=bounds.viewport+3,JSON.stringify(bounds))
   assert.ok(bounds.text>40,'page should not be blank')
   await page.screenshot({path:path.join(output,name+'.png'),fullPage:true})
   results.push({name,ok:true,bounds,apiRequests:requests.length})
  } catch(error) {
   results.push({name,ok:false,error:String(error),gaps,errors,writes,requests})
   await page.screenshot({path:path.join(output,name+'-failed.png'),fullPage:true})
  } finally {releaseSkills();await context.close()}
  console.log(JSON.stringify(results.at(-1)))
 }
} finally {await browser.close()}
await fs.writeFile(path.join(output,'results.json'),JSON.stringify(results,null,2))
assert.ok(results.every(r=>r.ok),'One or more compiled UI regressions failed')

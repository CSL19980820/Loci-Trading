import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
const out = '../.local/ui-components-20260921/evidence'
await fs.mkdir(out,{recursive:true})
const browser=await chromium.launch({headless:true})
try {
 const page=await browser.newPage({viewport:{width:1800,height:960},deviceScaleFactor:1})
 const errors=[]
 page.on('pageerror',e=>errors.push(String(e)))
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 await page.route(url => url.pathname.startsWith('/api/'),route=>route.fulfill({contentType:'application/json',body:JSON.stringify(route.request().url().includes('/market/search')?[{code:'000980',name:'示例标的甲'}]:[])}))
 await page.addInitScript(()=>{localStorage.setItem('loci.assistant.wide','1');localStorage.setItem('loci.assistant.historyOpen','1');localStorage.setItem('loci.assistant.taskSidebarOpen','0')})
 await page.goto('http://127.0.0.1:5174/e2e/fixtures/ui-audit.html',{waitUntil:'networkidle'})
 await page.waitForTimeout(1800)
 await page.screenshot({path:`${out}/assistant-desktop-first.png`,fullPage:true})
 const boxes = await page.evaluate(()=>Object.fromEntries(['.assistant-panel','.assistant-panel__stage','.assistant-conversation','.assistant-kline-card','.kline-chart__canvas','.assistant-sender','.assistant-turn__flow'].map(s=>{const e=document.querySelector(s),r=e?.getBoundingClientRect();return [s,r?{x:r.x,y:r.y,width:r.width,height:r.height,scrollWidth:e.scrollWidth,scrollHeight:e.scrollHeight}:null]})))
 console.log(JSON.stringify({errors,boxes,text:(await page.locator('body').innerText()).slice(0,1600)},null,2))
 await fs.writeFile(`${out}/first-render.json`,JSON.stringify({errors,boxes},null,2))
}finally{await browser.close()}

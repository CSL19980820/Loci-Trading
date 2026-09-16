import { expect, test } from '@playwright/test'

// 仅供界面验收的固定样本，不写入后端数据库，也不请求模型或真实行情。
const config = {
  name:'龙头选手', kind:'leader', description:'1进2 · 2进3 · 接力 · 龙空龙', provider:'验证模型', model:'test-model',
  prompt:'这是界面测试用提示词，不执行交易。', enabled:false, initial_capital_cents:20000000, strategies:[],
  daily_selection_limit:3, watch_limit:3, position_limit:3, temporary_position_limit:5, max_position_pct:35, timeout_seconds:240,
  schedule:{ timezone:'Asia/Shanghai', review_time:'20:00', premarket_time:'08:50', auction_time:'09:25', intraday_minutes:5, intraday_enabled:true },
  retention:{ days:30,max_entries:2000,cleanup_hours:24 },
}
const state = { initial_capital_cents:20000000, cash_cents:20000000, equity_cents:20000000, market_value_cents:0,
  total_pnl_cents:0, realized_pnl_cents:0, fees_cents:0, positions:[], watchlist:[], stale_codes:[],
  valuation_at:'2026-09-16T10:00:00+08:00', selected_today:{ date:'2026-09-16',codes:[] }, position_count:0 }
const profile = { id:'agent-ui-test', config, state, revision:1, state_version:1, archived:0, running:false,
  created_at:'2026-09-15T20:00:00+08:00', updated_at:'2026-09-16T10:00:00+08:00',
  total_runs:1,total_actions:0,total_trades:0,cleaned_runs:0,history_kept:1,
  latest_at:'2026-09-16T09:25:00+08:00',latest_phase:'auction',latest_status:'success',
  latest_summary:'竞价条件尚未满足，保留现金，等待承接和板块持续性得到确认。',latest_actions:[],
  schedules:[{ phase:'premarket',label:'盘前计划',time:'08:50',enabled:true },
    { phase:'auction',label:'竞价研判',time:'09:25',enabled:true },
    { phase:'review',label:'晚间复盘',time:'20:00',enabled:true },
    { phase:'intraday',label:'盘中管理',time:'每5分钟',enabled:true },
    { phase:'closeout',label:'尾盘收敛',time:'14:50 / 14:55',enabled:true }],
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path.includes('/auth/session')) return route.fulfill({ json:{ authenticated:true,username:'ui-verification',role:'user',must_change_password:false } })
    if (path.endsWith('/stock-agents/guardian/overview')) return route.fulfill({ json:{ config:{ enabled:false,provider:'',model:'' },state,runs:[],stats:{ total_runs:0,total_trades:0,total_reports:0,full_entries:0,compacted_entries:0,retention:config.retention },position_policy:{ close_max:4,temporary_max:8 } } })
    if (path.endsWith('/stock-agents/options')) return route.fulfill({ json:{ templates:{ leader:config,custom:{ ...config,name:'我的股票智能体',kind:'custom' } },strategies:[{ slug:'test-method',name:'验证工坊战法',description:'仅用于测试' }],timezone:'Asia/Shanghai' } })
    if (path.endsWith('/stock-agents')) return route.fulfill({ json:{ items:[profile],as_of:'2026-09-16T10:00:00+08:00' } })
    if (path.endsWith('/agent-ui-test/equity')) return route.fulfill({ json:{ items:[{ day:'2026-09-15',at:profile.created_at,equity_cents:20000000,funded_cents:20000000,pnl_cents:0,stale:0 },{ day:'2026-09-16',at:profile.updated_at,equity_cents:20000000,funded_cents:20000000,pnl_cents:0,stale:0 }],total:2,truncated:false } })
    if (path.endsWith('/agent-ui-test/history')) return route.fulfill({ json:{ items:url.searchParams.get('kind') === 'runs' ? [{ id:'run-ui-test',phase:'auction',started_at:profile.latest_at,status:'success',summary:profile.latest_summary,actions:[] }] : [],total:url.searchParams.get('kind') === 'runs' ? 1 : 0,limit:20,offset:0 } })
    if (path.endsWith('/agent-ui-test')) return route.fulfill({ json:profile })
    if (path.endsWith('/providers')) return route.fulfill({ json:[{ id:'test-provider',name:'验证模型',is_active:true,models:['test-model'] }] })
    if (path.includes('/health')) return route.fulfill({ json:{ status:'ok' } })
    return route.fulfill({ json:{} })
  })
})

for (const width of [1440,390]) {
  test(`智能体中心与详情布局 ${width}px`, async ({ page },testInfo) => {
    await page.setViewportSize({ width,height:1000 })
    const pageErrors:string[] = []
    page.on('pageerror', error => pageErrors.push(error.message))
    await page.goto('/agents')
    await expect(page.getByRole('heading',{ name:'让每个智能体，各司其职。' })).toBeVisible()
    await expect(page.getByRole('heading',{ name:'自主交易员',exact:true })).toBeVisible()
    await expect(page.getByText(profile.latest_summary,{ exact:true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1)).toBe(true)
    await page.screenshot({ path:testInfo.outputPath(`agents-${width}.png`),fullPage:true })
    await page.goto('/agents/agent-ui-test')
    await expect(page.getByRole('heading',{ name:'龙头选手',exact:true })).toBeVisible()
    await expect(page.getByRole('heading',{ name:'累计盈利曲线' })).toBeVisible()
    await expect(page.getByText('20:00',{ exact:true })).toBeVisible()
    await expect(page.getByText('09:25',{ exact:true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1)).toBe(true)
    await page.screenshot({ path:testInfo.outputPath(`agent-detail-${width}.png`),fullPage:true })
    await page.getByRole('button',{ name:'工作日记',exact:true }).click()
    await expect(page.locator('.diary-list').getByText(profile.latest_summary,{ exact:true })).toBeVisible()
    await page.getByRole('button',{ name:'设置',exact:true }).click()
    await expect(page.getByRole('dialog',{ name:'智能体设置',exact:true })).toBeVisible()
    await page.getByRole('tab',{ name:'账户与日程' }).click()
    await expect(page.getByText('每日累计入选上限',{ exact:true })).toBeVisible()
    await page.screenshot({ path:testInfo.outputPath(`agent-settings-${width}.png`),fullPage:true })
    expect(pageErrors).toEqual([])
  })
}

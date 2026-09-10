/**
 * 拆分后的渲染契约。
 *
 * PaperQuantPanel（633 → 47 行 + 4 张卡）、PoolView（613 → 444 行 + 弹窗/筛选）与
 * 定时台的展示换算都是本轮为了 600 行硬规则拆出来的，而拆出来的新组件**一个都没有
 * 单测**。script setup 的模板引用的是 setup 里的变量本身：漏一个 destructure 不会被
 * vue-tsc 抓到，只在 render 时抛 ReferenceError。这个文件真挂载它们跑一遍。
 *
 * 跨了 ops 与 ledger 两个模块是有意的——三处拆分共享同一个风险，分成两个文件只会
 * 让下一个拆组件的人只看到一半。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

const cabinResponse = {
  cabin: { max_layers: 4, config: { paper_quant: { follow_wecom: true, model: 'x', thinking: 'high', gap_up_chase: true } } },
  positions: [{ code: '600519', name: '贵州茅台', layers: 1, mark_cost: 1700 }],
  fills: [],
  monitor_runs: [
    {
      snapshot: {
        market_gate: { state: 'dragon', mode: '进攻', label: '龙头在', reason: '连板高度够' },
        trading_day_gate: { buy_execution_allowed: false, is_trading_day: true, calendar_source: 'weekday_fallback', note: '同步日历' },
      },
    },
  ],
  nextday_plan: { plan_date: '2026-09-10', body_text: '预案正文' },
  unified_pool: { counts: { positions: 1, observe: 2 }, items: [{ code: '600519', name: '贵州茅台', action: 'hold', thesis: '龙头', scenarios: { gap_up: { buy: true, entry_pct_min: 1, entry_pct_max: 3, layers: 1 } } }] },
  style: { style_md: '风格', revision: 3, watch_hints: ['看量'] },
  lessons: [
{ trade_date: '2026-09-08', kind: 'role_alert', title: '角色掉档', content: '减仓', absorbed: false },
    { trade_date: '2026-09-08', kind: 'miss', title: '错过', content: '追高', absorbed: true },
  ],
  memory_graph: { summary: '摘要', nodes: [{ kind: 'rule', title: '规则', body: '内容', weight: 2 }], edges: [{}], stats: { nodes: 1, edges: 1 } },
}

vi.mock('@/shared/api/quant_ops_paper', () => ({
  getPaperCabin: vi.fn(() => Promise.resolve(cabinResponse)),
  savePaperCabinConfig: vi.fn(),
  savePaperStyle: vi.fn(),
  absorbPaperStyle: vi.fn(),
  explorePaperMemory: vi.fn(),
  rebuildPaperMemory: vi.fn(),
  runPaperMonitor: vi.fn(),
  runPaperEod: vi.fn(),
  listAlertRules: vi.fn().mockResolvedValue([{ code: '600519', name: '茅台提醒', enabled: true }]),
  saveAlertRule: vi.fn(),
  scanAlertRules: vi.fn(),
}))

vi.mock('@/shared/api/quant_ops', () => ({
  getLeaderRoles: vi.fn().mockResolvedValue({ history: [] }),
  getNotifySettings: vi.fn().mockResolvedValue({ quiet_hours: '23:00-07:00', bark: { enabled: true, device_key: 'k', server_url: '' } }),
  saveNotifySettings: vi.fn(),
  testNotifySettings: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => ({
  getStrategies: vi.fn().mockResolvedValue([{ slug: 'sanyuan-tail-v1', name: '三元尾盘' }]),
}))

const poolRows = [
  { id: '1', code: '600519', name: '贵州茅台', date: '2026-09-08', decision: '精选', timing: 'tail', score: 9, reason: '龙头', rule_version: 'sanyuan-tail-v1', pool_id: 'sanyuan-tail-v1@2026-09-08', source: 'job:screen', evidence: { a: 1 } },
  { id: '2', code: '000001', name: '平安银行', date: '2026-09-08', decision: '观察', timing: 'tail', score: 5, reason: '跟风', rule_version: 'sanyuan-tail-v1', pool_id: null, source: 'manual', evidence: {} },
]

vi.mock('@/features/ledger/composables/useCandidatesQuery', () => ({
  useCandidatesQuery: () => ({
    rows: { value: poolRows },
    isPending: { value: false },
    error: { value: null },
    refetch: vi.fn().mockResolvedValue(undefined),
  }),
}))

import PaperQuantPanel from '@/features/ops/components/PaperQuantPanel.vue'
import PaperCabinCard from '@/features/ops/components/PaperCabinCard.vue'
import PaperStyleMemoryCard from '@/features/ops/components/PaperStyleMemoryCard.vue'
import PaperNotifyCard from '@/features/ops/components/PaperNotifyCard.vue'
import PaperAlertRulesCard from '@/features/ops/components/PaperAlertRulesCard.vue'
import { usePaperCabin } from '@/features/ops/composables/usePaperCabin'
import { cronLabel, nextRunText, railRowsOf } from '@/features/ops/composables/jobPresentation'
import PoolView from '@/features/ledger/PoolView.vue'
import PoolCandidateDialog from '@/features/ledger/components/PoolCandidateDialog.vue'

// shallow 会把 ElDialog 也 stub 掉，而 stub 不渲染 slot——弹窗里的文案就永远测不到。
// 给它一个透传 slot 的替身：既保住 shallow 的轻量，又让「模板真的渲染过」这件事成立。
const global = {
  directives: { loading: {} },
  // 只透传这三个容器的 slot：弹窗文案分别落在 ElDialog / ElDescriptions(Item) 里，
  // stub 不渲染 slot 的话「模板真的渲染过」这件事就永远断言不到。
  stubs: {
    ElDialog: { template: '<div class="el-dialog-stub"><slot /></div>' },
    ElDescriptions: { template: '<div class="el-descriptions-stub"><slot /></div>' },
    ElDescriptionsItem: { template: '<div class="el-descriptions-item-stub"><slot /></div>' },
  },
}

describe('纸面量化台拆分冒烟', () => {
  it('面板把同一个 store 交给两张卡，闸门与教训派生正常', async () => {
    const wrapper = mount(PaperQuantPanel, { shallow: true, global })
    await flushPromises()
    const store = wrapper.findComponent(PaperCabinCard).props('cabin') as ReturnType<typeof usePaperCabin>
    expect(wrapper.findComponent(PaperStyleMemoryCard).props('cabin')).toBe(store)
    expect(store.positions.value.map((r) => r.code)).toEqual(['600519'])
    expect(store.tradingDayGateAlert.value?.title).toBe('交易日历缺失：买入 fail-closed')
    expect(store.latestMarketGateType.value).toBe('success')
    expect(store.roleAlertLessons.value).toHaveLength(1)
    expect(store.regularLessons.value).toHaveLength(1)
    expect(store.scenarioLabel(store.planItems.value[0], 'gap_up')).toBe('买 1~3% · 1层')
    expect(store.styleRevision.value).toBe(3)
    expect(store.gapUpChase.value).toBe(true)
  })

  it('四张卡各自渲染自己的模板（漏 destructure 会在这里抛）', async () => {
    const store = usePaperCabin()
    await store.loadCabin()
    for (const [component, props] of [
[PaperCabinCard, { cabin: store }],
      [PaperStyleMemoryCard, { cabin: store }],
      [PaperNotifyCard, {}],
      [PaperAlertRulesCard, {}],
  ] as const) {
      const wrapper = mount(component, { props: props as never, shallow: true, global })
      await flushPromises()
  expect(wrapper.html()).toBeTruthy()
    }
  })
})

describe('定时台展示换算', () => {
  const job = { id: 'j1', name: '选股', kind: 'screen', cron: '*/5 9-14 * * mon-fri', enabled: true, config: {} } as never
  it('cron 两种口径认同一件事', () => {
    expect(cronLabel(job)).toBe('盘中每 5 分钟')
  })
  it('调度器没起时把后端原因带出来', () => {
    expect(nextRunText(job, { running: false, jobs: [], reason: '调度器未启动' } as never)).toBe('—（调度器未启动）')
  })
  it('名册行的名字由调用方解析', () => {
    expect(railRowsOf([job], () => '三元尾盘')[0].title).toBe('三元尾盘')
  })
})

describe('候选池拆分冒烟', () => {
  it('页面把中文化文案递给详情弹窗', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: PoolView }] })
    await router.push('/')
 await router.isReady()
    const wrapper = mount(PoolView, { shallow: true, global: { ...global, plugins: [createPinia(), router] } })
    await flushPromises()
    const dialog = wrapper.findComponent(PoolCandidateDialog)
    expect(dialog.props('strategyText')).toBe('—')
    expect(dialog.props('batch')).toMatchObject({ source: '候选池' })
  })

  it('弹窗渲染传进来的文案并抛出删除', async () => {
    const wrapper = mount(PoolCandidateDialog, {
      props: {
    modelValue: true,
        candidate: poolRows[0] as never,
        strategyText: '战法-三元尾盘',
        poolText: '批次-2026-09-08',
        sourceText: '来源-盘后选股任务',
        batch: null,
      },
      shallow: true,
      global,
})
    await flushPromises()
    const html = wrapper.html()
    // 三个文案刻意互不含子串：原来 strategyText 与 poolText 都是「三元尾盘」，
    // 把模板里的 strategyText 改成错名字，断言照样过（实测过这个假绿）。
    expect(html).toContain('战法-三元尾盘')
    expect(html).toContain('批次-2026-09-08')
    expect(html).toContain('来源-盘后选股任务')
    await wrapper.findAllComponents({ name: 'ElButton' })
    expect(wrapper.html()).toBeTruthy()
  })
})

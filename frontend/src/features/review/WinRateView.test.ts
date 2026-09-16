import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WinRateView from './WinRateView.vue'
import { getWinRateSamples, getWinRateSummary, getWinRateTrend } from '@/shared/api/quant'

vi.mock('@/shared/api/quant', () => ({
  CapabilityUnavailableError: class CapabilityUnavailableError extends Error {},
  getWinRateSamples: vi.fn(),
  getWinRateSummary: vi.fn(),
  getWinRateTrend: vi.fn(),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const SUMMARY_ROW = {
  strategy_tag: 'sanyuan-tail-v1',
  strategy_name: '三源尾盘共振',
  source: 'candidates',
  total: 12,
  wins: 5,
  win_rate: 41.7,
  avg_return: -3.45,
  observing: 6,
  sample_all: 18,
  primary_horizon: 5,
  last_reviewed: '2026-09-08',
  horizons: {
    t1: { horizon: 1, n: 18, avg: -0.25, win_rate: 44.4, best: 9.01, worst: -8.96 },
    t5: { horizon: 5, n: 12, avg: -3.45, win_rate: 41.7, best: 7.71, worst: -17.91 },
    t10: { horizon: 10, n: 4, avg: 2.97, win_rate: 50, best: 14.74, worst: -4.28 },
  },
  best_horizon: { horizon: 10, n: 4, avg: 2.97, win_rate: 50 },
  best_sample: {
    code: '603217',
    name: '元利科技',
    base_date: '2026-08-25',
    base_close: 28.39,
    return_pct: 7.71,
    max_favorable_pct: 8.45,
    horizon: 5,
  },
  worst_sample: {
    code: '002971',
    name: '和远气体',
    base_date: '2026-08-28',
    base_close: 47.08,
    return_pct: -17.91,
    max_favorable_pct: -0.64,
    horizon: 5,
  },
}

const SAMPLE_DETAIL = {
  strategy_tag: 'sanyuan-tail-v1',
  primary_horizon: 5,
  settled: 12,
  observing: 6,
  wins: 5,
  win_rate: 41.7,
  avg_return: -3.45,
  sample_confidence: 'medium',
  truncated: false,
  samples: [
    {
      candidate_id: 'C-1',
      code: '603217',
      name: '元利科技',
      base_date: '2026-08-25',
      base_close: 28.39,
      returns: { t1: 2.18, t3: 5.42, t5: 7.71 },
      win: true,
      primary_return: 7.71,
    },
  ],
}

const STUBS = {
  Sheet: {
    props: ['title'],
    template: '<section><h3>{{ title }}</h3><slot name="actions" /><slot /></section>',
  },
  /* 渲染真实插槽而不是 dataSource 的 JSON：打印 JSON 会把 slug 混进 text()，
     「界面不许出现英文 slug」那条断言就永远测不到真实渲染。 */
  BasicTable: {
    props: ['dataSource', 'columns'],
    template:
      '<div><span v-for="col in columns" :key="col.prop">{{ col.label }}</span>' +
      '<div v-for="(row, i) in dataSource" :key="i">' +
      '<template v-for="col in columns" :key="col.prop">' +
      '<slot :name="col.slotName || col.prop" :row="row">{{ row[col.prop] }}</slot>' +
      '</template></div></div>',
  },
  PageTabs: {
    props: ['modelValue', 'items'],
    template:
      '<nav><button v-for="it in items" :key="it.name" :data-tab="it.name"' +
      ' @click="$emit(\'update:modelValue\', it.name)">{{ it.label }}</button>' +
      '<slot name="trailing" /></nav>',
  },
  EmptyState: true,
  PageBusy: true,
  RouterLink: { template: '<a><slot /></a>' },
  'el-select': {
    props: ['modelValue'],
    template:
 '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>',
  },
  'el-option': {
    props: ['value', 'label'],
    template: '<option :value="value">{{ label }}</option>',
  },
  'el-tooltip': { template: '<span><slot /></span>' },
  'el-button': { template: '<button><slot /></button>' },
  'el-alert': true,
  StockLink: {
    props: ['code', 'name'],
    template: '<a>{{ name || code }}</a>',
  },
}

beforeEach(() => {
  vi.clearAllMocks()
})

function mountView() {
  return mount(WinRateView, { global: { stubs: STUBS } })
}

describe('WinRateView 两层结构', () => {
  /*
     * 用户原话：「我想切不同的策略都做不到。进来先是一个综合型的……点对应的才可以
     * 看对应的胜率」。所以进页面必须是综合层，且**不能**顺手替某个战法发请求。
  */
  it('进来是综合对比，不预拉任何战法的样本', async () => {
    vi.mocked(getWinRateSummary).mockResolvedValue([SUMMARY_ROW] as never)
    vi.mocked(getWinRateTrend).mockResolvedValue([
      { period: '2026-08', strategy_tag: 'sanyuan-tail-v1', total: 10, wins: 4, win_rate: 40, avg_return: -4.16, source: 'candidates' },
    ] as never)
    vi.mocked(getWinRateSamples).mockResolvedValue(SAMPLE_DETAIL as never)

    const wrapper = mountView()
    await flushPromises()

    expect(getWinRateSamples).not.toHaveBeenCalled()
    const text = wrapper.text()
    expect(text).toContain('综合对比')
    expect(text).toContain('三源尾盘共振')
    expect(text).toContain('同期对比（精选候选 T+5，按选出日）')
    expect(text).not.toContain('sanyuan-tail-v1')
    wrapper.unmount()
  })

  it('切到战法 tab 才拉样本，并写清分母与最佳/最差样本', async () => {
    vi.mocked(getWinRateSummary).mockResolvedValue([SUMMARY_ROW] as never)
    vi.mocked(getWinRateTrend).mockResolvedValue([] as never)
    vi.mocked(getWinRateSamples).mockResolvedValue(SAMPLE_DETAIL as never)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-tab="sanyuan-tail-v1"]').trigger('click')
    await flushPromises()

    expect(getWinRateSamples).toHaveBeenCalledWith({ tag: 'sanyuan-tail-v1' })
    const text = wrapper.text()
    // 分母写在页面上，观察中的样本单独交代——这就是「怎么算的」那一句
    expect(text).toContain('胜率 41.7% = 盈利 5 ÷ 已走完 T+5 的 12 条精选候选')
    expect(text).toContain('另有 6 条还在窗口内，不计入')
    // 最佳 / 最差样本点名到票，最佳持有期回答「该拿几天」
    expect(text).toContain('元利科技')
    expect(text).toContain('和远气体')
    expect(text).toContain('T+10')
    wrapper.unmount()
  })

  it('同一个战法来回切只请求一次样本', async () => {
    vi.mocked(getWinRateSummary).mockResolvedValue([SUMMARY_ROW] as never)
    vi.mocked(getWinRateTrend).mockResolvedValue([] as never)
    vi.mocked(getWinRateSamples).mockResolvedValue(SAMPLE_DETAIL as never)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-tab="sanyuan-tail-v1"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-tab="overview"]').trigger('click')
    await wrapper.get('[data-tab="sanyuan-tail-v1"]').trigger('click')
    await flushPromises()

    expect(vi.mocked(getWinRateSamples).mock.calls.length).toBe(1)
    wrapper.unmount()
  })
})

describe('工坊目录与异步隔离', () => {
  it('uses the current workshop name throughout tabs, tables and evidence', async () => {
    const custom = { ...SUMMARY_ROW, strategy_tag: 'yixian-auction', strategy_name: '一线定乾坤·首板次日' }
    vi.mocked(getWinRateSummary).mockResolvedValue([custom] as never)
    vi.mocked(getWinRateTrend).mockResolvedValue([{ period: '2026-09', strategy_tag: custom.strategy_tag, total: 2, wins: 1, win_rate: 50 }] as never)
    vi.mocked(getWinRateSamples).mockResolvedValue(SAMPLE_DETAIL as never)
    const wrapper = mountView()
    await flushPromises()
    expect(getWinRateSummary).toHaveBeenCalledWith({ current_only: true })
    expect(wrapper.get('[data-tab="yixian-auction"]').text()).toBe(custom.strategy_name)
    expect(wrapper.text()).not.toContain(custom.strategy_tag)
    expect(wrapper.text().split(custom.strategy_name).length).toBeGreaterThan(3)
    await wrapper.get('[data-tab="yixian-auction"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(`${custom.strategy_name} · 胜率与证据`)
    expect(wrapper.text()).not.toContain(custom.strategy_tag)
    vi.mocked(getWinRateSummary).mockResolvedValue([])
    await wrapper.findAll('button').find(button => button.text() === '刷新')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-tab="yixian-auction"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('胜率与证据')
    wrapper.unmount()
  })

  it('does not discard the initial summary when granularity changes while it loads', async () => {
    const pending = deferred<never>()
    vi.mocked(getWinRateSummary).mockReturnValue(pending.promise)
    vi.mocked(getWinRateTrend).mockResolvedValue([])
    const wrapper = mountView()
    await wrapper.get('select').setValue('week')
    pending.resolve([SUMMARY_ROW] as never)
    await flushPromises()
    expect(wrapper.find('[data-tab="sanyuan-tail-v1"]').exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'WinRateCompareTable' }).props('busy')).toBe(false)
    expect(getWinRateTrend).toHaveBeenLastCalledWith({ granularity: 'week', tags: 'sanyuan-tail-v1' })
    wrapper.unmount()
  })

  it('keeps cached A when a slower B response finishes after switching back', async () => {
    const slow = deferred<never>()
    vi.mocked(getWinRateSummary).mockResolvedValue([SUMMARY_ROW, { ...SUMMARY_ROW, strategy_tag: 'B' }] as never)
    vi.mocked(getWinRateTrend).mockResolvedValue([])
    vi.mocked(getWinRateSamples).mockImplementation(({ tag }) => tag === 'B' ? slow.promise : Promise.resolve(SAMPLE_DETAIL as never))
    const wrapper = mountView()
    await flushPromises()
    await wrapper.get('[data-tab="sanyuan-tail-v1"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-tab="B"]').trigger('click')
    await wrapper.get('[data-tab="sanyuan-tail-v1"]').trigger('click')
    slow.resolve({ ...SAMPLE_DETAIL, strategy_tag: 'B' } as never)
    await flushPromises()
    expect(wrapper.findComponent({ name: 'WinRateStrategyPanel' }).props('detail').strategy_tag).toBe('sanyuan-tail-v1')
    wrapper.unmount()
  })
})

describe('WinRateView trend changes', () => {
  it('keeps the trend for the latest granularity when a slower prior request resolves last', async () => {
    const month = deferred<never>()
    const week = deferred<never>()
    vi.mocked(getWinRateSummary).mockResolvedValue([{ strategy_tag: 'A', total: 1 }] as never)
    vi.mocked(getWinRateTrend).mockImplementation((options) =>
      options?.granularity === 'month' ? month.promise : week.promise,
    )

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('select').setValue('week')
    week.resolve([{ period: '2026-W01', strategy_tag: 'A', total: 3, wins: 2, win_rate: 88 }] as never)
    await flushPromises()
    month.resolve([{ period: '2026-01', strategy_tag: 'A', total: 3, wins: 1, win_rate: 12 }] as never)
    await flushPromises()

    expect(wrapper.text()).toContain('2026-W01')
    expect(wrapper.text()).not.toContain('2026-01')
    wrapper.unmount()
  })
})

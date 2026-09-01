import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import type { SignalItem } from '@/shared/api/marketStream'

/*
 * 信号流的三条硬约束（用户原话，不是我们推测的「合理默认」）：
 *   1. 榜单不许再被改个标签当信号——那是把同一份数据在旁边又说一遍；
 *   2. 超过 7 天的信号自动销毁；
 *   3. 只留最新 80 条。
 * 后端接口尚未就绪，这里全部打桩；契约已经钉死。
 */

const stream = vi.hoisted(() => ({
  streamQuotes: vi.fn(),
  streamSignals: vi.fn(),
  getRecentSignals: vi.fn(),
}))

const market = vi.hoisted(() => ({
  getLiveTape: vi.fn(),
  getMarketBoard: vi.fn(),
  getMarketDistribution: vi.fn(),
}))

vi.mock('@/shared/api/marketStream', () => stream)
vi.mock('@/shared/api/quant_market', () => market)

import { SIGNAL_MAX_AGE_DAYS, SIGNAL_MAX_ITEMS, useLiveBoard } from '../composables/useLiveBoard'

const DAY_MS = 24 * 60 * 60 * 1000
const MINUTE_MS = 60 * 1000

/** 永不 settle 的推流：让 connect() 停在「连着」的状态，测试自己控节奏 */
function pending(): Promise<void> {
  return new Promise<void>(() => undefined)
}

function boardRow(index: number) {
  return {
    code: `60000${index}`,
    name: `热票${index}`,
    price: 10 + index,
    pct: 9.9,
    change: 1,
    volume: 1000000,
    amount: 5000000000,
    turnover: 0.25,
    prev_close: 9,
    high: 11 + index,
    low: 9,
    open: 9.5,
  }
}

function signal(id: string, triggeredAt: string): SignalItem {
  return {
    id,
    code: '600519',
    name: '贵州茅台',
    strategy: 'ma_golden_cross',
    strategyName: '均线金叉',
    title: '金叉',
    detail: 'MA5 上穿 MA20',
    direction: 'long',
    strength: 60,
    price: 1800,
    pct: 1.2,
    provisional: false,
    triggeredAt,
  }
}

/** 泛型宿主：把 composable 的返回原样带出来，不用给它取名字 */
function mountHook<T>(hook: () => T): { api: T; wrapper: VueWrapper } {
  let api!: T
  const wrapper = mount(
    defineComponent({
      setup() {
        api = hook()
        return () => h('div')
      },
    }),
  )
  return { api, wrapper }
}

beforeEach(() => {
  vi.clearAllMocks()
  stream.streamQuotes.mockImplementation(pending)
  stream.streamSignals.mockImplementation(pending)
  stream.getRecentSignals.mockResolvedValue({ items: [], asOf: '' })
  market.getLiveTape.mockResolvedValue({ as_of: '2026-08-28 15:00:00', indices: [] })
  market.getMarketBoard.mockResolvedValue({
    items: Array.from({ length: 10 }, (_, i) => boardRow(i)),
  })
  market.getMarketDistribution.mockResolvedValue({ total_count: 0 })
})

describe('useLiveBoard 信号流', () => {
  it('喂满榜单 + 空信号流时，一条信号都不许造', async () => {
    const { api, wrapper } = mountHook(useLiveBoard)
    await flushPromises()

    // 榜单确实拿到了数据，否则这条用例是假绿
    expect(api.gainersRows.value.length).toBeGreaterThan(0)
    expect(api.amountRows.value.length).toBeGreaterThan(0)
    expect(api.turnoverRows.value.length).toBeGreaterThan(0)

    // 信号流仍然是空的：没有 snap_gainer_ / snap_amount_ / snap_turn_ 这类假货
    expect(api.signals.value).toEqual([])
    wrapper.unmount()
  })

  it('首屏信号来自真历史接口，而不是快照榜单', async () => {
    const fresh = signal('sig_real', new Date().toISOString())
    stream.getRecentSignals.mockResolvedValue({ items: [fresh], asOf: '2026-08-28T15:00:00' })

    const { api, wrapper } = mountHook(useLiveBoard)
    await flushPromises()

    expect(stream.getRecentSignals).toHaveBeenCalledWith(SIGNAL_MAX_ITEMS)
    expect(api.signals.value.map((row) => row.id)).toEqual(['sig_real'])
    wrapper.unmount()
  })

  it('历史接口 404/报错时空态收场，绝不回退造假', async () => {
    stream.getRecentSignals.mockRejectedValue(new Error('HTTP 404'))

    const { api, wrapper } = mountHook(useLiveBoard)
    await flushPromises()

    expect(api.signals.value).toEqual([])
    wrapper.unmount()
  })

  it('超过 7 天的信号被丢掉', async () => {
    const now = Date.now()
    stream.getRecentSignals.mockResolvedValue({
      items: [
        signal('sig_old', new Date(now - (SIGNAL_MAX_AGE_DAYS + 1) * DAY_MS).toISOString()),
        signal('sig_edge', new Date(now - SIGNAL_MAX_AGE_DAYS * DAY_MS + MINUTE_MS).toISOString()),
        signal('sig_fresh', new Date(now - MINUTE_MS).toISOString()),
      ],
      asOf: '',
    })

    const { api, wrapper } = mountHook(useLiveBoard)
    await flushPromises()

    expect(api.signals.value.map((row) => row.id)).toEqual(['sig_fresh', 'sig_edge'])
    wrapper.unmount()
  })

  it('超过 80 条只留最新的 80 条', async () => {
    const now = Date.now()
    // 第 i 条比上一条早一分钟：i 越小越新
    const items = Array.from({ length: 100 }, (_, i) =>
      signal(`sig_${i}`, new Date(now - i * MINUTE_MS).toISOString()),
    )
    stream.getRecentSignals.mockResolvedValue({ items, asOf: '' })

    const { api, wrapper } = mountHook(useLiveBoard)
    await flushPromises()

    expect(api.signals.value).toHaveLength(SIGNAL_MAX_ITEMS)
    expect(api.signals.value[0]?.id).toBe('sig_0')
    expect(api.signals.value[SIGNAL_MAX_ITEMS - 1]?.id).toBe('sig_79')
    expect(api.signals.value.some((row) => row.id === 'sig_80')).toBe(false)
    wrapper.unmount()
  })

  it('推流新信号排在历史前面，且仍受 80 条上限约束', async () => {
    const now = Date.now()
    stream.getRecentSignals.mockResolvedValue({
      items: Array.from({ length: SIGNAL_MAX_ITEMS }, (_, i) =>
        signal(`hist_${i}`, new Date(now - (i + 10) * MINUTE_MS).toISOString()),
      ),
      asOf: '',
    })
    type Push = (items: SignalItem[], seq: number) => void
    // 用容器接回调：直接 let 会被 TS 判成永远是 null（赋值发生在回调里）
    const live: { push: Push | null } = { push: null }
    stream.streamSignals.mockImplementation((opts: { onSignals: Push }) => {
      live.push = opts.onSignals
      return pending()
    })

    const { api, wrapper } = mountHook(useLiveBoard)
    await flushPromises()
    expect(api.signals.value).toHaveLength(SIGNAL_MAX_ITEMS)

    live.push?.([signal('sig_live', new Date(now).toISOString())], 1)
    await flushPromises()

    expect(api.signals.value).toHaveLength(SIGNAL_MAX_ITEMS)
    expect(api.signals.value[0]?.id).toBe('sig_live')
    expect(api.newSignalIds.value.has('sig_live')).toBe(true)
    wrapper.unmount()
  })
})

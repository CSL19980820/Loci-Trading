import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import type { QuoteFrame, QuoteRow } from '@/shared/api/marketStream'

/*
 * 行情帧的两条硬约束：
 *   1. quotesMap 不许单调增长——preset=all 的成员随日内轮换，挂机一天旧实现能攒到上万条；
 *   2. 四个榜单换成单趟部分选择后，结果必须与「全排序取前 10」逐行一致（含并列名次的先后）。
 * 这条用例专门喂满 20 帧、每帧 400 只不重样的票，把两件事一起钉住。
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
import { useLiveBoard } from '../composables/useLiveBoard'
import { QUOTE_CACHE_MAX } from '../lib/quoteState'

/** 永不 settle 的推流：让 connect() 停在「连着」的状态，测试自己控节奏 */
function pending(): Promise<void> {
  return new Promise<void>(() => undefined)
}

/**
 * 生成一只**不会**被 handleQuotesFrame 判成指数的票。
 * 指数判据是 sh000/sz399 前缀与五个裸码，600000 起的连号一个都不撞。
 */
function stockRow(seed: number, tick: number): QuoteRow {
  const code = String(600000 + seed)
  // 刻意制造大量并列：pct 只有 21 个取值，稳定性一旦丢失，Top10 立刻和全排序对不上
  const pct = ((seed + tick) % 21) - 10
  return {
    code,
    name: `票${seed}`,
    price: 10 + (seed % 97) / 10,
    prevClose: 10,
    change: 0.1,
    pct,
    volume: 1000 + seed,
    amount: ((seed * 7919) % 1000) * 1e6,
    turnover: ((seed * 31) % 40) / 2,
    amplitude: 1,
    speed: 0,
    high: 11,
    low: 9,
    open: 10,
    staleMs: 0,
  }
}

function frameOf(rows: QuoteRow[], seq: number): QuoteFrame {
  return {
    seq,
    asOf: `2026-09-09T09:${String(30 + seq).padStart(2, '0')}:00`,
    source: 'stream',
    session: { phase: 'morning', live: true },
    rows,
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

const FRAMES = 20
const ROWS_PER_FRAME = 400

beforeEach(() => {
  vi.clearAllMocks()
  stream.streamSignals.mockImplementation(pending)
  stream.getRecentSignals.mockResolvedValue({ items: [], asOf: '' })
  market.getLiveTape.mockResolvedValue({ as_of: '2026-09-09 09:30:00', indices: [] })
  market.getMarketBoard.mockResolvedValue({ items: [] })
  market.getMarketDistribution.mockResolvedValue({ total_count: 0 })
})

describe('useLiveBoard 行情帧', () => {
  it('连续多帧后报价缓存不超上限，且四榜与全排序结果逐行一致', async () => {
    const live: { push: ((frame: QuoteFrame) => void) | null } = { push: null }
    stream.streamQuotes.mockImplementation((opts: { onFrame: (frame: QuoteFrame) => void }) => {
      live.push = opts.onFrame
      return pending()
    })

    const { api, wrapper } = mountHook(useLiveBoard)
    await flushPromises()
    expect(live.push).not.toBeNull()

    let last: QuoteRow[] = []
    for (let tick = 0; tick < FRAMES; tick += 1) {
      // 每帧换一批全新的代码：模拟 select_active_universe 的日内轮换
      last = Array.from({ length: ROWS_PER_FRAME }, (_, i) =>
        stockRow(tick * ROWS_PER_FRAME + i, tick),
      )
      live.push?.(frameOf(last, tick))
    }
    await flushPromises()

    // 1. 上限：旧实现全程只 set 不 delete，这里会是 8000
    expect(api.quotesMap.value.size).toBeLessThanOrEqual(QUOTE_CACHE_MAX)
    // 真喂进去了才算数，否则上限断言是假绿
    expect(api.quotesMap.value.size).toBeGreaterThan(ROWS_PER_FRAME)

    // 2. 榜单：与「复制整个数组 + 全排序 + 取前 10」逐行一致（稳定性含在内）
    const topOf = (cmp: (a: QuoteRow, b: QuoteRow) => number) =>
      [...last]
        .sort(cmp)
        .slice(0, 10)
        .map((r) => r.code)

    expect(api.gainersRows.value.map((r) => r.code)).toEqual(topOf((a, b) => b.pct - a.pct))
    expect(api.losersRows.value.map((r) => r.code)).toEqual(topOf((a, b) => a.pct - b.pct))
    expect(api.turnoverRows.value.map((r) => r.code)).toEqual(
      topOf((a, b) => b.turnover - a.turnover),
    )
    expect(api.amountRows.value.map((r) => r.code)).toEqual(topOf((a, b) => b.amount - a.amount))

    wrapper.unmount()
  })

  it('quotesList 与 quotesMap 始终同步，页面不必每帧 Array.from 物化', async () => {
    const live: { push: ((frame: QuoteFrame) => void) | null } = { push: null }
    stream.streamQuotes.mockImplementation((opts: { onFrame: (frame: QuoteFrame) => void }) => {
      live.push = opts.onFrame
      return pending()
    })

    const { api, wrapper } = mountHook(useLiveBoard)
    await flushPromises()

    for (let tick = 0; tick < FRAMES; tick += 1) {
      const rows = Array.from({ length: ROWS_PER_FRAME }, (_, i) =>
 stockRow(tick * ROWS_PER_FRAME + i, tick),
      )
      live.push?.(frameOf(rows, tick))
    }
    await flushPromises()

    const list = api.quotesList.value
    const map = api.quotesMap.value
    expect(list).toHaveLength(map.size)
    // 每帧都换新引用，否则下游 props 不变、HeatStrip / TickerTape 不重算
    expect(new Set(list.map((r) => r.code)).size).toBe(map.size)
    for (const row of list) {
      expect(map.get(row.code)).toBe(row)
    }

    // 同一只票被后续帧刷新时，列表里必须是最新那一行，而不是追加一条
    const repeat = stockRow(0, 99)
    live.push?.(frameOf([repeat], FRAMES))
    await flushPromises()
    const refreshed = api.quotesList.value.filter((r) => r.code === repeat.code)
    expect(refreshed).toEqual([repeat])

    wrapper.unmount()
  })
})

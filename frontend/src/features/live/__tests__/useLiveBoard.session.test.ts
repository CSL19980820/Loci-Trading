import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import type { StreamStatus } from '@/shared/api/marketStream'

/*
 * 「大屏哪里都不像实时」那一轮的回归钉。三件事各钉一条：
 *   1. 会话相位与 live 必须能**在没有任何行情帧时**从 hello/heartbeat 拿到；
 *   2. 链路开着却一帧都没来，看门狗必须报「数据过期」（旧版要求先收到过帧，
 *      于是上游从头挂到尾时永远不报，界面一直显示「已连接」）；
 *   3. 采集器的失败原因要透出来，界面才说得出「数据源取数失败」而不是干瞪眼。
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

function pending(): Promise<void> {
  return new Promise<void>(() => undefined)
}

function status(patch: Partial<StreamStatus> = {}): StreamStatus {
  return {
    preset: 'all',
    session: { phase: 'morning', live: true },
    asOf: '',
    staleMs: -1,
    sourceError: '',
    rows: 0,
    errors: 0,
    ...patch,
  }
}

function mountBoard() {
  const seen: { board: ReturnType<typeof useLiveBoard> | null } = { board: null }
  const host = defineComponent({
    setup() {
      seen.board = useLiveBoard()
      return () => h('div')
    },
  })
  const wrapper = mount(host)
  return { wrapper, board: seen.board! }
}

describe('useLiveBoard 会话与数据新鲜度', () => {
  beforeEach(() => {
    vi.useRealTimers()
    stream.streamQuotes.mockReset()
    stream.streamSignals.mockReset()
    stream.getRecentSignals.mockReset().mockResolvedValue({ items: [], asOf: '' })
    market.getLiveTape.mockResolvedValue({ indices: [], as_of: '' })
    market.getMarketBoard.mockResolvedValue({ items: [] })
    market.getMarketDistribution.mockResolvedValue(null)
    stream.streamSignals.mockImplementation(() => pending())
  })

  it('没有任何行情帧时，相位与 live 从 hello 帧就位', async () => {
    const bus: { push?: (s: StreamStatus) => void } = {}
    stream.streamQuotes.mockImplementation((opts: { onStatus?: (s: StreamStatus) => void }) => {
      bus.push = opts.onStatus
      return pending()
    })

    const { wrapper, board } = mountBoard()
    await flushPromises()

    // 契约缺口那会儿：这里恒为 'closed' / false，顶栏于是全天「已收盘」
    bus.push?.(status({ session: { phase: 'noon_break', live: false } }))
    expect(board.sessionPhase.value).toBe('noon_break')
    expect(board.isLive.value).toBe(false)
    expect(board.status.value).toBe('connected')
    wrapper.unmount()
  })

  it('开着盘却一帧都没来：立刻标记数据过期，并透出数据源原因', async () => {
    const bus: { push?: (s: StreamStatus) => void } = {}
    stream.streamQuotes.mockImplementation((opts: { onStatus?: (s: StreamStatus) => void }) => {
      bus.push = opts.onStatus
      return pending()
    })

    const { wrapper, board } = mountBoard()
    await flushPromises()

    bus.push?.(status({ staleMs: -1, sourceError: '东财全市场截面失败：RemoteDisconnected' }))
    expect(board.dataStale.value).toBe(true)
    expect(board.sourceError.value).toContain('东财全市场截面失败')
    wrapper.unmount()
  })

  it('行情帧到达后清掉数据源告警，延迟归零', async () => {
    const handlers: { onStatus?: (s: StreamStatus) => void; onFrame?: (f: unknown) => void } = {}
    stream.streamQuotes.mockImplementation((opts: typeof handlers) => {
      Object.assign(handlers, opts)
      return pending()
    })

    const { wrapper, board } = mountBoard()
    await flushPromises()
    handlers.onStatus?.(status({ sourceError: '取数失败' }))
    expect(board.dataStale.value).toBe(true)

    handlers.onFrame?.({
      seq: 1,
      asOf: '2026-08-31 10:30:00',
      source: 'eastmoney_spot_all',
      session: { phase: 'morning', live: true },
      rows: [],
    })
    expect(board.dataStale.value).toBe(false)
    expect(board.sourceError.value).toBe('')
    expect(board.staleMs.value).toBe(0)
    expect(board.sessionPhase.value).toBe('morning')
    expect(board.isLive.value).toBe(true)
    wrapper.unmount()
  })
})

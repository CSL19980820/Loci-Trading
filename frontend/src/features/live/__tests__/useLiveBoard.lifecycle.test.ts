import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { KeepAlive, defineComponent, h, nextTick, ref, type Ref } from 'vue'
import type { QuoteFrame } from '@/shared/api/marketStream'

/*
 * 三条钉死的行为，全部来自用户实测的「盯盘大屏动不动就连接中断」：
 *
 *   1. KeepAlive 下离开大屏必须**真的停流**。PageHost 用 <KeepAlive> 包路由，
 *      离开时只触发 onDeactivated、不触发 onUnmounted；旧代码把 stopStream 挂在
 *onUnmounted 上，于是流在后台永久挂着，再进来又不重连，界面停在残留状态。
 *   2. 「链路建立」即判 connected，不必等第一帧。上游数据源挂掉时后端照常发心跳，
 *    链路是好的；用「收到帧」当连接判据，就会把数据源故障误报成连接中断。
 *   3. 链路好但交易时段长时间没有新帧 -> dataStale，单独报「数据源」，不碰 status。
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

import { useLiveBoard, type ConnectionStatus } from '../composables/useLiveBoard'

type QuotesOpts = {
  signal: AbortSignal
  onOpen?: () => void
  onFrame: (f: QuoteFrame) => void
  onError?: (e: unknown) => void
}

/** 本用例只依赖这两个出口；写成窄类型，顺手声明了这组测试的耦合面。 */
type BoardApi = {
  status: Ref<ConnectionStatus>
  dataStale: Ref<boolean>
}

const quotesCalls: QuotesOpts[] = []

/** 4 处调用共用同一份帧形状，改一处就得一起改，所以留成函数。 */
function frame(live: boolean): QuoteFrame {
  return {
    seq: 1,
    asOf: '2026-08-28 10:00:00',
    source: 'tdx',
    session: { phase: live ? 'morning' : 'closed', live },
    rows: [],
  }
}

/**
 * 把 composable 挂在 <KeepAlive> 里的真实子组件上。
 * 只有这样才会走到 onActivated / onDeactivated——直接 mount 是测不到的。
 */
function mountKeepAlive(): { api: () => BoardApi; wrapper: VueWrapper; alive: Ref<boolean> } {
  let api!: BoardApi
  const alive = ref(true)

  const Board = defineComponent({
    name: 'Board',
    setup() {
      api = useLiveBoard()
      return () => h('div', 'board')
    },
  })
  const Away = defineComponent({
    name: 'Away',
    setup() {
      return () => h('div', 'away')
    },
  })

  const wrapper = mount(
    defineComponent({
      setup() {
        return () => h(KeepAlive, null, { default: () => h(alive.value ? Board : Away) })
      },
    }),
  )
  return { api: () => api, wrapper, alive }
}

beforeEach(() => {
  vi.clearAllMocks()
  quotesCalls.length = 0
  // 永不 settle：让 connect() 停在「连着」，由测试自己控节奏
  stream.streamQuotes.mockImplementation((opts: QuotesOpts) => {
    quotesCalls.push(opts)
    return new Promise<void>(() => undefined)
  })
  stream.streamSignals.mockImplementation(() => new Promise<void>(() => undefined))
  stream.getRecentSignals.mockResolvedValue({ items: [], asOf: '' })
  market.getLiveTape.mockResolvedValue({ as_of: '2026-08-28 15:00:00', indices: [] })
  market.getMarketBoard.mockResolvedValue({ items: [] })
  market.getMarketDistribution.mockResolvedValue({ total_count: 0 })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useLiveBoard 生命周期(KeepAlive)', () => {
  it('离开大屏(deactivated)必须真的把流掐断', async () => {
    const { api, wrapper, alive } = mountKeepAlive()
    await flushPromises()

    expect(quotesCalls).toHaveLength(1)
    expect(quotesCalls[0].signal.aborted).toBe(false)

    // 切走：KeepAlive 只会触发 onDeactivated
    alive.value = false
    await nextTick()
    await flushPromises()

// 这一条就是老 bug 的照妖镜：挂在 onUnmounted 上时它是 false
    expect(quotesCalls[0].signal.aborted).toBe(true)

    wrapper.unmount()
  })

  it('切回大屏(activated)会重新建链，而不是停在残留状态', async () => {
    const { wrapper, alive } = mountKeepAlive()
    await flushPromises()

    alive.value = false
    await nextTick()
    await flushPromises()

    alive.value = true
    await nextTick()
    await flushPromises()

    expect(quotesCalls).toHaveLength(2)
    expect(quotesCalls[1].signal.aborted).toBe(false)

    wrapper.unmount()
  })

  it('信号历史只在首次建链回填一次，重连不重复打', async () => {
    const { wrapper, alive } = mountKeepAlive()
    await flushPromises()
    expect(stream.getRecentSignals).toHaveBeenCalledTimes(1)

    alive.value = false
    await nextTick()
    await flushPromises()
    alive.value = true
    await nextTick()
    await flushPromises()

    expect(quotesCalls).toHaveLength(2)
    expect(stream.getRecentSignals).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })
})

describe('useLiveBoard 链路与数据分开报', () => {
  it('链路建立(onOpen)即判已连接，不必等第一帧', async () => {
    const { api, wrapper } = mountKeepAlive()
    await flushPromises()

    expect(api().status.value).toBe('connecting')

    quotesCalls[0].onOpen?.()
    await nextTick()

    expect(api().status.value).toBe('connected')
    // 还没有任何一帧，所以此刻不该声称数据过期
    expect(api().dataStale.value).toBe(false)

    wrapper.unmount()
  })

  it('交易时段长时间没有新帧 -> dataStale，但 status 仍是已连接', async () => {
    vi.useFakeTimers()
    const { api, wrapper } = mountKeepAlive()
    await flushPromises()

    quotesCalls[0].onFrame(frame(true))
    expect(api().status.value).toBe('connected')
    expect(api().dataStale.value).toBe(false)

    // 45s 阈值：推到 60s 已经是「连着三轮都没喂上来」
    await vi.advanceTimersByTimeAsync(60_000)

    expect(api().dataStale.value).toBe(true)
    // 关键：不许把数据源故障说成连接问题
    expect(api().status.value).toBe('connected')

    // 数据回来后自愈
    quotesCalls[0].onFrame(frame(true))
    expect(api().dataStale.value).toBe(false)

    wrapper.unmount()
  })

  it('非交易时段没有新帧是正常的，不许报数据过期', async () => {
    vi.useFakeTimers()
    const { api, wrapper } = mountKeepAlive()
    await flushPromises()

    quotesCalls[0].onFrame(frame(false))
    await vi.advanceTimersByTimeAsync(120_000)

    expect(api().dataStale.value).toBe(false)

    wrapper.unmount()
  })
})

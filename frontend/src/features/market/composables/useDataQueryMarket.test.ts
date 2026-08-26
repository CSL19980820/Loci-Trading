import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useDataQueryMarket } from './useDataQueryMarket'

const api = vi.hoisted(() => ({
  getMarketBoard: vi.fn(),
  getMarketSession: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function board(code: string, live: boolean): Record<string, unknown> {
  return {
    total: 1,
    page: 1,
    page_size: 50,
    as_of: '2026-07-31 10:00:00',
    live_error: '',
    items: [
      {
        code,
        name: code,
        market: 'sz',
        board: 'main',
        instrument_type: 'STOCK',
        status: 'active',
        local_date: '2026-07-31',
        local_close: 10,
        local_pct: 1,
        live_close: live ? 11 : null,
        live_pct: live ? 2 : null,
        pct: live ? 2 : 1,
        turnover: null,
        trade_time: '',
        ok: live,
        source: live ? 'test' : 'local',
      },
    ],
  }
}

describe('useDataQueryMarket request ordering', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('does not let an older live response replace a newer list query', async () => {
    const firstLocal = deferred<Record<string, unknown>>()
    const oldLive = deferred<Record<string, unknown>>()
    const secondLocal = deferred<Record<string, unknown>>()
    let sessionCalls = 0

    api.getMarketSession.mockImplementation(() => {
      sessionCalls += 1
      return sessionCalls === 1
        ? Promise.resolve({ live_allowed: true })
        : new Promise(() => {})
    })
    api.getMarketBoard.mockImplementation((options: { live?: boolean; q?: string }) => {
      if (options.live) return oldLive.promise
      return options.q === 'new' ? secondLocal.promise : firstLocal.promise
    })

    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy: { value: false },
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    const firstLoad = market.loadBoard()
    firstLocal.resolve(board('old-local', false))
    await firstLoad
    await flushPromises()

    market.marketQ.value = 'new'
    const secondLoad = market.loadBoard()
    secondLocal.resolve(board('new-local', false))
    await secondLoad
    expect(market.boardRows.value[0]?.code).toBe('new-local')

    oldLive.resolve(board('old-live', true))
    await flushPromises()
    expect(market.boardRows.value[0]?.code).toBe('new-local')

    market.stopRefresh()
    wrapper.unmount()
  })

  it('keeps only one live timer when refresh starts overlap', async () => {
    vi.useFakeTimers()
    api.getMarketSession.mockResolvedValue({ live_allowed: true })
    api.getMarketBoard.mockResolvedValue(board('live', true))

    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy: { value: false },
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    market.startRefresh()
    market.startRefresh()
    await flushPromises()
    api.getMarketBoard.mockClear()

    vi.advanceTimersByTime(12_000)
    expect(api.getMarketBoard).toHaveBeenCalledTimes(1)

    market.stopRefresh()
    wrapper.unmount()
  })

  it('does not overlap live enrichment while the previous request is pending', async () => {
    vi.useFakeTimers()
    api.getMarketSession.mockResolvedValue({ live_allowed: true })
    const live = deferred<Record<string, unknown>>()
    let liveCalls = 0
    api.getMarketBoard.mockImplementation((options: { live?: boolean }) => {
      if (options.live) {
        liveCalls += 1
        return live.promise
      }
      return Promise.resolve(board('local', false))
    })

    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy: { value: false },
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    market.startRefresh()
    await flushPromises()
    vi.advanceTimersByTime(12_000)
    vi.advanceTimersByTime(12_000)

    expect(liveCalls).toBe(1)
    live.resolve(board('live', true))
    await flushPromises()
    market.stopRefresh()
    wrapper.unmount()
  })

  it('does not let an in-flight live response replace data after refresh stops', async () => {
    const live = deferred<Record<string, unknown>>()
    api.getMarketSession.mockResolvedValue({ live_allowed: true })
    api.getMarketBoard.mockImplementation((options: { live?: boolean }) => {
      return options.live ? live.promise : Promise.resolve(board('local', false))
    })

    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy: { value: false },
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    await market.loadBoard()
    await flushPromises()
    expect(market.boardRows.value[0]?.code).toBe('local')

    market.stopRefresh()
    live.resolve(board('stale-live', true))
    await flushPromises()
    expect(market.boardRows.value[0]?.code).toBe('local')
    wrapper.unmount()
  })

  it('does not let an older session response override a restarted refresh gate', async () => {
    vi.useFakeTimers()
    const first = deferred<{ live_allowed: boolean }>()
    const second = deferred<{ live_allowed: boolean }>()
    api.getMarketSession
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise)
      .mockResolvedValue({ live_allowed: true })
    api.getMarketBoard.mockResolvedValue(board('live', true))

    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy: { value: false },
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    market.startRefresh()
    market.startRefresh()
    second.resolve({ live_allowed: true })
    await flushPromises()
    first.resolve({ live_allowed: false })
    await flushPromises()
    api.getMarketBoard.mockClear()

    vi.advanceTimersByTime(12_000)
    await flushPromises()
    expect(api.getMarketBoard).toHaveBeenCalledTimes(1)

    market.stopRefresh()
    wrapper.unmount()
  })

  it('fails closed when the session gate request fails', async () => {
    api.getMarketSession.mockRejectedValue(new Error('session unavailable'))
    api.getMarketBoard.mockResolvedValue(board('local', false))

    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy: { value: false },
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    await market.loadBoard()
    await flushPromises()
    expect(api.getMarketBoard.mock.calls.some(([options]) => options.live === true)).toBe(false)
    wrapper.unmount()
  })

  it('does not leave busy stuck when KeepAlive activate restarts refresh during loadBoard', async () => {
    const local = deferred<Record<string, unknown>>()
    api.getMarketSession.mockResolvedValue({ live_allowed: false })
    api.getMarketBoard.mockImplementation((options: { live?: boolean }) => {
      if (options.live) return Promise.resolve(board('live', true))
      return local.promise
    })

    const busy = { value: false }
    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy,
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    const pending = market.loadBoard()
    expect(busy.value).toBe(true)

    // KeepAlive 首次挂载会同步 onActivated → startRefresh → stopRefresh，
    // 旧实现抬高 boardRequestSeq 后 loadBoard 的 finally 不再清 busy。
    market.startRefresh()

    local.resolve(board('local', false))
    await pending
    await flushPromises()

    expect(busy.value).toBe(false)
    expect(market.boardRows.value[0]?.code).toBe('local')
    expect(market.boardTotal.value).toBe(1)

    market.stopRefresh()
    wrapper.unmount()
  })

  it('clears liveEnriching when refresh stops during an in-flight live request', async () => {
    const live = deferred<Record<string, unknown>>()
    api.getMarketSession.mockResolvedValue({ live_allowed: true })
    api.getMarketBoard.mockImplementation((options: { live?: boolean }) => {
      return options.live ? live.promise : Promise.resolve(board('local', false))
    })

    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy: { value: false },
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    await market.loadBoard()
    await flushPromises()
    expect(market.liveEnriching.value).toBe(true)

    market.stopRefresh()
    expect(market.liveEnriching.value).toBe(false)

    live.resolve(board('stale-live', true))
    await flushPromises()
    expect(market.boardRows.value[0]?.code).toBe('local')
    expect(market.liveEnriching.value).toBe(false)

    wrapper.unmount()
  })

  it('sends the current keyword when searching', async () => {
    api.getMarketSession.mockResolvedValue({ live_allowed: false })
    api.getMarketBoard.mockResolvedValue(board('local', false))

    let market!: ReturnType<typeof useDataQueryMarket>
    const Probe = defineComponent({
      setup() {
        market = useDataQueryMarket({
          route: { fullPath: '/data' } as never,
          router: { push: vi.fn() } as never,
          busy: { value: false },
          error: { value: '' },
          liveError: { value: '' },
        })
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    market.marketQ.value = '不存在证券-审计'
    await market.onSearch()

    expect(api.getMarketBoard.mock.calls.at(-1)?.[0]).toMatchObject({
      q: '不存在证券-审计',
      live: false,
    })
    wrapper.unmount()
  })
})

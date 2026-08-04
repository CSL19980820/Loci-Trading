import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getTodayAlerts: vi.fn(),
  getLiveTape: vi.fn(),
  getMarketBoard: vi.fn(),
  getMarketSession: vi.fn(),
  getScreenHistory: vi.fn(),
  getStrategies: vi.fn(),
  getCandidateOutcomes: vi.fn(),
}))

vi.mock('@/shared/api/palace', () => api)
vi.mock('@/shared/api/quant', () => api)
vi.mock('@/shared/composables/useLivePolling', () => ({
  useLivePolling: vi.fn(),
}))

import { usePulseHome } from './usePulseHome'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function board(code: string): Record<string, unknown> {
  return {
    total: 1,
    page: 1,
    page_size: 40,
    as_of: '2026-07-31 15:00:00',
    live_error: '',
    items: [
      {
        code,
        name: code,
        market: 'sz',
        board: 'main',
        industry: '测试',
        instrument_type: 'STOCK',
        status: 'normal',
        local_date: '2026-07-31',
        local_close: 10,
        local_pct: 1,
        pct: 1,
        turnover: 0.1,
        ok: false,
        source: 'local',
      },
    ],
  }
}

function mountHome() {
  let home!: ReturnType<typeof usePulseHome>
  const Probe = defineComponent({
    setup() {
      home = usePulseHome()
      return () => h('div')
    },
  })
  const wrapper = mount(Probe)
  return { home, wrapper }
}

describe('usePulseHome request ordering', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  function stubScreenApis() {
    api.getStrategies.mockResolvedValue([])
    api.getScreenHistory.mockResolvedValue({ strategy: '', total: 0, dates: [], by_date: {} })
    api.getCandidateOutcomes.mockResolvedValue({ outcomes: [], summary: {} })
  }

  it('does not let an older board-tab response replace the current tab', async () => {
    const oldTab = deferred<Record<string, unknown>>()
    const currentTab = deferred<Record<string, unknown>>()
    api.getMarketSession.mockResolvedValue({ live_allowed: false, today: '2026-07-31' })
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], positions: [], items: [], as_of: '' })
    stubScreenApis()
    api.getMarketBoard.mockImplementation((options: { sort?: string }) => {
      if (options.sort === 'pct_asc') return oldTab.promise
      if (options.sort === 'pct_desc') {
        const calls = api.getMarketBoard.mock.calls.filter(
          ([call]) => call.sort === 'pct_desc',
        )
        if (calls.length > 1) return currentTab.promise
      }
      return Promise.resolve(board('initial'))
    })

    const { home, wrapper } = mountHome()
    await flushPromises()

    const stale = home.setBoardTab('loss')
    const current = home.setBoardTab('gain')
    currentTab.resolve(board('current-gain'))
    await current
    oldTab.resolve(board('stale-loss'))
    await stale

    expect(home.boardTab.value).toBe('gain')
    expect(home.boardRows.value[0]?.code).toBe('current-gain')
    wrapper.unmount()
  })

  it('does not force live requests when the session gate is unavailable', async () => {
    api.getMarketSession.mockRejectedValue(new Error('session unavailable'))
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], positions: [], items: [], as_of: '' })
    stubScreenApis()
    api.getMarketBoard.mockResolvedValue(board('local'))

    const { wrapper } = mountHome()
    await flushPromises()

    const boardCalls = api.getMarketBoard.mock.calls.map(([call]) => call)
    expect(boardCalls.some((call) => call.live === true)).toBe(false)
    wrapper.unmount()
  })

  it('surfaces a live-tape failure instead of silently keeping the refresh green', async () => {
    api.getMarketSession.mockResolvedValue({ live_allowed: false, today: '2026-07-31' })
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape
      .mockResolvedValueOnce({ indices: [], positions: [], items: [], as_of: '' })
      .mockRejectedValueOnce(new Error('live tape unavailable'))
    stubScreenApis()
    api.getMarketBoard.mockResolvedValue(board('local'))

    const { home, wrapper } = mountHome()
    await flushPromises()
    await home.reload()

    expect(home.tapeError.value).toContain('live tape unavailable')
    wrapper.unmount()
  })

  it('distinguishes a partial strategy-history failure from an empty result', async () => {
    api.getMarketSession.mockResolvedValue({ live_allowed: false, today: '2026-07-31' })
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], positions: [], items: [], as_of: '' })
    api.getStrategies.mockResolvedValue([
      { slug: 'good', name: '正常策略' },
      { slug: 'bad', name: '失败策略' },
    ])
    api.getCandidateOutcomes.mockResolvedValue({ outcomes: [], summary: {} })
    api.getScreenHistory.mockImplementation(({ strategy }: { strategy: string }) =>
      strategy === 'bad'
        ? Promise.reject(new Error('history unavailable'))
        : Promise.resolve({ strategy, total: 0, dates: [], by_date: {} }),
    )
    api.getMarketBoard.mockResolvedValue(board('local'))

    const { home, wrapper } = mountHome()
    await flushPromises()

    expect(home.historyError.value).toContain('失败策略')
    wrapper.unmount()
  })

  it('loads local daily pct for picks after the live window closes', async () => {
    api.getMarketSession.mockResolvedValue({ live_allowed: false, today: '2026-07-31' })
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], positions: [], items: [], as_of: '' })
    api.getStrategies.mockResolvedValue([{ slug: 'demo', name: '示例策略' }])
    api.getCandidateOutcomes.mockResolvedValue({ outcomes: [], summary: {} })
    api.getScreenHistory.mockResolvedValue({
      strategy: 'demo',
      total: 1,
      dates: ['2026-07-31'],
      by_date: {
        '2026-07-31': [
          { code: '600519', name: '贵州茅台', score: 88, reason: '测试' },
        ],
      },
    })
    api.getMarketBoard.mockResolvedValue(board('600519'))

    const { home, wrapper } = mountHome()
    await flushPromises()

    expect(home.todayRows.value[0]?.pct).toBe(1)
    expect(home.pickPctMode.value).toBe('local')
    expect(
      api.getMarketBoard.mock.calls.some(
        ([options]) => options.live === false && options.codes?.includes('600519'),
      ),
    ).toBe(true)
    wrapper.unmount()
  })
})

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getTodayAlerts: vi.fn(),
  getLiveTape: vi.fn(),
  getMarketBoard: vi.fn(),
  getMarketSession: vi.fn(),
  getScreenHistory: vi.fn(),
  getScreenHistoryBatch: vi.fn(),
  getStrategies: vi.fn(),
  getCandidateOutcomes: vi.fn(),
}))

vi.mock('@/shared/api/palace', () => api)
vi.mock('@/shared/api/quant', () => api)
vi.mock('@/shared/composables/useLivePolling', () => ({
  useLivePolling: vi.fn(),
}))

import { useLivePolling } from '@/shared/composables/useLivePolling'
import { usePulseHome } from './usePulseHome'

const useLivePollingMock = vi.mocked(useLivePolling)

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
  let pollTick: (() => void | Promise<void>) | undefined
  useLivePollingMock.mockImplementation(({ tick }) => {
    pollTick = tick
    return {
      session: ref(null),
      liveAllowed: ref(false),
      refreshSession: vi.fn(),
      refreshOnce: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
      runTick: vi.fn(),
    }
  })
  const Probe = defineComponent({
    setup() {
      home = usePulseHome()
      return () => h('div')
    },
  })
  const wrapper = mount(Probe)
  return { home, wrapper, pollTick: () => pollTick!() }
}

describe('usePulseHome request ordering', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  function stubScreenApis() {
    api.getStrategies.mockResolvedValue([])
    api.getScreenHistoryBatch.mockResolvedValue({ strategies: [], histories: [] })
    api.getCandidateOutcomes.mockResolvedValue({ outcomes: [], summary: {} })
  }

  it('does not let an older board-tab response replace the current tab', async () => {
    const oldTab = deferred<Record<string, unknown>>()
    const currentTab = deferred<Record<string, unknown>>()
    api.getMarketSession.mockResolvedValue({ live_allowed: false, today: '2026-07-31' })
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], items: [], as_of: '' })
    stubScreenApis()
    api.getMarketBoard.mockImplementation((options: { sort?: string }) => {
      if (options.sort === 'turnover_desc') return oldTab.promise
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

    const stale = home.setBoardTab('turnover')
    const current = home.setBoardTab('gain')
    currentTab.resolve(board('current-gain'))
    await current
    oldTab.resolve(board('stale-turnover'))
    await stale

    expect(home.boardTab.value).toBe('gain')
    expect(home.boardRows.value[0]?.code).toBe('current-gain')
    wrapper.unmount()
  })

  it('does not force live requests when the session gate is unavailable', async () => {
    api.getMarketSession.mockRejectedValue(new Error('session unavailable'))
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], items: [], as_of: '' })
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
      .mockResolvedValueOnce({ indices: [], items: [], as_of: '' })
      .mockRejectedValueOnce(new Error('live tape unavailable'))
    stubScreenApis()
    api.getMarketBoard.mockResolvedValue(board('local'))

    const { home, wrapper } = mountHome()
    await flushPromises()
    await home.reload()

    expect(home.tapeError.value).toContain('live tape unavailable')
    wrapper.unmount()
  })

  it('distinguishes a batch strategy-history failure from an empty result', async () => {
    api.getMarketSession.mockResolvedValue({ live_allowed: false, today: '2026-07-31' })
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], items: [], as_of: '' })
    api.getStrategies.mockResolvedValue([
      { slug: 'good', name: '正常策略' },
      { slug: 'bad', name: '失败策略' },
    ])
    api.getCandidateOutcomes.mockResolvedValue({ outcomes: [], summary: {} })
    api.getScreenHistoryBatch.mockRejectedValue(new Error('history unavailable'))
    api.getMarketBoard.mockResolvedValue(board('local'))

    const { home, wrapper } = mountHome()
    await flushPromises()

    expect(home.historyError.value).toContain('选股历史')
    wrapper.unmount()
  })

  it('loads local daily pct for picks after the live window closes', async () => {
    api.getMarketSession.mockResolvedValue({ live_allowed: false, today: '2026-07-31' })
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], items: [], as_of: '' })
    api.getStrategies.mockResolvedValue([{ slug: 'demo', name: '示例策略' }])
    api.getCandidateOutcomes.mockResolvedValue({ outcomes: [], summary: {} })
    api.getScreenHistoryBatch.mockResolvedValue({
      strategies: ['demo'],
      histories: [
        {
          strategy: 'demo',
          total: 1,
          dates: ['2026-07-31'],
          by_date: {
            '2026-07-31': [
              { code: '000001', name: '平安银行', score: 88, reason: '测试' },
            ],
          },
        },
      ],
    })
    api.getMarketBoard.mockImplementation((options: { codes?: string; sort?: string }) => {
      if (options.codes) return Promise.resolve(board('000001'))
      return Promise.resolve(board('600519'))
    })

    const { home, wrapper } = mountHome()
    await flushPromises()

    expect(home.todayRows.value[0]?.pct).toBe(1)
    expect(home.pickPctMode.value).toBe('local')
    expect(
      api.getMarketBoard.mock.calls.some(
        ([options]) => options.live === false && options.codes?.includes('000001'),
      ),
    ).toBe(true)
    wrapper.unmount()
  })

  it('poll tick always refreshes tape; board every other cycle; spot reuses board rows', async () => {
    api.getMarketSession.mockResolvedValue({ live_allowed: true, today: '2026-07-31' })
    api.getTodayAlerts.mockResolvedValue([])
    api.getLiveTape.mockResolvedValue({ indices: [], items: [], as_of: '' })
    api.getStrategies.mockResolvedValue([{ slug: 'demo', name: '示例策略' }])
    api.getCandidateOutcomes.mockResolvedValue({ outcomes: [], summary: {} })
    api.getScreenHistoryBatch.mockResolvedValue({
      strategies: ['demo'],
      histories: [
        {
          strategy: 'demo',
          total: 2,
          dates: ['2026-07-31'],
          by_date: {
            '2026-07-31': [
              { code: '600519', name: '贵州茅台', score: 88, reason: '榜内' },
              { code: '000001', name: '平安银行', score: 77, reason: '榜外' },
            ],
          },
        },
      ],
    })
    api.getMarketBoard.mockImplementation((options: { sort?: string; codes?: string | string[] }) => {
      if (options.codes) {
        const raw = Array.isArray(options.codes) ? options.codes.join(',') : String(options.codes)
        const code = raw.split(',')[0]
        return Promise.resolve(board(code))
      }
      return Promise.resolve(board('600519'))
    })

    const { home, wrapper, pollTick } = mountHome()
    await flushPromises()

    const callsBeforePoll = api.getMarketBoard.mock.calls.length
    const tapeBeforePoll = api.getLiveTape.mock.calls.length

    // tick1（奇）：tape + spot（复用榜，仅补 000001）；不刷市场榜
    await pollTick()
    await flushPromises()
    expect(api.getLiveTape.mock.calls.length).toBe(tapeBeforePoll + 1)
    const firstPollBoard = api.getMarketBoard.mock.calls.slice(callsBeforePoll)
    expect(firstPollBoard.some(([call]) => call.sort === 'pct_desc')).toBe(false)
    expect(firstPollBoard.some(([call]) => String(call.codes).includes('000001'))).toBe(true)
    expect(firstPollBoard.some(([call]) => String(call.codes).includes('600519'))).toBe(false)
    expect(home.todayRows.value.find((r) => r.code === '600519')?.pct).toBe(1)

    const callsBeforeSecond = api.getMarketBoard.mock.calls.length
    const tapeBeforeSecond = api.getLiveTape.mock.calls.length
    // tick2（偶）：tape + 市场榜 + spot（同 tick 复用刚刷的榜）
    await pollTick()
    await flushPromises()
    expect(api.getLiveTape.mock.calls.length).toBe(tapeBeforeSecond + 1)
    const secondPollBoard = api.getMarketBoard.mock.calls.slice(callsBeforeSecond)
    expect(secondPollBoard.some(([call]) => call.sort === 'pct_desc')).toBe(true)
    expect(secondPollBoard.some(([call]) => String(call.codes).includes('000001'))).toBe(true)
    expect(secondPollBoard.some(([call]) => String(call.codes).includes('600519'))).toBe(false)
    wrapper.unmount()
  })
})

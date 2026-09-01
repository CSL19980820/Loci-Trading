/**
 * 首页盘面数据：指数/仓摘要、近选跟踪（T～T+4）、市场榜、今日选股。
 * 数字以后端与 live 叠价为准；无数据诚实空态，不掺演示票。
 */
import { computed, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'

import { getTodayAlerts } from '@/shared/api/palace'
import { ElMessage } from 'element-plus'

import {
  getCandidateOutcomes,
  getLiveTape,
  getMarketBoard,
  getMarketSession,
  getScreenHistoryBatch,
  getStrategies,
  persistMarketBoardSpot,
  type LiveTape,
  type LiveTapeItem,
} from '@/shared/api/quant'
import { useLivePolling } from '@/shared/composables/useLivePolling'
import { toErrorMessage } from '@/shared/lib/errors'
import type { MarketSession } from '@/shared/lib/marketSession'
import type { BoardRow, ScreenCandidate, StrategyInfo } from '@/shared/types/quant'

import {
  boardRowsToSpotMap,
  changeFromEntry,
  collectPicksForDate,
  dedupeTrackRowsByDayCode,
  effectivePct,
  excludeTodayFromTrack,
  horizonReturn,
  localIsoDate,
  rankBoardRows,
  rankSectorRows,
  screenSessionDay,
  splitScreenDates,
  strategyDisplayName,
  swingFromLowHigh,
  trackAsOfDate,
  type PulseBoardTab,
  type PulsePickRow,
  type SectorBoardRow,
} from './pulseHomeLogic'

export type { PulseBoardTab, PulsePickRow, SectorBoardRow }

/** 近选跟踪行：选入价/最新/累计涨跌 + 后端 T+1/T+3。 */
export type PulseTrackRow = {
  rank: number
  code: string
  name: string
  date: string
  strategy: string
  strategyName: string
  entryPrice: number | null
  latestPrice: number | null
  changePct: number | null
  swingPct: number | null
  t1: number | null
  t3: number | null
}

export type PickPctMode = 'live' | 'local' | 'none'

export { effectivePct }

const TRACK_WINDOW_DAYS = 5

function sessionLabel(session: MarketSession | null): string {
  if (!session) return '—'
  if (!session.is_trading_day) return '休市'
  const reason = session.live_reason
  if (reason === 'live_window' || session.in_live_clock) return '交易中'
  if (reason === 'before_open') return '开盘前'
  if (typeof reason === 'string' && reason.startsWith('after_close')) return '已收盘'
  return session.live_allowed ? '交易中' : '休市'
}

function boardLatestPrice(row: BoardRow | undefined): number | null {
  if (!row) return null
  if (row.price != null && Number.isFinite(Number(row.price))) return Number(row.price)
  if (row.local_close != null && Number.isFinite(Number(row.local_close))) {
    return Number(row.local_close)
  }
  return null
}

export function usePulseHome() {
  const loading = ref(false)
  const spotPersistBusy = ref(false)
  const error = ref('')
  const session = ref<MarketSession | null>(null)
  const tape = ref<LiveTape | null>(null)
  const strategies = ref<StrategyInfo[]>([])
  const trackRows = ref<PulseTrackRow[]>([])
  const todayRows = ref<PulsePickRow[]>([])
  const trackNote = ref('')
  const todayDate = ref('')
  // null = 尚未加载/加载失败；0 才是「一次都没跑过」的真·新用户
  const screenHistoryTotal = ref<number | null>(null)
  const boardTab = ref<PulseBoardTab>('gain')
  const boardRows = ref<BoardRow[]>([])
  const sectorRows = ref<SectorBoardRow[]>([])
  const boardNote = ref('')
  const boardAsOf = ref('')
  const pickPctMode = ref<PickPctMode>('none')
  const alertCount = ref(0)
  const clock = ref('')
  const tapeError = ref('')
  const historyError = ref('')
  const alertsError = ref('')
  let dataGeneration = 0
  let boardRequestSeq = 0
  let livePollTick = 0

  function isCurrent(generation: number): boolean {
    return generation === dataGeneration
  }

  function liveRequestAllowed(): boolean {
    return session.value != null && Boolean(session.value.live_allowed)
  }

  const indices = computed(() => tape.value?.indices ?? [])
  const sessionText = computed(() => sessionLabel(session.value))
  const asOfText = computed(() => {
    const raw = tape.value?.as_of || session.value?.now || ''
    if (!raw) return clock.value
    const part = raw.includes(' ') ? raw.split(' ')[1] : raw
    return part ? String(part).slice(0, 8) : raw
  })

  async function refreshTape(generation = dataGeneration): Promise<void> {
    try {
      const next = await getLiveTape(true)
      if (!isCurrent(generation)) return
      tape.value = next
      tapeError.value = ''
      if (next.as_of) clock.value = next.as_of
    } catch (caught: unknown) {
      if (!isCurrent(generation)) return
      tapeError.value = toErrorMessage(caught, '指数行情更新失败')
    }
  }

  async function loadBoard(generation = dataGeneration): Promise<void> {
    const requestSeq = ++boardRequestSeq
    const tab = boardTab.value
    const sort =
      tab === 'turnover' ? 'turnover_desc' : 'pct_desc'
    const liveAllowed = liveRequestAllowed()
    try {
      const board = await getMarketBoard({
        live: liveAllowed,
        // 轮询只读 live；persist 需写鉴权，绑 live 会在 production 整请求 401
        persist: false,
        page: 1,
        // 板块聚合需要更宽样本；涨幅/换手仍取前页即可
        page_size: tab === 'sector' ? 100 : 40,
        sort,
        instrument_type: 'STOCK',
        status: 'normal',
      })
      if (!isCurrent(generation) || requestSeq !== boardRequestSeq) return
      if (tab === 'sector') {
        // 股票行仍缓存，供选股叠价复用；展示走行业聚合
        boardRows.value = rankBoardRows(board.items, 'gain')
        sectorRows.value = rankSectorRows(board.items)
      } else {
        boardRows.value = rankBoardRows(board.items, tab)
        sectorRows.value = []
      }
      boardAsOf.value = board.as_of || ''
      const liveHint = board.live_error ? `实时降级：${board.live_error}` : ''
      const sectorHint =
        tab === 'sector'
          ? liveAllowed
            ? '库内行业·成交额加权（叠实时价）'
            : '库内行业·成交额加权（本地日线）'
          : ''
      boardNote.value = [sectorHint, liveHint].filter(Boolean).join(' · ')
    } catch (caught: unknown) {
      if (!isCurrent(generation) || requestSeq !== boardRequestSeq) return
      boardRows.value = []
      sectorRows.value = []
      boardAsOf.value = ''
      boardNote.value = toErrorMessage(caught, '市场榜加载失败')
    }
  }

  async function overlaySpot(
    codes: string[],
    generation: number,
  ): Promise<Map<string, BoardRow>> {
    if (!codes.length) return new Map()
    const live = liveRequestAllowed()
    const spot = await getMarketBoard({
      codes,
      live,
      persist: false,
      page_size: Math.max(10, codes.length),
      instrument_type: 'all',
    })
    if (!isCurrent(generation)) return new Map()
    pickPctMode.value = live ? 'live' : 'local'
    return new Map(spot.items.map((item) => [item.code, item] as const))
  }

  function syncPickPctMode(): void {
    pickPctMode.value = liveRequestAllowed() ? 'live' : 'local'
  }

  async function resolveSpotMap(
    codes: string[],
    generation: number,
    reuseBoard: boolean,
  ): Promise<Map<string, BoardRow>> {
    const spotMap = reuseBoard ? boardRowsToSpotMap(boardRows.value) : new Map<string, BoardRow>()
    const missing = codes.filter((code) => !spotMap.has(code))
    if (missing.length) {
      const extra = await overlaySpot(missing, generation)
      for (const [code, row] of extra) spotMap.set(code, row)
    } else {
      syncPickPctMode()
    }
    return spotMap
  }

  function applySpotOverlay(spotMap: Map<string, BoardRow>): void {
    if (!spotMap.size) return

    const nextTrack = [...trackRows.value]
      .map((r) => {
        const spot = spotMap.get(r.code)
        const latest = boardLatestPrice(spot) ?? r.latestPrice
        const liveSwing =
          r.swingPct == null && spot ? swingFromLowHigh(spot.low, spot.high) : null
        return {
          ...r,
          name: spot?.name || r.name,
          latestPrice: latest,
          changePct: changeFromEntry(r.entryPrice, latest),
          swingPct: r.swingPct ?? liveSwing,
        }
      })
      .sort((a, b) => {
        if (a.date !== b.date) return a.date < b.date ? 1 : -1
        return (b.changePct ?? -999) - (a.changePct ?? -999)
      })
      .map((r, i) => ({ ...r, rank: i + 1 }))

    const trackChanged = nextTrack.some((nr, i) => {
      const prev = trackRows.value[i]
      if (!prev) return true
      return (
        nr.code !== prev.code ||
        nr.latestPrice !== prev.latestPrice ||
        nr.changePct !== prev.changePct
      )
    }) || nextTrack.length !== trackRows.value.length

    if (trackChanged) {
      trackRows.value = nextTrack
    }

    const nextToday = todayRows.value.map((r) => {
      const spot = spotMap.get(r.code)
      return {
        ...r,
        pct: spot ? effectivePct(spot) : r.pct,
        name: spot?.name || r.name,
      }
    })

    const todayChanged = nextToday.some((nr, i) => {
      const prev = todayRows.value[i]
      if (!prev) return true
      return nr.code !== prev.code || nr.pct !== prev.pct
    }) || nextToday.length !== todayRows.value.length

    if (todayChanged) {
      todayRows.value = nextToday
    }
  }

  async function loadScreenTables(generation = dataGeneration): Promise<void> {
    try {
      const list = await getStrategies()
      if (!isCurrent(generation)) return
      strategies.value = list
      const nameBySlug = new Map(list.map((s) => [s.slug, s.name]))

      const calendarToday = session.value?.today || localIsoDate()
      const sessionDay = screenSessionDay({
        calendarToday,
        lastTradingDay: session.value?.last_trading_day,
        coverageLastDate: session.value?.coverage_last_date,
        expectedLastDate: session.value?.expected_last_date,
        liveReason: session.value?.live_reason,
      })
      const coverageDay =
        session.value?.coverage_last_date || session.value?.expected_last_date || sessionDay
      // 近选跟踪不含当天：锚点优先昨收，展示前再剔除选股日=今天。
      const trackAsOf = trackAsOfDate(
        calendarToday,
        coverageDay,
        Boolean(session.value?.is_trading_day),
      )

      const [trackResult, historyBatch] = await Promise.all([
        getCandidateOutcomes(400, {
          window_days: TRACK_WINDOW_DAYS,
          selected_only: true,
          as_of: trackAsOf,
        })
          .then((payload) => ({ outcomes: payload.outcomes, failed: false }))
          .catch(() => ({ outcomes: [], failed: true })),
        list.length
          ? getScreenHistoryBatch({
              strategies: list.map((s) => s.slug),
              limit: 80,
              live_only: true,
            })
              .then((payload) => ({ histories: payload.histories, failed: false }))
              .catch(() => ({
                histories: list.map((s) => ({
                  strategy: s.slug,
                  total: 0,
                  dates: [] as string[],
                  by_date: {} as Record<string, ScreenCandidate[]>,
                })),
                failed: true,
              }))
          : Promise.resolve({ histories: [], failed: false }),
      ])
      if (!isCurrent(generation)) return

      const parts: string[] = []
      if (trackResult.failed) parts.push('近选跟踪')
      if (historyBatch.failed) parts.push('选股历史')
      historyError.value = parts.length ? `部分数据加载失败：${parts.join('；')}` : ''

      const histories = historyBatch.histories
      screenHistoryTotal.value = historyBatch.failed
        ? null
        : histories.reduce((sum, h) => sum + h.dates.length, 0)
      const dateSet = new Set<string>()
      for (const h of histories) {
        for (const d of h.dates) dateSet.add(d)
      }
      const dates = [...dateSet].sort((a, b) => (a < b ? 1 : a > b ? -1 : 0))
      const { todayHit } = splitScreenDates(dates, calendarToday, sessionDay)
      todayDate.value = todayHit

      let today = collectPicksForDate(histories, todayHit, nameBySlug)
      const trackDrafts = trackResult.outcomes.map((o) => ({
        rank: 0,
        code: o.code,
        name: o.name || o.code,
        date: o.base_date,
        strategy: o.strategy_slug || o.rule_version || '',
        // 中文名兜底一处收口：接口名 → 词表/拼音词根 → 「自定义战法」，绝不漏 slug
        strategyName: strategyDisplayName(o.strategy_slug || o.rule_version, nameBySlug),
        entryPrice: o.base_close,
        latestPrice: null as number | null,
        changePct: null as number | null,
        swingPct: o.swing_pct ?? null,
        t1: horizonReturn(o.returns, 1),
        t3: horizonReturn(o.returns, 3),
        score: o.score ?? null,
      }))
      let track: PulseTrackRow[] = excludeTodayFromTrack(
        dedupeTrackRowsByDayCode(trackDrafts).map(({ score: _score, ...row }) => row),
        calendarToday,
      )

      pickPctMode.value = 'none'
      const codes = [...new Set([...track, ...today].map((r) => r.code))].slice(0, 80)
      if (codes.length) {
        try {
          const spotMap = await resolveSpotMap(codes, generation, true)
          if (!isCurrent(generation)) return
          track = track.map((r) => {
            const spot = spotMap.get(r.code)
            const latest = boardLatestPrice(spot)
            const name = spot?.name || r.name
            const liveSwing =
              r.swingPct == null && spot
                ? swingFromLowHigh(spot.low, spot.high)
                : null
            return {
              ...r,
              name,
              latestPrice: latest,
              changePct: changeFromEntry(r.entryPrice, latest),
              swingPct: r.swingPct ?? liveSwing,
            }
          })
          today = today.map((r) => {
            const spot = spotMap.get(r.code)
            return {
              ...r,
              pct: spot ? effectivePct(spot) : r.pct,
              name: spot?.name || r.name,
            }
          })
        } catch {
          /* 叠价失败仍展示名单 */
        }
      }

      track.sort((a, b) => {
        if (a.date !== b.date) return a.date < b.date ? 1 : -1
        return (b.changePct ?? -999) - (a.changePct ?? -999)
      })
      today.sort((a, b) => {
        if (a.score != null && b.score != null && b.score !== a.score) return b.score - a.score
        return (b.pct ?? -999) - (a.pct ?? -999)
      })
      if (!isCurrent(generation)) return
      trackRows.value = track.slice(0, 40).map((r, i) => ({ ...r, rank: i + 1 }))
      todayRows.value = today.slice(0, 20).map((r, i) => ({ ...r, rank: i + 1 }))
      const datesInTrack = [...new Set(trackRows.value.map((r) => r.date))].sort()
      trackNote.value = datesInTrack.length
        ? `${datesInTrack[0]}～${datesInTrack[datesInTrack.length - 1]} · ${TRACK_WINDOW_DAYS} 个交易日`
        : `近 ${TRACK_WINDOW_DAYS} 个交易日暂无精选`
    } catch (caught: unknown) {
      if (!isCurrent(generation)) return
      historyError.value = ''
      trackRows.value = []
      todayRows.value = []
      todayDate.value = ''
      trackNote.value = ''
      screenHistoryTotal.value = null
      error.value = toErrorMessage(caught, '选股记录加载失败')
    }
  }

  async function reload(): Promise<void> {
    const generation = ++dataGeneration
    boardRequestSeq += 1
    loading.value = true
    error.value = ''
    tapeError.value = ''
    historyError.value = ''
    alertsError.value = ''
    try {
      const [sess, alerts] = await Promise.all([
        getMarketSession().catch(() => null),
        // 触价提醒失败不能吞成空列表：那样「接口挂了」和「今天没触价」在
        // 界面上完全一样，止损提醒会无声消失。
        getTodayAlerts().catch((caught: unknown) => {
          alertsError.value = toErrorMessage(caught, '触价提醒加载失败')
          return null
        }),
      ])
      if (!isCurrent(generation)) return
      session.value = sess
      alertCount.value = alerts?.length ?? 0
      // 指数/榜先出，整页遮罩随即撤掉；选股表较慢，不挡已渲染内容。
      await Promise.all([refreshTape(generation), loadBoard(generation)])
      if (!isCurrent(generation)) return
      loading.value = false
      await loadScreenTables(generation)
    } catch (caught: unknown) {
      if (!isCurrent(generation)) return
      error.value = toErrorMessage(caught, '盘面加载失败')
    } finally {
      if (isCurrent(generation)) loading.value = false
    }
  }

  async function setBoardTab(tab: PulseBoardTab): Promise<void> {
    boardTab.value = tab
    await loadBoard(dataGeneration)
  }

  /** 显式落盘盘中 spot（与轮询 persist:false 解耦；需写鉴权）。 */
  async function persistSpot(): Promise<void> {
    if (spotPersistBusy.value) return
    spotPersistBusy.value = true
    try {
      const codes = boardRows.value.map((r) => r.code).filter(Boolean).slice(0, 80)
      const result = await persistMarketBoardSpot(codes.length ? { codes } : {})
      ElMessage.success(`现价已落盘 ${result.written} 只`)
      await loadBoard(dataGeneration)
    } catch (caught: unknown) {
      ElMessage.error(toErrorMessage(caught, '现价落盘失败'))
    } finally {
      spotPersistBusy.value = false
    }
  }

  useLivePolling({
    intervalMs: 8000,
    tick: async () => {
      const generation = dataGeneration
      livePollTick += 1
      // 指数/仓 tape 每 tick；市场榜隔 tick（≈16s）；叠价同 tick 复用榜内行，仅补缺失 code
      const refreshBoard = livePollTick % 2 === 0

      await refreshTape(generation)
      if (!isCurrent(generation)) return

      if (refreshBoard) {
        await loadBoard(generation)
        if (!isCurrent(generation)) return
      }

      if (!(trackRows.value.length || todayRows.value.length)) return
      const codes = [
        ...new Set([...trackRows.value, ...todayRows.value].map((r) => r.code)),
      ].slice(0, 80)
      if (!codes.length) return
      try {
        const spotMap = await resolveSpotMap(codes, generation, true)
        if (!isCurrent(generation)) return
        applySpotOverlay(spotMap)
      } catch {
        /* ignore */
      }
    },
  })

  function bumpDataGeneration(): void {
    // KeepAlive 离页也作废 in-flight，避免回写过期 tape/board
    dataGeneration += 1
    boardRequestSeq += 1
  }

  onDeactivated(bumpDataGeneration)
  onBeforeUnmount(bumpDataGeneration)

  onMounted(() => {
    void reload()
  })

  return {
    loading,
    spotPersistBusy,
    error,
    session,
    indices,
    alertCount,
    sessionText,
    asOfText,
    tapeError,
    historyError,
    alertsError,
    trackRows,
    todayRows,
    trackNote,
    todayDate,
    screenHistoryTotal,
    boardTab,
    boardRows,
    sectorRows,
    boardNote,
    boardAsOf,
    pickPctMode,
    reload,
    persistSpot,
    setBoardTab,
    effectivePct,
  }
}

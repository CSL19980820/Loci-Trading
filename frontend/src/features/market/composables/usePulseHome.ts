/**
 * 首页盘面数据：指数/仓摘要、近选跟踪（T～T+4）、市场榜、今日选股。
 * 数字以后端与 live 叠价为准；无数据诚实空态，不掺演示票。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { getTodayAlerts } from '@/shared/api/palace'
import {
  getCandidateOutcomes,
  getLiveTape,
  getMarketBoard,
  getMarketSession,
  getScreenHistory,
  getStrategies,
  type LiveTape,
  type LiveTapeItem,
} from '@/shared/api/quant'
import { useLivePolling } from '@/shared/composables/useLivePolling'
import { toErrorMessage } from '@/shared/lib/errors'
import type { MarketSession } from '@/shared/lib/marketSession'
import type { BoardRow, ScreenCandidate, StrategyInfo } from '@/shared/types/quant'

import {
  changeFromEntry,
  dedupeTrackRowsByDayCode,
  effectivePct,
  horizonReturn,
  localIsoDate,
  rankBoardRows,
  splitScreenDates,
  type PulseBoardTab,
} from './pulseHomeLogic'

export type { PulseBoardTab }

export type PulsePickRow = {
  rank: number
  code: string
  name: string
  strategy: string
  strategyName: string
  score: number | null
  reason: string
  pct: number | null
  date: string
}

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
  t1: number | null
  t3: number | null
}

export type PickPctMode = 'live' | 'local' | 'none'

export { effectivePct }

const TRACK_WINDOW_DAYS = 5

function bagPctFromPositions(positions: LiveTapeItem[]): number | null {
  const rows = positions.filter((p) => p.ok && p.pct != null)
  if (!rows.length) return null
  let weighted = 0
  let weight = 0
  for (const p of rows) {
    const pct = Number(p.pct)
    const mv =
      p.market_value ??
      (p.price != null && p.shares ? Number(p.price) * Number(p.shares) : 0)
    if (mv > 0) {
      weighted += pct * mv
      weight += mv
    }
  }
  if (weight > 0) return weighted / weight
  return rows.reduce((s, p) => s + Number(p.pct), 0) / rows.length
}

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
  const error = ref('')
  const session = ref<MarketSession | null>(null)
  const tape = ref<LiveTape | null>(null)
  const strategies = ref<StrategyInfo[]>([])
  const trackRows = ref<PulseTrackRow[]>([])
  const todayRows = ref<PulsePickRow[]>([])
  const trackNote = ref('')
  const todayDate = ref('')
  const boardTab = ref<PulseBoardTab>('gain')
  const boardRows = ref<BoardRow[]>([])
  const boardNote = ref('')
  const pickPctMode = ref<PickPctMode>('none')
  const alertCount = ref(0)
  const clock = ref('')
  const tapeError = ref('')
  const historyError = ref('')
  let dataGeneration = 0
  let boardRequestSeq = 0

  function isCurrent(generation: number): boolean {
    return generation === dataGeneration
  }

  function liveRequestAllowed(): boolean {
    return session.value != null && Boolean(session.value.live_allowed)
  }

  const indices = computed(() => tape.value?.indices ?? [])
  const bagPct = computed(() => bagPctFromPositions(tape.value?.positions ?? []))
  const positionCount = computed(
    () => (tape.value?.positions ?? []).filter((p) => p.code).length,
  )
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
      tab === 'gain' ? 'pct_desc' : tab === 'loss' ? 'pct_asc' : 'turnover_desc'
    const liveAllowed = liveRequestAllowed()
    try {
      const board = await getMarketBoard({
        live: liveAllowed,
        page: 1,
        page_size: 40,
        sort,
        instrument_type: 'STOCK',
        status: 'normal',
      })
      if (!isCurrent(generation) || requestSeq !== boardRequestSeq) return
      boardRows.value = rankBoardRows(board.items, tab)
      boardNote.value = board.live_error
        ? `实时降级：${board.live_error}`
        : board.as_of
          ? `截至 ${board.as_of}`
          : ''
    } catch (caught: unknown) {
      if (!isCurrent(generation) || requestSeq !== boardRequestSeq) return
      boardRows.value = []
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
      page_size: Math.max(10, codes.length),
      instrument_type: 'all',
    })
    if (!isCurrent(generation)) return new Map()
    pickPctMode.value = live ? 'live' : 'local'
    return new Map(spot.items.map((item) => [item.code, item] as const))
  }

  async function loadScreenTables(generation = dataGeneration): Promise<void> {
    try {
      const list = await getStrategies()
      if (!isCurrent(generation)) return
      strategies.value = list
      const nameBySlug = new Map(list.map((s) => [s.slug, s.name]))

      const calendarToday = session.value?.today || localIsoDate()
      const sessionDay =
        session.value?.last_trading_day ||
        session.value?.coverage_last_date ||
        calendarToday

      const [trackResult, historyResults] = await Promise.all([
        getCandidateOutcomes(400, {
          window_days: TRACK_WINDOW_DAYS,
          selected_only: true,
          as_of: sessionDay,
        })
          .then((payload) => ({ outcomes: payload.outcomes, failed: false }))
          .catch(() => ({ outcomes: [], failed: true })),
        Promise.all(
          list.map((s) =>
            getScreenHistory({ strategy: s.slug, limit: 80, live_only: true })
              .then((history) => ({ history, failed: false, label: '' }))
              .catch(() => ({
                history: {
                  strategy: s.slug,
                  total: 0,
                  dates: [] as string[],
                  by_date: {} as Record<string, ScreenCandidate[]>,
                },
                failed: true,
                label: s.name || s.slug,
              })),
          ),
        ),
      ])
      if (!isCurrent(generation)) return

      const failedStrategies = historyResults
        .filter((result) => result.failed)
        .map((result) => result.label)
      const parts: string[] = []
      if (trackResult.failed) parts.push('近选跟踪')
      if (failedStrategies.length) {
        parts.push(`策略：${failedStrategies.join('、')}`)
      }
      historyError.value = parts.length ? `部分数据加载失败：${parts.join('；')}` : ''

      const histories = historyResults.map((result) => result.history)
      const dateSet = new Set<string>()
      for (const h of histories) {
        for (const d of h.dates) dateSet.add(d)
      }
      const dates = [...dateSet].sort((a, b) => (a < b ? 1 : a > b ? -1 : 0))
      const { todayHit } = splitScreenDates(dates, calendarToday, sessionDay)
      todayDate.value = todayHit

      function collectToday(date: string): PulsePickRow[] {
        if (!date) return []
        const merged: PulsePickRow[] = []
        for (const h of histories) {
          for (const row of h.by_date[date] || []) {
            if (!row.code) continue
            merged.push({
              rank: 0,
              code: row.code,
              name: row.name || row.code,
              strategy: h.strategy,
              strategyName: nameBySlug.get(h.strategy) || h.strategy,
              score: row.score,
              reason: row.reason || '',
              pct: null,
              date,
            })
          }
        }
        const dedup = new Map<string, PulsePickRow>()
        for (const row of merged) {
          const prev = dedup.get(row.code)
          if (!prev || (row.score ?? -1) > (prev.score ?? -1)) dedup.set(row.code, row)
        }
        return [...dedup.values()]
      }

      let today = collectToday(todayHit)
      const trackDrafts = trackResult.outcomes.map((o) => ({
        rank: 0,
        code: o.code,
        name: o.name || o.code,
        date: o.base_date,
        strategy: o.strategy_slug || o.rule_version || '',
        strategyName:
          nameBySlug.get(o.strategy_slug || '') ||
          o.strategy_slug ||
          o.rule_version ||
          '—',
        entryPrice: o.base_close,
        latestPrice: null as number | null,
        changePct: null as number | null,
        t1: horizonReturn(o.returns, 1),
        t3: horizonReturn(o.returns, 3),
        score: o.score ?? null,
      }))
      let track: PulseTrackRow[] = dedupeTrackRowsByDayCode(trackDrafts).map(
        ({ score: _score, ...row }) => row,
      )

      pickPctMode.value = 'none'
      const codes = [...new Set([...track, ...today].map((r) => r.code))].slice(0, 80)
      if (codes.length) {
        try {
          const spotMap = await overlaySpot(codes, generation)
          if (!isCurrent(generation)) return
          track = track.map((r) => {
            const spot = spotMap.get(r.code)
            const latest = boardLatestPrice(spot)
            const name = spot?.name || r.name
            return {
              ...r,
              name,
              latestPrice: latest,
              changePct: changeFromEntry(r.entryPrice, latest),
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
    try {
      const [sess, alerts] = await Promise.all([
        getMarketSession().catch(() => null),
        getTodayAlerts().catch(() => []),
      ])
      if (!isCurrent(generation)) return
      session.value = sess
      alertCount.value = alerts.length
      await Promise.all([
        refreshTape(generation),
        loadBoard(generation),
        loadScreenTables(generation),
      ])
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

  useLivePolling({
    intervalMs: 8000,
    tick: async () => {
      const generation = dataGeneration
      await Promise.all([refreshTape(generation), loadBoard(generation)])
      if (!isCurrent(generation)) return
      if (!(trackRows.value.length || todayRows.value.length)) return
      const codes = [
        ...new Set([...trackRows.value, ...todayRows.value].map((r) => r.code)),
      ].slice(0, 80)
      if (!codes.length) return
      try {
        const spotMap = await overlaySpot(codes, generation)
        if (!isCurrent(generation)) return
        trackRows.value = [...trackRows.value]
          .map((r) => {
            const spot = spotMap.get(r.code)
            const latest = boardLatestPrice(spot) ?? r.latestPrice
            return {
              ...r,
              latestPrice: latest,
              changePct: changeFromEntry(r.entryPrice, latest),
            }
          })
          .sort((a, b) => {
            if (a.date !== b.date) return a.date < b.date ? 1 : -1
            return (b.changePct ?? -999) - (a.changePct ?? -999)
          })
          .map((r, i) => ({ ...r, rank: i + 1 }))
        todayRows.value = todayRows.value.map((r) => {
          const spot = spotMap.get(r.code)
          return {
            ...r,
            pct: spot ? effectivePct(spot) : r.pct,
          }
        })
      } catch {
        /* ignore */
      }
    },
  })

  onBeforeUnmount(() => {
    dataGeneration += 1
    boardRequestSeq += 1
  })

  onMounted(() => {
    void reload()
  })

  return {
    loading,
    error,
    session,
    indices,
    bagPct,
    positionCount,
    alertCount,
    sessionText,
    asOfText,
    tapeError,
    historyError,
    trackRows,
    todayRows,
    trackNote,
    todayDate,
    boardTab,
    boardRows,
    boardNote,
    pickPctMode,
    reload,
    setBoardTab,
    effectivePct,
  }
}

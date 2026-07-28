import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'

import { getMarketBoard, getMarketSession } from '@/shared/api/quant'
import { isAshareLiveWindow } from '@/shared/lib/marketSession'
import type { IndicatorKind } from '@/shared/components/charts/KlineChart.vue'
import type { KPeriod } from '@/shared/lib/indicators'
import type { BoardRow } from '@/shared/types/quant'

import { useQuotesQuery } from './useQuotesQuery'

type Adjust = 'qfq' | 'hfq' | 'none'
type DeskTab = 'market' | 'trades' | 'candidates'

export function useDataQueryMarket(opts: {
  route: RouteLocationNormalizedLoaded
  router: Router
  tab: { value: DeskTab }
  busy: { value: boolean }
  error: { value: string }
  liveError: { value: string }
}) {
  const marketQ = ref('')
  /** 勾选后：盘中后台叠实时并尝试入库；非 live 窗口不自动轮询 */
  const liveOn = ref(isAshareLiveWindow())
  const page = ref(1)
  const pageSize = ref(50)
  const boardRows = ref<BoardRow[]>([])
  const boardTotal = ref(0)
  const boardAsOf = ref('')
  const liveEnriching = ref(false)

  const detailCode = ref('')
  const detailName = ref('')
  const adjust = ref<Adjust>('qfq')
  const period = ref<KPeriod>('day')
  const indicator = ref<IndicatorKind>('macd')

  const { quote: quoteCached, refetch: refetchQuotes } = useQuotesQuery(detailCode, () => ({
    adjust: adjust.value,
    limit: 800,
  }))

  /** Colada 试点：有详情代码才暴露缓存结果 */
  const quote = computed(() => (detailCode.value ? quoteCached.value : null))

  let refreshTimer: ReturnType<typeof setInterval> | null = null
  let sessionTimer: ReturnType<typeof setInterval> | null = null
  let sessionLiveAllowed: boolean | null = null
  let enrichSeq = 0

  async function refreshSessionGate(): Promise<boolean> {
    try {
      const s = await getMarketSession()
      sessionLiveAllowed = Boolean(s.live_allowed)
    } catch {
      sessionLiveAllowed = isAshareLiveWindow()
    }
    return sessionLiveAllowed
  }

  function livePollAllowed(): boolean {
    if (sessionLiveAllowed != null) return sessionLiveAllowed
    return isAshareLiveWindow()
  }

  function stopSessionTimer(): void {
    if (sessionTimer) {
      clearInterval(sessionTimer)
      sessionTimer = null
    }
  }

  function startSessionTimer(): void {
    stopSessionTimer()
    sessionTimer = setInterval(() => {
      void refreshSessionGate().then((allowed) => {
        if (!allowed) stopRefresh()
      })
    }, 60_000)
  }

  const adjustLabel = computed(() =>
    ({ qfq: '前复权', hfq: '后复权', none: '不复权' })[adjust.value],
  )

  const lastClose = computed(() => {
    const bars = quote.value?.bars
    if (!bars?.length) return '—'
    const c = bars[bars.length - 1]?.close
    return c == null ? '—' : Number(c).toFixed(2)
  })

  const detailPct = computed(() => {
    const bars = quote.value?.bars
    if (!bars || bars.length < 2) return null
    const a = Number(bars[bars.length - 2]?.close)
    const b = Number(bars[bars.length - 1]?.close)
    if (!a || Number.isNaN(a) || Number.isNaN(b)) return null
    return ((b - a) / a) * 100
  })

  function stopRefresh(): void {
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
    stopSessionTimer()
  }

  function startRefresh(): void {
    stopRefresh()
    if (!liveOn.value || detailCode.value || opts.tab.value !== 'market') return
    void refreshSessionGate().then((allowed) => {
      if (!allowed) return
      refreshTimer = setInterval(() => {
        if (document.hidden) return
        if (!livePollAllowed()) {
          void refreshSessionGate().then((stillAllowed) => {
            if (!stillAllowed) stopRefresh()
          })
          return
        }
        void enrichLiveBoard()
      }, 12_000)
      startSessionTimer()
    })
  }

  /** 只读本机库，列表立刻出来 */
  async function loadBoard(): Promise<void> {
    if (detailCode.value) return
    opts.busy.value = true
    opts.error.value = ''
    try {
      const board = await getMarketBoard({
        q: marketQ.value.trim(),
        page: page.value,
        page_size: pageSize.value,
        live: false,
      })
      boardRows.value = board.items
      boardTotal.value = board.total
      boardAsOf.value = board.as_of?.slice(11, 19) || ''
      opts.liveError.value = ''
    } catch (caught: unknown) {
      opts.error.value = (caught as Error).message || '加载行情列表失败'
    } finally {
      opts.busy.value = false
    }
    if (liveOn.value) {
      void refreshSessionGate().then((allowed) => {
        if (allowed) {
          void enrichLiveBoard()
          startRefresh()
        } else {
          stopRefresh()
        }
      })
    } else {
      stopRefresh()
    }
  }

  /** 后台叠当前页实时（不挡 busy），服务端会异步写入当日 bar */
  async function enrichLiveBoard(): Promise<void> {
    if (detailCode.value || opts.tab.value !== 'market') return
    if (!liveOn.value || !livePollAllowed()) return
    const seq = ++enrichSeq
    liveEnriching.value = true
    try {
      const board = await getMarketBoard({
        q: marketQ.value.trim(),
        page: page.value,
        page_size: pageSize.value,
        live: true,
      })
      if (seq !== enrichSeq || detailCode.value) return
      boardRows.value = board.items
      boardTotal.value = board.total
      boardAsOf.value = board.as_of?.slice(11, 19) || ''
      opts.liveError.value = board.live_error || ''
    } catch (caught: unknown) {
      if (seq !== enrichSeq) return
      opts.liveError.value = (caught as Error).message || '实时刷新失败'
    } finally {
      if (seq === enrichSeq) liveEnriching.value = false
    }
  }

  function onSearch(): void {
    page.value = 1
    void loadBoard()
  }

  function onPageSizeChange(): void {
    page.value = 1
    void loadBoard()
  }

  async function openDetail(row: BoardRow): Promise<void> {
    detailCode.value = row.code
    detailName.value = row.name || row.code
    stopRefresh()
    await opts.router.replace({ query: { ...opts.route.query, code: row.code } })
    await loadDetail()
  }

  function closeDetail(): void {
    detailCode.value = ''
    detailName.value = ''
    const next = { ...opts.route.query }
    delete next.code
    void opts.router.replace({ query: next })
    void loadBoard()
  }

  async function loadDetail(): Promise<void> {
    if (!detailCode.value) return
    stopRefresh()
    opts.busy.value = true
    opts.error.value = ''
    try {
      await refetchQuotes()
      if (quoteCached.value?.name) detailName.value = quoteCached.value.name
    } catch (caught: unknown) {
      opts.error.value = (caught as Error).message || '加载日线失败'
    } finally {
      opts.busy.value = false
    }
  }

  watch(liveOn, (on) => {
    if (detailCode.value) return
    if (on) {
      void refreshSessionGate().then((allowed) => {
        if (allowed) {
          void enrichLiveBoard()
          startRefresh()
        } else {
          stopRefresh()
        }
      })
    } else {
      stopRefresh()
      void loadBoard()
    }
  })

  onBeforeUnmount(() => stopRefresh())

  return {
    marketQ,
    liveOn,
    liveEnriching,
    page,
    pageSize,
    boardRows,
    boardTotal,
    boardAsOf,
    detailCode,
    detailName,
    quote,
    adjust,
    period,
    indicator,
    adjustLabel,
    lastClose,
    detailPct,
    loadBoard,
    onSearch,
    onPageSizeChange,
    openDetail,
    closeDetail,
    loadDetail,
    startRefresh,
    stopRefresh,
  }
}

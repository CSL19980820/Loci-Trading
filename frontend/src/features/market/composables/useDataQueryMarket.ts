import { onBeforeUnmount, ref, watch } from 'vue'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'

import { getMarketBoard, getMarketSession } from '@/shared/api/quant'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { useBatchBrowseStore } from '@/shared/stores/batchBrowse'
import type { BoardRow } from '@/shared/types/quant'

export type BoardSort = 'code' | 'turnover_desc' | 'turnover_asc'

export function useDataQueryMarket(opts: {
  route: RouteLocationNormalizedLoaded
  router: Router
  busy: { value: boolean }
  error: { value: string }
  liveError: { value: string }
}) {
  const marketQ = ref('')
  /** 行情台默认叠实时；盘中自动轮询，非 live 窗口不强拉 */
  const liveOn = ref(true)
  const industryFilter = ref('')
  const turnoverMin = ref<number | null>(null)
  const boardSort = ref<BoardSort>('code')
  const page = ref(1)
  const pageSize = ref(50)
  const boardRows = ref<BoardRow[]>([])
  const boardTotal = ref(0)
  const boardAsOf = ref('')
  const liveEnriching = ref(false)

  let refreshTimer: ReturnType<typeof setInterval> | null = null
  let sessionTimer: ReturnType<typeof setInterval> | null = null
  let sessionLiveAllowed: boolean | null = null
  let boardRequestSeq = 0
  let refreshGeneration = 0
  let sessionRequestSeq = 0
  let liveRequestInFlight = false

  function boardQueryOpts(live: boolean) {
    return {
      q: marketQ.value.trim(),
      page: page.value,
      page_size: pageSize.value,
      live,
      industry: industryFilter.value || undefined,
      sort: boardSort.value,
      turnover_min: turnoverMin.value ?? undefined,
    }
  }

  async function refreshSessionGate(): Promise<boolean> {
    const requestSeq = ++sessionRequestSeq
    try {
      const s = await getMarketSession()
      if (requestSeq !== sessionRequestSeq) {
        return sessionLiveAllowed ?? false
      }
      sessionLiveAllowed = Boolean(s.live_allowed)
    } catch {
      if (requestSeq !== sessionRequestSeq) {
        return sessionLiveAllowed ?? false
      }
      sessionLiveAllowed = false
    }
    return sessionLiveAllowed
  }

  function livePollAllowed(): boolean {
    if (sessionLiveAllowed != null) return sessionLiveAllowed
    return false
  }

  function stopSessionTimer(): void {
    if (sessionTimer) {
      clearInterval(sessionTimer)
      sessionTimer = null
    }
  }

  function startSessionTimer(): void {
    stopSessionTimer()
    const generation = refreshGeneration
    sessionTimer = setInterval(() => {
      void refreshSessionGate().then((allowed) => {
        if (generation !== refreshGeneration) return
        if (!allowed) stopRefresh()
      })
    }, 60_000)
  }

  function stopRefresh(): void {
    refreshGeneration += 1
    // 关闭实时后，已发出的 live 请求不能再覆盖本地列表。
    boardRequestSeq += 1
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
    stopSessionTimer()
  }

  function startRefresh(): void {
    stopRefresh()
    if (!liveOn.value) return
    const generation = refreshGeneration
    void refreshSessionGate().then((allowed) => {
      if (generation !== refreshGeneration || !liveOn.value || !allowed) return
      refreshTimer = setInterval(() => {
        if (document.hidden) return
        if (!livePollAllowed()) {
          void refreshSessionGate().then((stillAllowed) => {
            if (generation !== refreshGeneration) return
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
    const seq = ++boardRequestSeq
    liveEnriching.value = false
    opts.busy.value = true
    opts.error.value = ''
    try {
      const board = await getMarketBoard(boardQueryOpts(false))
      if (seq !== boardRequestSeq) return
      boardRows.value = board.items
      boardTotal.value = board.total
      boardAsOf.value = board.as_of?.slice(11, 19) || ''
      opts.liveError.value = ''
    } catch (caught: unknown) {
      if (seq !== boardRequestSeq) return
      opts.error.value = (caught as Error).message || '加载行情列表失败'
    } finally {
      if (seq === boardRequestSeq) opts.busy.value = false
    }
    if (liveOn.value) {
      const generation = refreshGeneration
      void refreshSessionGate().then((allowed) => {
        if (seq !== boardRequestSeq || generation !== refreshGeneration) return
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
    if (!liveOn.value || !livePollAllowed() || liveRequestInFlight) return
    liveRequestInFlight = true
    const seq = ++boardRequestSeq
    liveEnriching.value = true
    try {
      const board = await getMarketBoard(boardQueryOpts(true))
      if (seq !== boardRequestSeq) return
      boardRows.value = board.items
      boardTotal.value = board.total
      boardAsOf.value = board.as_of?.slice(11, 19) || ''
      opts.liveError.value = board.live_error || ''
    } catch (caught: unknown) {
      if (seq !== boardRequestSeq) return
      opts.liveError.value = (caught as Error).message || '实时刷新失败'
    } finally {
      liveRequestInFlight = false
      if (seq === boardRequestSeq) liveEnriching.value = false
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

  /** 点行进档案页详情（含批量浏览），详情主场在 ArchiveView */
  async function openDetail(row: BoardRow): Promise<void> {
    const batch = useBatchBrowseStore()
    batch.openBatch({
      source: '行情台',
      sourcePath: opts.route.fullPath || '/data',
      focusCode: row.code,
      items: toBatchItems(
        boardRows.value.map((item) => ({
          code: item.code,
          name: item.name,
          pct: item.pct ?? item.local_pct ?? null,
        })),
      ),
    })
    await opts.router.push({
      path: `/archive/${row.code}`,
      query: { view: 'quote' },
    })
  }

  watch(liveOn, (on) => {
    if (on) {
      const generation = refreshGeneration
      void refreshSessionGate().then((allowed) => {
        if (generation !== refreshGeneration || !liveOn.value) return
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
    industryFilter,
    turnoverMin,
    boardSort,
    liveEnriching,
    page,
    pageSize,
    boardRows,
    boardTotal,
    boardAsOf,
    loadBoard,
    onSearch,
    onPageSizeChange,
    openDetail,
    startRefresh,
    stopRefresh,
  }
}

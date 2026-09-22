import { onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'

import { getMarketBoard, getMarketSession } from '@/shared/api/quant'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { useBatchBrowseStore } from '@/shared/stores/batchBrowse'
import type { BoardRow } from '@/shared/types/quant'

export type BoardSort = 'code' | 'turnover_desc' | 'turnover_asc'

/** 行情台的公开契约：视图与测试都对着这个名字写，别去反推 useDataQueryMarket 的返回值。 */
export interface DataQueryMarket {
  marketQ: Ref<string>
  liveOn: Ref<boolean>
  industryFilter: Ref<string>
  turnoverMin: Ref<number | null>
  boardSort: Ref<BoardSort>
  liveEnriching: Ref<boolean>
  page: Ref<number>
  pageSize: Ref<number>
  boardRows: Ref<BoardRow[]>
  boardTotal: Ref<number>
  loadBoard: () => Promise<void>
  onSearch: () => void
  onPageSizeChange: () => void
  openDetail: (row: BoardRow) => Promise<void>
  /** `knownAllowed` 见实现处注释：复用调用方刚探到的 session 结果 */
  startRefresh: (knownAllowed?: boolean) => void
  stopRefresh: () => void
}

export function useDataQueryMarket(opts: {
  route: RouteLocationNormalizedLoaded
  router: Router
  busy: { value: boolean }
  error: { value: string }
  liveError: { value: string }
}): DataQueryMarket {
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
  const liveEnriching = ref(false)

  let refreshTimer: ReturnType<typeof setInterval> | null = null
  let sessionTimer: ReturnType<typeof setInterval> | null = null
  let sessionLiveAllowed: boolean | null = null
  /** 本机列表请求世代：翻页/搜索互相作废；与实时世代分离，避免 stopRefresh 卡死 busy */
  let listRequestSeq = 0
  /** 实时叠价请求世代：停表/离页只抬这个，不碰列表 busy */
  let liveRequestSeq = 0
  let listLoadsInFlight = 0
  let refreshGeneration = 0
  let sessionRequestSeq = 0
  let liveRequestInFlight = false

  function boardQueryOpts(live: boolean) {
    return {
      q: marketQ.value.trim(),
      page: page.value,
      page_size: pageSize.value,
      live,
      persist: false,
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
    // 只作废实时叠价；勿抬 listRequestSeq，否则 KeepAlive onActivated→startRefresh
    // 与首屏 loadBoard 竞态时 finally 清不掉 busy，页面永久转圈。
    liveRequestSeq += 1
    liveRequestInFlight = false
    liveEnriching.value = false
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
    stopSessionTimer()
  }

  /**
   * `knownAllowed` 让刚探测过 session 的调用方直接复用结果，省掉背靠背的第二发
   * GET /market/session；离页回来（onActivated）不传，那时确实该重新探测。
   */
  function startRefresh(knownAllowed?: boolean): void {
    stopRefresh()
    if (!liveOn.value) return
    const generation = refreshGeneration
    const gate =
      knownAllowed === undefined ? refreshSessionGate() : Promise.resolve(knownAllowed)
    void gate.then((allowed) => {
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
    const seq = ++listRequestSeq
    // 新列表查询作废进行中的实时叠价，避免旧 live 盖住新页。
    liveRequestSeq += 1
    liveRequestInFlight = false
    liveEnriching.value = false
    listLoadsInFlight += 1
    opts.busy.value = true
    opts.error.value = ''
    try {
      const board = await getMarketBoard(boardQueryOpts(false))
      if (seq !== listRequestSeq) return
      boardRows.value = board.items
      boardTotal.value = board.total
      opts.liveError.value = ''
    } catch (caught: unknown) {
      if (seq !== listRequestSeq) return
      opts.error.value = (caught as Error).message || '加载行情列表失败'
    } finally {
      listLoadsInFlight = Math.max(0, listLoadsInFlight - 1)
      if (listLoadsInFlight === 0) opts.busy.value = false
    }
    if (liveOn.value) {
      const generation = refreshGeneration
      void refreshSessionGate().then((allowed) => {
        if (seq !== listRequestSeq || generation !== refreshGeneration) return
        if (allowed) {
          // 先建轮询（内部 stopRefresh 只作废旧 live），再立即叠一次现价。
          startRefresh(allowed)
          void enrichLiveBoard()
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
    if (!liveOn.value || !livePollAllowed() || liveRequestInFlight || listLoadsInFlight > 0) {
      return
    }
    liveRequestInFlight = true
    const seq = ++liveRequestSeq
    liveEnriching.value = true
    try {
      const board = await getMarketBoard(boardQueryOpts(true))
      if (seq !== liveRequestSeq) return
      boardRows.value = board.items
      boardTotal.value = board.total
      opts.liveError.value = board.live_error || ''
    } catch (caught: unknown) {
      if (seq !== liveRequestSeq) return
      opts.liveError.value = (caught as Error).message || '实时刷新失败'
    } finally {
      if (seq === liveRequestSeq) {
        liveRequestInFlight = false
        liveEnriching.value = false
      }
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
          startRefresh(allowed)
          void enrichLiveBoard()
        } else {
          stopRefresh()
        }
      })
    } else {
      stopRefresh()
      void loadBoard()
    }
  })

  onDeactivated(() => stopRefresh())
  onActivated(() => {
    if (liveOn.value) startRefresh()
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
    loadBoard,
    onSearch,
    onPageSizeChange,
    openDetail,
    startRefresh,
    stopRefresh,
  }
}

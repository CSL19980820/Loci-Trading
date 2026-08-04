import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

import {
  createTrade,
  getAnalytics,
  getDashboard,
  getPoolDay,
  getPools,
  getReviews,
  getTimeline,
  getTrades,
} from '@/shared/api/palace'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  Analytics,
  Dashboard,
  PoolDay,
  PoolSummary,
  ReviewRecord,
  TimelineEvent,
  TradePayload,
  TradeRecord,
} from '@/shared/types/palace'

/** 并行读接口：单路失败不拖垮整页；成功结果才写入。 */
async function settleValue<T>(promise: Promise<T>): Promise<{ ok: true; value: T } | { ok: false; error: unknown }> {
  try {
    return { ok: true, value: await promise }
  } catch (error: unknown) {
    return { ok: false, error }
  }
}

function errorMessage(caught: unknown, fallback: string): string {
  return toErrorMessage(caught, fallback)
}

export const usePalaceStore = defineStore('palace', () => {
  const dashboard = ref<Dashboard | null>(null)
  const trades = ref<TradeRecord[]>([])
  const reviews = ref<ReviewRecord[]>([])
  const pools = ref<PoolSummary[]>([])
  const poolDay = ref<PoolDay | null>(null)
  const analytics = ref<Analytics | null>(null)
  const selectedTimeline = ref<TimelineEvent[]>([])
  const selectedCode = ref('')
  const selectedPoolDate = ref('')
  const selectedPoolId = ref('')
  const loading = ref(false)
  const error = ref('')
  const notice = ref('')

  let inFlight: Promise<void> | null = null
  let lastKey = ''
  let loadSeq = 0

  /** 个股工作台按 tab 缓存：同代码切回已加载切片不再打接口。 */
  let archiveCache = {
    code: '',
    trades: false,
    timeline: false,
    dashboard: false,
  }

  const hasData = computed(() => dashboard.value !== null)
  const firstPosition = computed(() => dashboard.value?.positions[0] ?? null)

  function resetArchiveCache(code = ''): void {
    archiveCache = { code, trades: false, timeline: false, dashboard: false }
  }

  function archiveViewOf(route: RouteLocationNormalizedLoaded): 'quote' | 'trades' | 'candidates' {
    const raw = String(route.query.view || 'quote')
    if (raw === 'trades' || raw === 'candidates') return raw
    return 'quote'
  }

  /** 按需拉取个股账本切片；force 仅用于写入后刷新。 */
  async function ensureArchiveSlice(
    code: string,
    parts: Array<'trades' | 'timeline' | 'dashboard'>,
    opts: { force?: boolean; isCurrent?: () => boolean } = {},
  ): Promise<string[]> {
    const normalized = code.trim()
    if (!normalized) return []
    const isCurrent = opts.isCurrent ?? (() => true)
    if (!isCurrent()) return []
    if (archiveCache.code !== normalized) {
      selectedCode.value = normalized
      selectedTimeline.value = []
      resetArchiveCache(normalized)
    }
    const canCommit = () => isCurrent() && archiveCache.code === normalized && selectedCode.value === normalized
    const force = opts.force === true
    const need = parts.filter((part) => force || !archiveCache[part])
    if (!need.length) return []

    const failures: string[] = []
    const tasks: Promise<void>[] = []

    if (need.includes('timeline')) {
      tasks.push(
        (async () => {
          const result = await settleValue(getTimeline(normalized))
          if (result.ok) {
            if (!canCommit()) return
            selectedTimeline.value = result.value
            archiveCache.timeline = true
          } else {
            failures.push(errorMessage(result.error, '时间线加载失败'))
          }
        })(),
      )
    }
    if (need.includes('trades')) {
      tasks.push(
        (async () => {
          const result = await settleValue(getTrades(normalized))
          if (result.ok) {
            if (!canCommit()) return
            const others = trades.value.filter((item) => item.code !== normalized)
            trades.value = [...result.value, ...others]
            archiveCache.trades = true
          } else {
            failures.push(errorMessage(result.error, '成交加载失败'))
          }
        })(),
      )
    }
    if (need.includes('dashboard')) {
      tasks.push(
        (async () => {
          const result = await settleValue(getDashboard())
          if (result.ok) {
            if (!canCommit()) return
            dashboard.value = result.value
            archiveCache.dashboard = true
          } else {
            failures.push(errorMessage(result.error, '持仓摘要加载失败'))
          }
        })(),
      )
    }

    await Promise.all(tasks)
    return failures
  }

  function invalidateArchive(code?: string): void {
    const next = (code ?? selectedCode.value).trim()
    resetArchiveCache(next)
    if (next && selectedCode.value === next) {
      selectedTimeline.value = []
    }
  }

  function archiveSlicesReady(route: RouteLocationNormalizedLoaded): boolean {
    const code = String(route.params.code ?? '').trim()
    if (!code || archiveCache.code !== code || selectedCode.value !== code) return false
    const view = archiveViewOf(route)
    if (view === 'quote') return true
    if (view === 'candidates') return archiveCache.timeline
    return archiveCache.trades && archiveCache.timeline && archiveCache.dashboard
  }

  /** 当前路由需要什么，就直接请求对应 API。没有本地账本缓存。 */
  async function loadRoute(route: RouteLocationNormalizedLoaded, force = false): Promise<void> {
    if (route.meta.public === true) return

    const archiveView = route.name === 'archive' ? archiveViewOf(route) : ''
    const key = `${String(route.name)}:${String(route.params.code ?? '')}:${archiveView}:${selectedPoolDate.value}:${selectedPoolId.value}`

    // 个股工作台：行情不拉账本；已加载的交割/候选切回不打接口、不闪顶栏进度条。
    // App 路由监听常带 force，不能靠 force 判定「必须重拉」。
    if (route.name === 'archive') {
      const code = String(route.params.code ?? '')
      if (archiveCache.code !== code || selectedCode.value !== code) {
        selectedCode.value = code
        selectedTimeline.value = []
        resetArchiveCache(code)
      }
      if (archiveView === 'quote' || archiveSlicesReady(route)) {
        lastKey = key
        return
      }
    }

    if (!force && inFlight && lastKey === key) return inFlight

    lastKey = key
    const seq = ++loadSeq
    loading.value = true
    error.value = ''

    const task = (async () => {
      const failures: string[] = []
      try {
        switch (route.name) {
          case 'ledger': {
            // 账本主数据必取；曲线/分布可降级，避免次要接口把整页打成 500 红条。
            const [dashResult, analyticsResult] = await Promise.all([
              settleValue(getDashboard()),
              settleValue(getAnalytics()),
            ])
            if (seq !== loadSeq) return
            if (dashResult.ok) dashboard.value = dashResult.value
            else failures.push(errorMessage(dashResult.error, '账本加载失败'))
            if (analyticsResult.ok) analytics.value = analyticsResult.value
            else if (!dashResult.ok) {
              // 主数据也挂了才上报；仅 analytics 失败时静默降级
              failures.push(errorMessage(analyticsResult.error, '统计加载失败'))
            }
            break
          }
          case 'journal': {
            const [tradesResult, dashResult] = await Promise.all([
              settleValue(getTrades()),
              settleValue(getDashboard()),
            ])
            if (seq !== loadSeq) return
            if (tradesResult.ok) trades.value = tradesResult.value
            else failures.push(errorMessage(tradesResult.error, '交割加载失败'))
            if (dashResult.ok) dashboard.value = dashResult.value
            else if (!tradesResult.ok) failures.push(errorMessage(dashResult.error, '账户加载失败'))
            break
          }
          case 'pool': {
            const poolsResult = await settleValue(getPools())
            if (seq !== loadSeq) return
            if (!poolsResult.ok) {
              failures.push(errorMessage(poolsResult.error, '候选池加载失败'))
              break
            }
            pools.value = poolsResult.value
            const preferred =
              poolsResult.value.find(
                (item) => item.date === selectedPoolDate.value && item.pool_id === selectedPoolId.value,
              ) ?? poolsResult.value[0]
            if (preferred) {
              selectedPoolDate.value = preferred.date
              selectedPoolId.value = preferred.pool_id
              const dayResult = await settleValue(getPoolDay(preferred.date, preferred.pool_id))
              if (seq !== loadSeq) return
              if (dayResult.ok) poolDay.value = dayResult.value
              else failures.push(errorMessage(dayResult.error, '当日候选加载失败'))
            } else {
              selectedPoolDate.value = ''
              selectedPoolId.value = ''
              const dayResult = await settleValue(getPoolDay())
              if (seq !== loadSeq) return
              if (dayResult.ok) poolDay.value = dayResult.value
              else failures.push(errorMessage(dayResult.error, '当日候选加载失败'))
            }
            if (!dashboard.value) {
              const dashResult = await settleValue(getDashboard())
              if (seq !== loadSeq) return
              if (dashResult.ok) dashboard.value = dashResult.value
            }
            break
          }
          case 'reviews':
            // 绩效中心自管 Colada 分区查询，不预拉账本 reviews/dashboard
            break
          case 'review-records': {
            const [reviewsResult, dashResult] = await Promise.all([
              settleValue(getReviews()),
              settleValue(getDashboard()),
            ])
            if (seq !== loadSeq) return
            if (reviewsResult.ok) reviews.value = reviewsResult.value
            else failures.push(errorMessage(reviewsResult.error, '复盘加载失败'))
            if (dashResult.ok) dashboard.value = dashResult.value
            else if (!reviewsResult.ok) failures.push(errorMessage(dashResult.error, '账户加载失败'))
            break
          }
          case 'archive': {
            const code = String(route.params.code ?? '')
            const view = archiveViewOf(route)
            if (archiveCache.code !== code || selectedCode.value !== code) {
              selectedCode.value = code
              selectedTimeline.value = []
              resetArchiveCache(code)
            }
            // 行情 tab 只看 market quotes，不预拉账本；交割/候选按需。
            if (view === 'quote') break
            if (view === 'candidates') {
              failures.push(...(await ensureArchiveSlice(code, ['timeline'], { isCurrent: () => seq === loadSeq })))
            } else {
              failures.push(
                ...(await ensureArchiveSlice(code, ['trades', 'timeline', 'dashboard'], { isCurrent: () => seq === loadSeq })),
              )
            }
            if (seq !== loadSeq) return
            break
          }
          default:
            // ops / quant / insights / data-query 等由页面自管，不预拉 dashboard
            break
        }
        if (seq === loadSeq) {
          // 已有可读数据时，刷新失败不再盖红条（避免偶发锁竞争刷屏）
          const softOk =
            (route.name === 'ledger' && dashboard.value) ||
            (route.name === 'pulse') ||
            (route.name === 'journal' && (trades.value.length > 0 || dashboard.value)) ||
            (route.name === 'pool' && pools.value.length > 0) ||
            (route.name === 'review-records' && (reviews.value.length > 0 || dashboard.value)) ||
            (route.name === 'reviews') ||
            (route.name === 'ops') ||
            (route.name === 'quant') ||
            (route.name === 'insights') ||
            (route.name === 'data-query') ||
            (route.name === 'screen-history') ||
            (route.name === 'strategy-converter') ||
            (route.name === 'winrate')
          error.value = failures.length && !softOk ? (failures[0] ?? '') : ''
        }
      } catch (caught: unknown) {
        if (seq === loadSeq) {
          error.value = errorMessage(caught, '接口请求失败')
        }
      } finally {
        if (seq === loadSeq) {
          loading.value = false
          inFlight = null
        }
      }
    })()

    inFlight = task
    return task
  }

  async function loadPoolDay(date?: string, poolId?: string): Promise<void> {
    error.value = ''
    loading.value = true
    try {
      if (date) selectedPoolDate.value = date
      if (poolId !== undefined) selectedPoolId.value = poolId
      poolDay.value = await getPoolDay(date, poolId)
    } catch (caught: unknown) {
      error.value = errorMessage(caught, '无法读取候选池')
    } finally {
      loading.value = false
    }
  }

  async function addTrade(payload: TradePayload, route?: RouteLocationNormalizedLoaded): Promise<void> {
    error.value = ''
    try {
      const result = await createTrade(payload)
      notice.value = `已写入 ${result.id}`
      if (route?.name === 'archive') {
        const code = String(route.params.code ?? payload.code ?? '')
        resetArchiveCache(code)
        selectedCode.value = code
        await ensureArchiveSlice(code, ['trades', 'timeline', 'dashboard'], { force: true })
      } else if (route) {
        await loadRoute(route, true)
      } else {
        const [nextDashboard, nextTrades, nextAnalytics] = await Promise.all([
          getDashboard(),
          getTrades(),
          getAnalytics(),
        ])
        dashboard.value = nextDashboard
        trades.value = nextTrades
        analytics.value = nextAnalytics
      }
    } catch (caught: unknown) {
      error.value = errorMessage(caught, '写入失败')
      throw caught
    }
  }

  function clearNotice(): void {
    notice.value = ''
  }

  function clearError(): void {
    error.value = ''
  }

  return {
    dashboard,
    trades,
    reviews,
    pools,
    poolDay,
    analytics,
    selectedTimeline,
    selectedCode,
    selectedPoolDate,
    selectedPoolId,
    loading,
    error,
    notice,
    hasData,
    firstPosition,
    loadRoute,
    loadPoolDay,
    ensureArchiveSlice,
    invalidateArchive,
    addTrade,
    clearNotice,
    clearError,
  }
})

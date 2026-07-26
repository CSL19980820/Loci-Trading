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
} from '@/api/palace'
import type {
  Analytics,
  Dashboard,
  PoolDay,
  PoolSummary,
  ReviewRecord,
  TimelineEvent,
  TradePayload,
  TradeRecord,
} from '@/types'

/** 并行读接口：单路失败不拖垮整页；成功结果才写入。 */
async function settleValue<T>(promise: Promise<T>): Promise<{ ok: true; value: T } | { ok: false; error: unknown }> {
  try {
    return { ok: true, value: await promise }
  } catch (error: unknown) {
    return { ok: false, error }
  }
}

function errorMessage(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback
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

  const hasData = computed(() => dashboard.value !== null)
  const firstPosition = computed(() => dashboard.value?.positions[0] ?? null)

  async function ensureDashboard(): Promise<void> {
    dashboard.value = await getDashboard()
  }

  /** 当前路由需要什么，就直接请求对应 API。没有本地账本缓存。 */
  async function loadRoute(route: RouteLocationNormalizedLoaded, force = false): Promise<void> {
    if (route.meta.public === true) return

    const key = `${String(route.name)}:${String(route.params.code ?? '')}:${selectedPoolDate.value}:${selectedPoolId.value}`
    if (!force && inFlight && lastKey === key) return inFlight

    lastKey = key
    const seq = ++loadSeq
    loading.value = true
    error.value = ''

    const task = (async () => {
      const failures: string[] = []
      try {
        switch (route.name) {
          case 'dashboard': {
            // 看板主数据必取；曲线/分布可降级，避免次要接口把整页打成 500 红条。
            const [dashResult, analyticsResult] = await Promise.all([
              settleValue(getDashboard()),
              settleValue(getAnalytics()),
            ])
            if (seq !== loadSeq) return
            if (dashResult.ok) dashboard.value = dashResult.value
            else failures.push(errorMessage(dashResult.error, '总览加载失败'))
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
          case 'reviews': {
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
            selectedCode.value = code
            const [timelineResult, tradesResult, dashResult] = await Promise.all([
              settleValue(getTimeline(code)),
              settleValue(getTrades(code)),
              settleValue(getDashboard()),
            ])
            if (seq !== loadSeq) return
            if (timelineResult.ok) selectedTimeline.value = timelineResult.value
            else failures.push(errorMessage(timelineResult.error, '时间线加载失败'))
            if (tradesResult.ok) {
              const others = trades.value.filter((item) => item.code !== code)
              trades.value = [...tradesResult.value, ...others]
            } else if (!timelineResult.ok) {
              failures.push(errorMessage(tradesResult.error, '成交加载失败'))
            }
            if (dashResult.ok) dashboard.value = dashResult.value
            break
          }
          default: {
            const dashResult = await settleValue(getDashboard())
            if (seq !== loadSeq) return
            if (dashResult.ok) dashboard.value = dashResult.value
            else failures.push(errorMessage(dashResult.error, '总览加载失败'))
          }
        }
        if (seq === loadSeq) {
          error.value = failures[0] ?? ''
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
      if (route) await loadRoute(route, true)
      else {
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
    addTrade,
    clearNotice,
    clearError,
  }
})
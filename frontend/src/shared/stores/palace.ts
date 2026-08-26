import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

import { getReviews, getTimeline } from '@/shared/api/palace'
import { toErrorMessage } from '@/shared/lib/errors'
import type { ReviewRecord, TimelineEvent } from '@/shared/types/palace'

/** 读接口包一层：单路失败不拖垮整页；成功结果才写入。 */
async function settleValue<T>(
  promise: Promise<T>,
): Promise<{ ok: true; value: T } | { ok: false; error: unknown }> {
  try {
    return { ok: true, value: await promise }
  } catch (error: unknown) {
    return { ok: false, error }
  }
}

export const usePalaceStore = defineStore('palace', () => {
  const reviews = ref<ReviewRecord[]>([])
  const selectedTimeline = ref<TimelineEvent[]>([])
  const selectedCode = ref('')
  const loading = ref(false)
  const error = ref('')

  let inFlight: Promise<void> | null = null
  let lastKey = ''
  let loadSeq = 0

  /** 个股工作台缓存：同代码切回已加载的候选时间线不再打接口。 */
  let archiveCache = {
    code: '',
    timeline: false,
  }

  function resetArchiveCache(code = ''): void {
    archiveCache = { code, timeline: false }
  }

  function archiveViewOf(route: RouteLocationNormalizedLoaded): 'quote' | 'candidates' {
    return String(route.query.view || 'quote') === 'candidates' ? 'candidates' : 'quote'
  }

  /** 按需拉取个股候选时间线；已加载过同一只票就不再打接口。 */
  async function ensureArchiveSlice(
    code: string,
    opts: { isCurrent?: () => boolean } = {},
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
    if (archiveCache.timeline) return []

    const result = await settleValue(getTimeline(normalized))
    if (!result.ok) return [toErrorMessage(result.error, '时间线加载失败')]
    // 响应回来时可能已切票：仍是同一只票才落库。
    const stale =
      !isCurrent() || archiveCache.code !== normalized || selectedCode.value !== normalized
    if (stale) return []
    selectedTimeline.value = result.value
    archiveCache.timeline = true
    return []
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
    if (archiveViewOf(route) === 'quote') return true
    return archiveCache.timeline
  }

  /** 当前路由需要什么，就直接请求对应 API。没有本地缓存副本。 */
  async function loadRoute(route: RouteLocationNormalizedLoaded, force = false): Promise<void> {
    if (route.meta.public === true) return

    const archiveView = route.name === 'archive' ? archiveViewOf(route) : ''
    const key = `${String(route.name)}:${String(route.params.code ?? '')}:${archiveView}`

    // 个股工作台：行情 tab 不打候选接口；已加载的候选切回不打接口、不闪顶栏进度条。
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
          case 'pool': {
            // PoolView 自己通过 Colada 查询候选列表；旧 store 不再预取
            // pools/day，避免两套状态模型互相覆盖。
            break
          }
          case 'reviews':
            // 绩效中心自管 Colada 分区查询，不预拉 reviews
            break
          case 'review-records': {
            const reviewsResult = await settleValue(getReviews())
            if (seq !== loadSeq) return
            if (reviewsResult.ok) reviews.value = reviewsResult.value
            else failures.push(toErrorMessage(reviewsResult.error, '复盘加载失败'))
            break
          }
          case 'archive': {
            const code = String(route.params.code ?? '')
            if (archiveCache.code !== code || selectedCode.value !== code) {
              selectedCode.value = code
              selectedTimeline.value = []
              resetArchiveCache(code)
            }
            // 行情 tab 只看 market quotes；候选 tab 按需。
            if (archiveViewOf(route) === 'quote') break
            failures.push(...(await ensureArchiveSlice(code, { isCurrent: () => seq === loadSeq })))
            if (seq !== loadSeq) return
            break
          }
          default:
            // ops / quant / insights / data-query 等由页面自管
            break
        }
        if (seq === loadSeq) {
          // 已有可读数据时，刷新失败不再盖红条（避免偶发锁竞争刷屏）
          const softOk =
            route.name === 'pulse' ||
            (route.name === 'review-records' && reviews.value.length > 0) ||
            route.name === 'reviews' ||
            route.name === 'ops' ||
            route.name === 'quant' ||
            route.name === 'insights' ||
            route.name === 'data-query' ||
            route.name === 'screen-history' ||
            route.name === 'strategy-converter' ||
            route.name === 'winrate'
          error.value = failures.length && !softOk ? (failures[0] ?? '') : ''
        }
      } catch (caught: unknown) {
        if (seq === loadSeq) {
          error.value = toErrorMessage(caught, '接口请求失败')
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

  function clearError(): void {
    error.value = ''
  }

  return {
    reviews,
    selectedTimeline,
    selectedCode,
    loading,
    error,
    loadRoute,
    invalidateArchive,
    clearError,
  }
})

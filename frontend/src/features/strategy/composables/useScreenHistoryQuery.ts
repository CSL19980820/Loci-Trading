/**
 * Pinia Colada：选股历史 getScreenHistory 只读缓存。
 * 不在此层计算胜率/盈亏；今日选股写操作后需显式 refetch。
 */
import { useQuery } from '@pinia/colada'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { getScreenHistory } from '@/shared/api/quant'
import type { ScreenHistory } from '@/shared/types/quant'

export type ScreenHistoryFilter = {
  strategy: string
  start?: string
  end?: string
  limit?: number
  /** 默认 true；false=含回填 */
  live_only?: boolean
}

export function useScreenHistoryQuery(filters: MaybeRefOrGetter<ScreenHistoryFilter>) {
  const query = useQuery({
    key: () => {
      const f = toValue(filters)
      return [
        'screen-history',
        f.strategy.trim(),
        f.start ?? '',
        f.end ?? '',
        f.limit ?? 500,
        f.live_only === false ? 'all' : 'live',
      ] as const
    },
    query: (): Promise<ScreenHistory | null> => {
      const f = toValue(filters)
      const strategy = f.strategy.trim()
      if (!strategy) return Promise.resolve(null)
      return getScreenHistory({
        strategy,
        start: f.start || undefined,
        end: f.end || undefined,
        limit: f.limit ?? 500,
        live_only: f.live_only !== false,
      })
    },
    enabled: () => Boolean(toValue(filters).strategy.trim()),
    staleTime: 30_000,
  })

  const history = computed(() => query.data.value ?? null)

  return {
    history,
    isPending: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

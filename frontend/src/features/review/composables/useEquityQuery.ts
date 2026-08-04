/**
 * Pinia Colada：复盘权益曲线只读缓存。
 * 数字以后端 EquityCurve 为准，前端禁止重算权威指标。
 */
import { useQuery } from '@pinia/colada'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { getEquityCurve } from '@/shared/api/quant_review'
import type { EquityCurve } from '@/shared/types/quant'

export function useEquityQuery(
  options: MaybeRefOrGetter<{
    start?: string
    end?: string
    benchmarks?: string
    enabled?: boolean
  }> = {},
) {
  const query = useQuery({
    key: () => {
      const opts = toValue(options)
      return ['review-equity', opts.start ?? '', opts.end ?? '', opts.benchmarks ?? ''] as const
    },
    query: (): Promise<EquityCurve> => {
      const opts = toValue(options)
      return getEquityCurve({
        start: opts.start,
        end: opts.end,
        benchmarks: opts.benchmarks,
      })
    },
    enabled: () => toValue(options).enabled !== false,
    staleTime: 60_000,
  })

  const curve = computed(() => query.data.value ?? null)

  return {
    curve,
    isPending: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

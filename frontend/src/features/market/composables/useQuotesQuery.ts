/**
 * Pinia Colada 试点：缓存单票日线 getQuotes。
 * 不在此层计算盈亏/胜率；数字以后端 QuoteSeries 为准。
 */
import { useQuery } from '@pinia/colada'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { getQuotes } from '@/shared/api/quant_market'
import type { QuoteSeries } from '@/shared/types/quant'

export type QuotesAdjust = 'qfq' | 'hfq' | 'none'

export function useQuotesQuery(
  code: MaybeRefOrGetter<string>,
  options: MaybeRefOrGetter<{
    adjust?: QuotesAdjust
    limit?: number
    start?: string
    end?: string
    /** 默认有代码即拉取；个股工作台可按 tab 关闭 */
    enabled?: boolean
  }> = {},
) {
  const query = useQuery({
    key: () => {
      const c = toValue(code).trim()
      const opts = toValue(options)
      return [
        'market-quotes',
        c,
        opts.adjust ?? 'qfq',
        opts.limit ?? 60,
        opts.start ?? '',
        opts.end ?? '',
      ] as const
    },
    query: async (): Promise<QuoteSeries | null> => {
      const c = toValue(code).trim()
      if (!c) return null
      const opts = toValue(options)
      return getQuotes(c, {
        adjust: opts.adjust,
        limit: opts.limit ?? 60,
        start: opts.start,
        end: opts.end,
      })
    },
    enabled: () => {
      const c = toValue(code).trim()
      if (!c) return false
      const opts = toValue(options)
      return opts.enabled !== false
    },
    staleTime: 60_000,
  })

  const quote = computed(() => query.data.value ?? null)
  const isError = computed(() => query.error.value !== null)

  return {
    quote,
    isPending: query.isPending,
    isLoading: query.isLoading,
    error: query.error,
    isError,
    refetch: query.refetch,
    refresh: query.refetch,
  }
}

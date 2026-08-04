/**
 * Pinia Colada：复盘持仓归因 getRoundTrips 只读缓存。
 * 数字以后端 trips/summary 为准，前端禁止重算权威指标。
 */
import { useQuery } from '@pinia/colada'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { getRoundTrips } from '@/shared/api/quant'
import type { RoundTrip, RoundTripSummary } from '@/shared/types/quant'

export type RoundTripsResult = {
  trips: RoundTrip[]
  summary: RoundTripSummary
}

export function useRoundTripsQuery(
  code: MaybeRefOrGetter<string | undefined> = undefined,
  options: MaybeRefOrGetter<{ enabled?: boolean }> = {},
) {
  const query = useQuery({
    key: () => ['review-trips', toValue(code) ?? ''] as const,
    query: (): Promise<RoundTripsResult> => getRoundTrips(toValue(code) || undefined),
    enabled: () => toValue(options).enabled !== false,
    staleTime: 60_000,
  })

  const trips = computed(() => query.data.value ?? null)

  return {
    trips,
    isPending: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

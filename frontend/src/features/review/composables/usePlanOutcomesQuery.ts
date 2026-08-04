/**
 * Pinia Colada：预案兑现 getPlanOutcomes 只读缓存。
 * 状态与触发结果以后端为准。
 */
import { useQuery } from '@pinia/colada'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { getPlanOutcomes } from '@/shared/api/quant'
import type { PlanOutcome } from '@/shared/types/quant'

export function usePlanOutcomesQuery(options: MaybeRefOrGetter<{ enabled?: boolean }> = {}) {
  const query = useQuery({
    key: () => ['review-plan-outcomes'] as const,
    query: (): Promise<PlanOutcome[]> => getPlanOutcomes(),
    enabled: () => toValue(options).enabled !== false,
    staleTime: 60_000,
  })

  const plans = computed(() => query.data.value ?? [])

  return {
    plans,
    isPending: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

/**
 * Pinia Colada：候选验证 getCandidateOutcomes 只读缓存。
 * T+N 收益以后端为准，前端禁止发明胜率。
 */
import { useQuery } from '@pinia/colada'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { getCandidateOutcomes } from '@/shared/api/quant'
import type { CandidateOutcome, CandidateSummary } from '@/shared/types/quant'

export type CandidateOutcomesResult = {
  outcomes: CandidateOutcome[]
  summary: CandidateSummary
}

export function useCandidateOutcomesQuery(
  limit: MaybeRefOrGetter<number> = 300,
  options: MaybeRefOrGetter<{ enabled?: boolean }> = {},
) {
  const query = useQuery({
    key: () => ['review-candidate-outcomes', toValue(limit)] as const,
    query: (): Promise<CandidateOutcomesResult> => getCandidateOutcomes(toValue(limit)),
    enabled: () => toValue(options).enabled !== false,
    staleTime: 60_000,
  })

  const candidates = computed(() => query.data.value ?? null)

  return {
    candidates,
    isPending: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

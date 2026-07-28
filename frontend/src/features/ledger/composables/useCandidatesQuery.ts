/**
 * Pinia Colada：候选池 listCandidates 缓存。
 * 不在此层计算胜率/盈亏；删除后需 refetch。
 */
import { useQuery } from '@pinia/colada'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { listCandidates } from '@/shared/api/palace'
import type { Candidate } from '@/shared/types/palace'

export type CandidatesFilter = {
  strategy?: string
  decision?: string
  start?: string
  end?: string
  limit?: number
}

export function useCandidatesQuery(filters: MaybeRefOrGetter<CandidatesFilter> = {}) {
  const query = useQuery({
    key: () => {
      const f = toValue(filters)
      return [
        'candidates-list',
        f.strategy ?? '',
        f.decision ?? '',
        f.start ?? '',
        f.end ?? '',
        f.limit ?? 2000,
      ] as const
    },
    query: () => {
      const f = toValue(filters)
      return listCandidates({
        strategy: f.strategy || undefined,
        decision: f.decision || undefined,
        start: f.start,
        end: f.end,
        limit: f.limit ?? 2000,
      })
    },
    staleTime: 30_000,
  })

  const rows = computed(() => (query.data.value as Candidate[] | undefined) ?? [])

  return {
    rows,
    isPending: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

/**
 * Pinia Colada：任务执行历史 getJobRuns 只读缓存。
 * 跑任务成功后需显式 refetch。
 */
import { useQuery } from '@pinia/colada'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { getJobRuns } from '@/shared/api/quant'
import type { JobRun } from '@/shared/types/quant'

export type JobRunsFilter = {
  job_id?: string
  status?: string
  limit?: number
}

export function useJobRunsQuery(filters: MaybeRefOrGetter<JobRunsFilter> = {}) {
  const query = useQuery({
    key: () => {
      const f = toValue(filters)
      return [
        'ops-job-runs',
        f.job_id ?? '',
        f.status ?? '',
        f.limit ?? 20,
      ] as const
    },
    query: (): Promise<JobRun[]> => {
      const f = toValue(filters)
      return getJobRuns({
        job_id: f.job_id,
        status: f.status,
        limit: f.limit ?? 20,
      })
    },
    staleTime: 15_000,
  })

  const runs = computed(() => query.data.value ?? [])

  return {
    runs,
    isPending: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

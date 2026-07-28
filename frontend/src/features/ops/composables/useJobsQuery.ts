/**
 * Pinia Colada：定时任务列表 getJobs 只读缓存。
 * 创建/更新/执行/删除成功后需显式 refetch；不在此层写业务公式。
 */
import { useQuery } from '@pinia/colada'
import { computed } from 'vue'

import { getJobs } from '@/shared/api/quant'
import type { Job } from '@/shared/types/quant'

export function useJobsQuery() {
  const query = useQuery({
    key: () => ['ops-jobs'] as const,
    query: (): Promise<Job[]> => getJobs(),
    staleTime: 15_000,
  })

  const jobs = computed(() => query.data.value ?? [])

  return {
    jobs,
    isPending: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

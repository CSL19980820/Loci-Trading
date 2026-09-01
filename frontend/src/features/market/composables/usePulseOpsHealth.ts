/**
 * 首屏「任务健康」取数：定时选股是否启用、下次触发时间、最近一次失败运行。
 * 三块并行取，任一失败只降级那一块并把原因写进 error——不把失败吞成「一切正常」。
 */
import { onDeactivated, onMounted, onUnmounted, ref, type Ref } from 'vue'

import { getJobRuns, getJobs, getScheduleStatus } from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type { Job, JobRun, ScheduleStatus } from '@/shared/types/quant'

/** 已启用的 screen 任务里最早的非空 next_run_at；一个都没有则 null。 */
function earliestScreenNextRun(jobs: Job[], schedule: ScheduleStatus | null): string | null {
  if (!schedule) return null
  const screenIds = new Set(
    jobs.filter((j) => j.kind === 'screen' && j.enabled).map((j) => j.id),
  )
  if (!screenIds.size) return null
  let earliest: string | null = null
  for (const entry of schedule.jobs || []) {
    if (!screenIds.has(entry.id)) continue
    const next = (entry.next_run_at || '').trim()
    if (!next) continue
    // 后端给的是同一种时间串，字典序即时序；解析失败的怪串也能稳定取到一个
    if (earliest === null || next < earliest) earliest = next
  }
  return earliest
}

export interface PulseOpsHealth {
  loading: Ref<boolean>
  /** 三块里任何一块读不到的原因（多条以「；」相连）；空串=都读到了 */
  error: Ref<string>
  hasEnabledScreenJob: Ref<boolean>
  nextScreenRunAt: Ref<string | null>
  lastFailedRun: Ref<JobRun | null>
  load: () => Promise<void>
}

export function usePulseOpsHealth(): PulseOpsHealth {
  const loading = ref(false)
  const error = ref('')
  const hasEnabledScreenJob = ref(false)
  const nextScreenRunAt = ref<string | null>(null)
  const lastFailedRun = ref<JobRun | null>(null)

  let generation = 0
  let controller: AbortController | null = null

  async function load(): Promise<void> {
    const token = ++generation
    controller?.abort()
    const ac = new AbortController()
    controller = ac
    loading.value = true
    error.value = ''
    try {
      const [jobsResult, scheduleResult, runsResult] = await Promise.allSettled([
        getJobs(),
        getScheduleStatus(),
        getJobRuns({ status: 'failed', limit: 3 }, ac.signal),
      ])
      if (token !== generation) return

      const failures: string[] = []

      const jobs = jobsResult.status === 'fulfilled' ? jobsResult.value : []
      if (jobsResult.status === 'rejected') {
        failures.push(toErrorMessage(jobsResult.reason, '任务列表读取失败'))
      }
      hasEnabledScreenJob.value = jobs.some((j) => j.kind === 'screen' && j.enabled)

      if (scheduleResult.status === 'rejected') {
        failures.push(toErrorMessage(scheduleResult.reason, '调度状态读取失败'))
      }
      nextScreenRunAt.value = earliestScreenNextRun(
        jobs,
        scheduleResult.status === 'fulfilled' ? scheduleResult.value : null,
      )

      if (runsResult.status === 'fulfilled') {
        lastFailedRun.value = runsResult.value[0] ?? null
      } else {
        lastFailedRun.value = null
        failures.push(toErrorMessage(runsResult.reason, '失败运行记录读取失败'))
      }

      error.value = failures.join('；')
    } finally {
      if (token === generation) loading.value = false
    }
  }

  function cancelInFlight(): void {
    // 卸载/离页后作废在途请求与回写
    generation += 1
    controller?.abort()
    controller = null
    loading.value = false
  }

  onDeactivated(cancelInFlight)
  onUnmounted(cancelInFlight)

  onMounted(() => {
    void load()
  })

  return { loading, error, hasEnabledScreenJob, nextScreenRunAt, lastFailedRun, load }
}

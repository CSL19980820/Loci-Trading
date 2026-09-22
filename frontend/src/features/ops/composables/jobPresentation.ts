/**
 * 任务行的展示换算：cron → 人话、下次触发、名册行。
 *
 * 三段都是纯函数，拆出来有两个原因：一是它们的口径值得被单测直接钉住（`mon-fri`
 * 与 `1-5` 是同一件事、调度器没起时要显示后端给的原因），喂一个 Job 字面量就能测，
 * 不必先 mount 定时台；二是 JobsTab 本体装的是 CRUD 与回执，再驮这三段就过 600 行。
 */
import type { Job, ScheduleStatus } from '@/shared/types/quant'

import type { JobRailRow } from '../components/JobsRail.vue'
import { isBoundManagedJob, jobOriginLabel } from './jobOwnership'
import { formatNext, jobHealth, jobHealthLabel, kindLabel } from './opsLabels'

/**
 * cron → 人话。托管任务写的是 `mon-fri`（APScheduler 口径），本机任务的历史
 * 预设写的是 `1-5`，两种都要认得出来，否则同一个时点显示成两种样子。
 */
export function cronLabel(job: Job): string {
  if (!job.cron) return '仅手动'
  const text = job.cron.replace(/\bmon-fri\b/i, '1-5')
  if (text === '*/5 9-14 * * 1-5') return '盘中每 5 分钟'
  const once = /^(\d{1,2}) (\d{1,2}) \* \* 1-5$/.exec(text)
  if (once) {
    return `工作日 ${once[2].padStart(2, '0')}:${once[1].padStart(2, '0')}`
  }
  return job.cron
}

/**
 * 下次触发。schedule 显式传进来（而不是闭包里抓）：这段跟着任务行走，
 * 谁在渲染它就该说清楚自己拿的是哪一份调度快照。
 */
export function nextRunText(job: Job, schedule: ScheduleStatus | null): string {
  if (!job.cron) return '仅手动'
  if (!job.enabled) return '已停用'
  const hit = schedule?.jobs.find((item) => item.id === job.id)
  const text = formatNext(hit?.next_run_at)
  if (text !== '—') return text
  // 调度器未跑时后端仍会按 cron 推算；若仍无值，展示原因
  return schedule?.reason ? `—（${schedule.reason}）` : '—'
}

export function railRowsOf(jobs: Job[], displayName: (job: Job) => string): JobRailRow[] {
  return jobs.map((job) => {
    const health = jobHealth(job)
    return {
      id: job.id,
      title: displayName(job),
      kindText: kindLabel(job.kind),
      originText: jobOriginLabel(job),
      bound: isBoundManagedJob(job),
      enabled: job.enabled,
      health,
      healthText: jobHealthLabel(health),
      cronText: cronLabel(job),
      lastRunAt: job.last_run_at || '',
    }
  })
}

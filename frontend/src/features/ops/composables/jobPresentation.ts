/**
 * 任务行的展示换算：cron → 人话、下次触发、名册行。
 *
 * 三段都是纯函数：口径值得被单测直接钉住（`mon-fri` 与 `1-5` 是同一件事、多条
 * cron 合并成一句、调度器没起时要显示后端给的原因），喂一个 Job 字面量就能测。
 */
import type { Job, ScheduleStatus } from '@/shared/types/quant'

import type { JobRailRow } from '../components/JobsRail.vue'
import { splitCronExpressions } from '../lib/cronPreview'
import { isBoundManagedJob, jobOriginLabel } from './jobOwnership'
import { formatNext, jobHealth, jobHealthLabel, kindLabel } from './opsLabels'

const DOW_INDEX: Record<string, number> = { mon: 0, tue: 1, wed: 2, thu: 3, fri: 4, sat: 5, sun: 6 }
const DOW_TEXT = ['一', '二', '三', '四', '五', '六', '日']

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** 星期字段 → 人话；只认名字写法与历史 `1-5`，数字星期口径有歧义，认不出就放弃 */
function dayText(field: string): string | null {
  const value = field.trim().toLowerCase()
  if (value === '*') return '每天'
  if (value === 'mon-fri' || value === '1-5' || value === '1,2,3,4,5') return '工作日'
  if (value === 'sat,sun' || value === 'sat-sun') return '周末'
  const days: number[] = []
  for (const part of value.split(',')) {
    const [a, b] = part.split('-')
    const start = DOW_INDEX[a ?? '']
    const end = b === undefined ? start : DOW_INDEX[b]
    if (start === undefined || end === undefined || end < start) return null
    for (let d = start; d <= end; d += 1) days.push(d)
  }
  return days.length ? `周${days.map((d) => DOW_TEXT[d]).join('、')}` : null
}

type HourSpan = [number, number]

function parseHours(field: string): HourSpan[] | null {
  const spans: HourSpan[] = []
  for (const part of field.split(',')) {
    if (part === '*') {
      spans.push([0, 23])
      continue
    }
    const range = /^(\d{1,2})(?:-(\d{1,2}))?$/.exec(part)
    if (!range) return null
    const start = Number(range[1])
    const end = range[2] === undefined ? start : Number(range[2])
    if (start > 23 || end > 23 || end < start) return null
    spans.push([start, end])
  }
  return spans
}

type CronLine = { day: string; times: string[]; spans: string[]; step: number | null; intraday: boolean }

function parseLine(line: string): CronLine | null {
  const fields = line.trim().split(/\s+/)
  if (fields.length !== 5) return null
  const [minute, hour, dom, month, dow] = fields as [string, string, string, string, string]
  if (dom !== '*' || month !== '*') return null
  const day = dayText(dow)
  const hours = parseHours(hour)
  if (!day || !hours) return null
  const step = /^(?:\*|\d{1,2}-\d{1,2})\/(\d{1,2})$/.exec(minute)
  if (step) {
    const intraday = hours.every(([start, end]) => start >= 9 && end <= 15)
    return { day, times: [], spans: [], step: Number(step[1]), intraday }
  }
  if (!/^\d{1,2}$/.test(minute)) return null
  const m = Number(minute)
  const times: string[] = []
  const spans: string[] = []
  for (const [start, end] of hours) {
    if (start === end) times.push(`${pad(start)}:${pad(m)}`)
    else spans.push(`${pad(start)}:${pad(m)}–${pad(end)}:${pad(m)} 每小时`)
  }
  return { day, times, spans, step: null, intraday: false }
}

// cron → 一句人话。多条表达式（分号或换行分隔）按星期合并，例如盘中三段每 5 分钟
// 加一个 15:00 定点 → 「工作日 盘中每 5 分钟 · 15:00」。任一条看不懂就返回 null，
// 由调用方回落到原文。
export function humanizeCron(cron: string): { day: string; body: string } | null {
  const lines = splitCronExpressions(cron)
  if (!lines.length) return null
  const parsed = lines.map(parseLine)
  if (parsed.some((line) => line === null)) return null
  const rows = parsed as CronLine[]
  const day = rows[0]!.day
  if (rows.some((row) => row.day !== day)) return null
  const steps = [...new Set(rows.map((row) => row.step).filter((n): n is number => n !== null))]
  const times = [...new Set(rows.flatMap((row) => row.times))].sort()
  const spans = rows.flatMap((row) => row.spans)
  const parts: string[] = []
  if (steps.length) {
    const intraday = rows.every((row) => row.step === null || row.intraday)
    parts.push(`${intraday ? '盘中' : ''}每 ${steps.sort((a, b) => a - b).join('/')} 分钟`)
  }
  parts.push(...spans)
  if (times.length > 3) parts.push(`${times[0]} 起 ${times.length} 个时点`)
  else parts.push(...times)
  return { day, body: parts.join(' · ') }
}

/** cron → 人话；看不懂的写法原样给出，不编一个近似值 */
export function cronLabel(job: Pick<Job, 'cron'>): string {
  if (!job.cron) return '仅手动'
  const human = humanizeCron(job.cron)
  return human ? `${human.day} ${human.body}` : job.cron
}

/** 调度器快照里这一条的下次触发时刻（原文 ISO），没有就是空串 */
export function nextRunAt(job: Pick<Job, 'id'>, schedule: ScheduleStatus | null): string {
  return String(schedule?.jobs.find((item) => item.id === job.id)?.next_run_at || '')
}

/**
 * 下次触发。schedule 显式传进来（而不是闭包里抓）：这段跟着任务行走，
 * 谁在渲染它就该说清楚自己拿的是哪一份调度快照。
 */
export function nextRunText(job: Job, schedule: ScheduleStatus | null): string {
  if (!job.cron) return '仅手动'
  if (!job.enabled) return '已停用'
  const text = formatNext(nextRunAt(job, schedule))
  if (text !== '—') return text
  return schedule?.reason ? `—（${schedule.reason}）` : '—'
}

function parseStamp(raw: string): Date | null {
  const text = raw.trim()
  if (!text) return null
  const time = Date.parse(text.includes('T') ? text : text.replace(' ', 'T'))
  return Number.isFinite(time) ? new Date(time) : null
}

function dayOffset(target: Date, now: Date): number {
  const a = new Date(target.getFullYear(), target.getMonth(), target.getDate()).getTime()
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  return Math.round((a - b) / 86_400_000)
}

/** 「今天 15:45」「明天 09:25」「09-28 15:45」 */
export function relativeDayTime(raw: string, now: Date = new Date()): string {
  const date = parseStamp(raw)
  if (!date) return ''
  const hm = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const offset = dayOffset(date, now)
  if (offset === 0) return `今天 ${hm}`
  if (offset === 1) return `明天 ${hm}`
  if (offset === -1) return `昨天 ${hm}`
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${hm}`
}

/** 距现在还有多久：「4 小时 20 分」「12 分」「2 天」 */
export function countdownText(raw: string, now: Date = new Date()): string {
  const date = parseStamp(raw)
  if (!date) return ''
  const minutes = Math.round((date.getTime() - now.getTime()) / 60_000)
  if (minutes < 0) return ''
  if (minutes < 1) return '即将'
  if (minutes < 60) return `${minutes} 分`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return minutes % 60 ? `${hours} 小时 ${minutes % 60} 分` : `${hours} 小时`
  return `${Math.floor(hours / 24)} 天`
}

export function railRowsOf(
  jobs: Job[],
  displayName: (job: Job) => string,
  schedule: ScheduleStatus | null = null,
): JobRailRow[] {
  return jobs.map((job) => {
    const health = jobHealth(job)
    const human = job.cron ? humanizeCron(job.cron) : null
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
      dayText: human?.day ?? (job.cron ? '' : '仅手动'),
      bodyText: human?.body ?? job.cron,
      nextRunAt: job.enabled ? nextRunAt(job, schedule) : '',
      lastRunAt: job.last_run_at || '',
    }
  })
}

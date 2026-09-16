import { strategyLabel } from '@/shared/lib/format'
import type { Job, JobRun } from '@/shared/types/quant'

/**
 * 一条任务的健康态。列表行上原本只有类型与启用态，`last_status` 完全不露脸，
 * 于是「哪条挂了」只能逐条点开看——这个类型就是为了把它显示在行上。
 *
 * `timed_out` 归 failed（超时就是没跑成），`cancelled` 归 skipped（是人喊停的，
 * 不是系统坏了）。两者混成一档会让「只看失败」筛出一堆自己按的取消。
 */
export type JobHealth = 'ok' | 'failed' | 'skipped' | 'running' | 'never'

const HEALTH_BY_STATUS: Record<string, JobHealth> = {
  success: 'ok',
  failed: 'failed',
  timed_out: 'failed',
  skipped: 'skipped',
  cancelled: 'skipped',
  running: 'running',
}

export function jobHealth(job: Pick<Job, 'last_status'>): JobHealth {
  const status = String(job.last_status || '').trim().toLowerCase()
  if (!status) return 'never'
  return HEALTH_BY_STATUS[status] ?? 'never'
}

/** 圆点旁的一句话。「从未跑过」必须说出来：空白会被读成「没问题」。 */
export function jobHealthLabel(health: JobHealth): string {
  const labels: Record<JobHealth, string> = {
    ok: '上次成功',
    failed: '上次失败',
    skipped: '上次跳过',
    running: '正在跑',
    never: '从未跑过',
  }
  return labels[health]
}

export function kindLabel(kind: string): string {
  return (
    {
      sync: '同步行情',
      screen: '选股',
      backtest: '回测',
      skill: '技能模式',
      notify: '企微推送',
      compare: '横向对比',
      optimize: '退出扫描',
      prune: '清理历史',
      outcome: '候选T+N',
      hot_rebuild: '行情热库重建',
      data_quality: '行情库体检',
      intel_fetch: '情报采集',
      intel_brief: '简报推送',
      skill_watch: '战法监测',
      alert_scan: '价格提醒扫描',
      strategy_monitor: '纸面盯盘',
      paper_eod: '纸面日终',
      guardian: '自主交易员',
      guardian_review: '交易员复盘与计划',
      exchange_calendar: '交易所日历更新',
    }[kind] ?? kind
  )
}

export function statusLabel(status: string): string {
  return (
    { success: '✓ 成功', failed: '✗ 失败', running: '… 运行中', skipped: '跳过' }[status] ??
    (status || '—')
  )
}

/** 触发方式中文标签 */
export function triggerLabel(trigger: string): string {
  const key = (trigger || '').trim().toLowerCase()
  const map: Record<string, string> = {
    schedule: '定时',
    api: '接口',
    manual: '手动',
  }
  return map[key] ?? (trigger || '—')
}

export function formatNext(value?: string | null): string {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
}

export function firstLine(text: string): string {
  return text.split('\n')[0].slice(0, 90)
}

export function formatBytes(n: number): string {
  if (!n || n < 0) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function parseRunResult(result: unknown): Record<string, unknown> {
  if (!result) return {}
  if (typeof result === 'string') {
    try {
      return JSON.parse(result) as Record<string, unknown>
    } catch {
      return {}
    }
  }
  if (typeof result === 'object') return result as Record<string, unknown>
  return {}
}

export function formatLlmMeta(run: JobRun): string {
  const meta = parseRunResult(run.result).llm_meta as
    | { provider?: string; model?: string; thinking?: string }
    | undefined
  if (!meta || (!meta.provider && !meta.model)) return '—'
  const parts = [meta.provider, meta.model].filter(Boolean)
  if (meta.thinking) parts.push(meta.thinking)
  return parts.join(' · ')
}

export function formatRtt(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return '—'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`
  return `${Math.round(ms)} ms`
}

/** 任务执行耗时：≥1s 忽略 ms，如 11h2min3s / 7min23s / 3s；不足 1s 用 ms */
export function formatRunDuration(ms: number | null | undefined): string {
  const n = Math.max(0, Math.round(Number(ms) || 0))
  if (n < 1000) return `${n}ms`
  let rem = Math.floor(n / 1000)
  const h = Math.floor(rem / 3600)
  rem %= 3600
  const m = Math.floor(rem / 60)
  const s = rem % 60
  const parts: string[] = []
  if (h) parts.push(`${h}h`)
  if (m) parts.push(`${m}min`)
  if (s || !parts.length) parts.push(`${s}s`)
  return parts.join('')
}

export function formatThroughput(mb: number | null | undefined): string {
  if (mb == null || Number.isNaN(mb) || mb <= 0) return '—'
  return `${mb.toFixed(2)} MB/s`
}

/**
 * 后端 `name` 与 slug 的取舍：**界面上不许出现 `sanyuan-tail-v1` 这类英文编码**。
 *
 * `name` 缺失、或它本身就是 slug 形状（全小写字母数字 + 连字符、没有空格与中文）时
 * 一律改走共享词表 `strategyLabel`（含拼音词根兜底）；其余情况尊重用户自己起的名字。
 */
export function cnStrategyName(name: string | null | undefined, slug: string): string {
  const text = String(name || '').trim()
  const slugShaped = /^[a-z0-9][a-z0-9._-]*$/.test(text)
  if (text && !slugShaped) return text
  return strategyLabel(slug || text)
}

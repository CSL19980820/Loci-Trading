import type { JobRun } from '@/shared/types/quant'

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

/** Pure display helpers for QuantView (not Vue state). */

export function formatFunnel(
  f:
    | {
        instruments_total?: number
        after_board?: number
        after_st?: number
        panel_columns?: number
        signals_true?: number
      }
    | null
    | undefined,
): string {
  if (!f) return ''
  return `漏斗 ${f.instruments_total ?? '—'} → 板 ${f.after_board ?? '—'} → 剔ST后 ${f.after_st ?? '—'} → 面板 ${f.panel_columns ?? '—'} → 信号 ${f.signals_true ?? '—'}`
}

export function fmt(value: number | boolean | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '✓' : '—'
  return Number(value).toFixed(2)
}

export { signedPct as signed } from '@/shared/lib/format'

export function pnlTone(value: number | null | undefined): 'up' | 'down' | '' {
  if (value == null) return ''
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

const EXIT_LABELS: Record<string, string> = {
  hold_expired: '到期',
  stop_loss: '止损',
  take_profit: '止盈',
  data_end: '数据到头',
}

const EXIT_DIST_LABELS: Record<string, string> = {
  hold_expired: '到期',
  stop_loss: '止损',
  take_profit: '止盈',
  data_end: '无数据',
}

export function exitReasonLabel(reason: string | undefined): string {
  if (!reason) return '—'
  return EXIT_LABELS[reason] ?? reason
}

export function exitReasonsText(reasons: Record<string, number> | undefined): string {
  if (!reasons) return '—'
  return (
    Object.entries(reasons)
      .map(([key, count]) => `${exitReasonLabel(key)} ${count}`)
      .join(' · ') || '—'
  )
}

export function exitDist(reasons: Record<string, number>): string {
  return Object.entries(reasons)
    .map(([key, count]) => `${EXIT_DIST_LABELS[key] ?? key}${count}`)
    .join(' ')
}

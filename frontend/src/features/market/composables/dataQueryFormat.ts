/** Pure display helpers for DataQueryView. */
import { compactNumber } from '@/shared/lib/format'

export function formatCount(n: number | undefined): string {
  if (n == null) return '—'
  // 计数不用「亿」档，但也不再中英混排（原先 100 万以上会显示成 1.0M）
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}万`
  return String(n)
}

export { pct as fmtPct, price as fmtPrice } from '@/shared/lib/format'

export function fmtChange(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}`
}

export function fmtAmount(v: number | null | undefined): string {
  return compactNumber(v)
}

/** 库内换手为小数；展示为百分数。 */
export function fmtTurnover(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(2)}%`
}

export function chgClass(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(Number(pct)) || Number(pct) === 0) return ''
  return Number(pct) > 0 ? 'is-up' : 'is-down'
}

export function pnlClass(v: number | null | undefined): string {
  if (v == null || v === 0) return ''
  return v > 0 ? 'is-up' : 'is-down'
}

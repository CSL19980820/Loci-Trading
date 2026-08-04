/** Pure display helpers for DataQueryView. */

export function formatCount(n: number | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}万`
  return String(n)
}

export function fmtPrice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return Number(v).toFixed(2)
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

export function fmtChange(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}`
}

export function fmtAmount(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(1)}万`
  return n.toFixed(0)
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

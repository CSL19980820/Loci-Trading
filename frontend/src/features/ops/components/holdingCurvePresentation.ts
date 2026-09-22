import type { HoldingCurvePoint } from '@/shared/types/holdingCurve'

export type CurveMetric = 'drawdown' | 'return' | 'pnl'

/** Display coordinates only. Financial values remain the server's canonical values. */
export function curveTimestamp(value: string): number {
  let normalized = value.trim().replace(' ', 'T')
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized)) normalized += '+08:00'
  return Date.parse(normalized)
}

export function curvePointValue(point: HoldingCurvePoint, metric: CurveMetric): number | null {
  if (point.nav == null || !Number.isFinite(point.nav) || point.nav < 0 || point.quality !== 'verified') return null
  const value = metric === 'drawdown' ? point.drawdown_pct : metric === 'return' ? (point.nav - 1) * 100 : point.pnl_cents == null ? null : point.pnl_cents / 100
  return value != null && Number.isFinite(value) ? value : null
}

export function curveTickLabel(timestamp: number, sameDay: boolean, spanDays: number): string {
  if (!Number.isFinite(timestamp)) return ''
  const local = new Date(timestamp + 8 * 3600000).toISOString()
  if (sameDay) return local.slice(11, 16)
  return spanDays > 90 ? local.slice(0, 7) : local.slice(5, 10)
}

export function thresholdDistance(currentDrawdown: number | null, threshold: number): number | null {
  return currentDrawdown == null || !Number.isFinite(currentDrawdown) ? null : threshold + currentDrawdown
}

/** K 线详情共享配置与类型（勿从 .vue SFC 再 export const）。 */

import type { OhlcBar } from './indicators'

export type IndicatorKind = 'macd' | 'kdj'

export type KlineHoverPayload = {
  bar: OhlcBar & { turnover?: number | null }
  prevClose: number | null
  index: number
  ma: Array<{ period: number; value: number | null }>
  volume: number | null
  volumeMa: Array<{ period: number; value: number | null }>
  macd: { dif: number | null; dea: number | null; hist: number | null } | null
  kdj: { k: number | null; d: number | null; j: number | null } | null
}

/** 通达信常用默认均线；可在设置里改成任意周期（如 5/13/21） */
export const DEFAULT_MA_PERIODS: number[] = [5, 10, 20, 30, 60, 120, 250]

export const MA_LINE_COLORS = [
  '#c41e3a',
  '#2563eb',
  '#d97706',
  '#7c3aed',
  '#0f6b5c',
  '#0891b2',
  '#be185d',
  '#ca8a04',
]

/** 规范化均线周期：整数 2–500，去重升序；空数组 = 不画均线 */
export function normalizeMaPeriods(raw: unknown): number[] {
  if (!Array.isArray(raw)) return []
  const set = new Set<number>()
  for (const item of raw) {
    const n = Math.round(Number(item))
    if (!Number.isFinite(n) || n < 2 || n > 500) continue
    set.add(n)
  }
  return [...set].sort((a, b) => a - b)
}

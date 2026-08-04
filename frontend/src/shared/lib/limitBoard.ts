/** A 股涨跌停幅度与触板判定（展示用，非交易所权威）。 */

export type LimitKind = 'up' | 'down' | null

/** 主板 10%、创业/科创 20%、ST 5%。 */
export function boardLimitRatio(code: string, name?: string | null): number {
  const label = String(name ?? '').toUpperCase()
  if (label.includes('ST')) return 0.05
  const c = String(code ?? '').trim()
  if (c.startsWith('300') || c.startsWith('301') || c.startsWith('688')) return 0.2
  return 0.1
}

export function limitPrices(
  prevClose: number,
  code: string,
  name?: string | null,
): { up: number; down: number; ratio: number } {
  const ratio = boardLimitRatio(code, name)
  return {
    ratio,
    up: prevClose * (1 + ratio),
    down: prevClose * (1 - ratio),
  }
}

export type LimitDetectMode = 'touch' | 'close'

/**
 * 触板判定。
 * - touch：最高/最低或收盘贴近涨跌停价（含冲高回落）
 * - close：仅收盘封板（给 K 线钉标用，避免阴线还钉「涨停」）
 * 容差约 0.15%（复权与四舍五入）。
 */
export function detectLimitHit(
  bar: { high?: number | null; low?: number | null; close?: number | null },
  prevClose: number | null | undefined,
  code: string,
  name?: string | null,
  mode: LimitDetectMode = 'touch',
): LimitKind {
  if (prevClose == null || !Number.isFinite(prevClose) || prevClose <= 0) return null
  const { up, down } = limitPrices(prevClose, code, name)
  const high = Number(bar.high)
  const low = Number(bar.low)
  const close = Number(bar.close)
  const tolUp = up * 0.0015
  const tolDown = down * 0.0015
  const closeUp = Number.isFinite(close) && close >= up - tolUp
  const closeDown = Number.isFinite(close) && close <= down + tolDown
  const hitUp =
    mode === 'close'
      ? closeUp
      : (Number.isFinite(high) && high >= up - tolUp) || closeUp
  const hitDown =
    mode === 'close'
      ? closeDown
      : (Number.isFinite(low) && low <= down + tolDown) || closeDown
  if (hitUp && !hitDown) return 'up'
  if (hitDown && !hitUp) return 'down'
  if (hitUp && hitDown) {
    // 同日极端：以收盘贴近哪侧为准
    if (Number.isFinite(close)) {
      return Math.abs(close - up) <= Math.abs(close - down) ? 'up' : 'down'
    }
    return 'up'
  }
  return null
}

export function limitLabel(kind: LimitKind): string {
  if (kind === 'up') return '涨停'
  if (kind === 'down') return '跌停'
  return ''
}

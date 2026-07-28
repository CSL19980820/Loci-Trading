export type SampleConfidence = 'low' | 'medium' | 'high'

/** 复盘 / 交割笔数 → 样本可信度：<5 低，5–29 中，≥30 高。 */
export function sampleConfidence(total: number): SampleConfidence {
  if (total < 5) return 'low'
  if (total < 30) return 'medium'
  return 'high'
}

/** 样本 badge：低/中显示，高样本不显示。 */
export function sampleBadgeLabel(total: number): '样本不足' | '初步' | null {
  const level = sampleConfidence(total)
  if (level === 'low') return '样本不足'
  if (level === 'medium') return '初步'
  return null
}

/** 胜率展示 CSS：低样本灰字；中样本弱色；高样本正常涨跌色。 */
export function winRateDisplayTone(rate: number | null | undefined, total: number): string {
  if (rate === null || rate === undefined) return 'wr-muted'
  const level = sampleConfidence(total)
  if (level === 'low') return 'wr-muted'
  if (level === 'medium') return 'wr-mid'
  if (rate >= 60) return 'wr-high'
  if (rate >= 45) return 'wr-mid'
  return 'wr-low'
}

/** StatCard tone：仅高样本才用 up/down。 */
export function winRateStatTone(rate: number | null | undefined, total: number): 'up' | 'down' | '' {
  if (rate === null || rate === undefined) return ''
  if (sampleConfidence(total) !== 'high') return ''
  if (rate >= 60) return 'up'
  if (rate < 45) return 'down'
  return ''
}

export function winRateText(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—'
  return `${rate}%`
}

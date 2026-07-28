import type { EquityCurve } from '@/shared/types/quant'

/** 复盘中心资金曲线标题（去掉「示意」）。 */
export function reviewEquityChartTitle(confidence: EquityCurve['confidence'] | undefined): string {
  if (confidence === 'estimated') return '净值估计'
  if (confidence === 'none') return '盈亏走势'
  return '盈亏走势'
}

/** 曲线 trust chip：锚定 / 估计 / 样本不足。 */
export function curveTrustLabel(confidence: EquityCurve['confidence'] | undefined): string {
  if (confidence === 'anchored') return '锚定'
  if (confidence === 'estimated') return '估计'
  return '样本不足'
}

export function curveTrustChipClass(confidence: EquityCurve['confidence'] | undefined): string {
  if (confidence === 'anchored') return 'trust-chip trust-chip-anchored'
  if (confidence === 'estimated') return 'trust-chip trust-chip-estimated'
  return 'trust-chip trust-chip-none'
}

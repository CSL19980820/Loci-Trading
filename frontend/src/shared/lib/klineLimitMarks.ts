/** K 线涨跌停 markPoint 数据。 */
import { detectLimitHit, limitLabel } from '@/shared/lib/limitBoard'
import type { OhlcBar } from '@/shared/lib/indicators'

export function buildLimitMarks(
  bars: OhlcBar[],
  dates: string[],
  stockCode: string,
  stockName?: string,
): Array<Record<string, unknown>> {
  if (!stockCode || !bars.length) return []
  const marks: Array<Record<string, unknown>> = []
  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i]
    const prev = i > 0 ? Number(bars[i - 1].close) : null
    // 只钉收盘封板；冲高回落不标「涨停」，避免和阴线打架
    const kind = detectLimitHit(bar, prev, stockCode, stockName, 'close')
    if (!kind) continue
    const y = kind === 'up' ? Number(bar.high ?? bar.close) : Number(bar.low ?? bar.close)
    if (!Number.isFinite(y)) continue
    marks.push({
      name: limitLabel(kind),
      coord: [dates[i], y],
      value: limitLabel(kind),
      symbol: 'pin',
      symbolSize: 28,
      symbolOffset: kind === 'up' ? [0, -4] : [0, 4],
      itemStyle: { color: kind === 'up' ? '#c41e3a' : '#0f6b5c' },
      label: {
        formatter: limitLabel(kind),
        color: '#fff',
        fontSize: 9,
        fontWeight: 650,
      },
    })
  }
  return marks
}

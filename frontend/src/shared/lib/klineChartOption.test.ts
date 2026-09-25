import { describe, expect, it } from 'vitest'
import { computeChartPrep } from './chartPrep'
import { buildKlineOption } from './klineChartOption'

describe('Kline scroll interaction', () => {
  const prep = computeChartPrep({ bars: [], period: 'day', indicator: 'macd', maPeriods: [] })
  const options = { prep, indicator: 'macd' as const, maPeriods: [], showBarLabels: false, zoomStart: 40, zoomEnd: 100, stockCode: '', stockName: '' }

  it('preserves standalone chart wheel and drag zoom by default', () => {
    const zoom = buildKlineOption(options).dataZoom as Record<string, unknown>[]
    expect(zoom[0]).toMatchObject({ type: 'inside', disabled: false, zoomOnMouseWheel: true, moveOnMouseMove: true, preventDefaultMouseMove: true })
  })

  it('lets embedded chart scrolling pass through while retaining the range slider', () => {
    const zoom = buildKlineOption({ ...options, scrollThrough: true }).dataZoom as Record<string, unknown>[]
    expect(zoom[0]).toMatchObject({ type: 'inside', disabled: true, zoomOnMouseWheel: false, moveOnMouseMove: false, preventDefaultMouseMove: false })
    expect(zoom[1]).toMatchObject({ type: 'slider', start: 40, end: 100, xAxisIndex: [0, 1, 2] })
    expect(zoom[1]?.disabled).not.toBe(true)
  })
})

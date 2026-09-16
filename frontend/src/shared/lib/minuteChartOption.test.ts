import { describe, expect, it } from 'vitest'

import type { MinuteBar } from '@/shared/api/quant_market'

import { readChartTokens } from './chartTokens'
import {
  buildMinuteOption,
  computeMinuteDayStats,
  computeMinutePriceAxis,
  formatMinutePxPct,
  saneMinuteAvg,
} from './minuteChartOption'
function bar(
  time: string,
  close: number,
  high: number,
  low: number,
  avg: number,
): MinuteBar {
  return {
    datetime: `2026-07-31 ${time}`,
    open: close,
    high,
    low,
    close,
    volume: 1000,
    amount: close * 1000,
    avg_price: avg,
  }
}

describe('saneMinuteAvg', () => {
  it('scales down 100x dirty avg', () => {
    expect(saneMinuteAvg(421, 4.21)).toBeCloseTo(4.21, 2)
    expect(saneMinuteAvg(4.2, 4.21)).toBeCloseTo(4.2, 2)
    expect(saneMinuteAvg(50_000, 4.21)).toBeNull()
  })
})

describe('computeMinuteDayStats', () => {
  it('finds session high/low and last avg', () => {
    const bars = [
      bar('09:31:00', 17.2, 17.25, 17.1, 17.2),
      bar('10:00:00', 17.55, 17.6, 17.4, 17.3),
      bar('14:00:00', 17.15, 17.2, 17.05, 17.28),
      bar('15:00:00', 17.44, 17.45, 17.4, 17.32),
    ]
    const stats = computeMinuteDayStats(bars)
    expect(stats).not.toBeNull()
    expect(stats!.high).toBe(17.6)
    expect(stats!.highIndex).toBe(1)
    expect(stats!.low).toBe(17.05)
    expect(stats!.lowIndex).toBe(2)
    expect(stats!.avg).toBe(17.32)
  })
})

describe('formatMinutePxPct', () => {
  it('joins price and signed pct vs prev close', () => {
    expect(formatMinutePxPct(63.6, 60.6)).toBe('63.60 +4.95%')
    expect(formatMinutePxPct(58.87, 60.6)).toBe('58.87 -2.85%')
    expect(formatMinutePxPct(59.2, null)).toBe('59.20')
  })
})

describe('computeMinutePriceAxis', () => {
  it('centers on prevClose and keeps pad for flat limit-up session', () => {
    const bars = [
      bar('09:31:00', 13.31, 13.31, 13.31, 13.31),
      bar('10:00:00', 13.3100001, 13.31, 13.31, 13.309999),
      bar('15:00:00', 13.31, 13.31, 13.31, 13.31),
    ]
    const axis = computeMinutePriceAxis(bars, 11.09)
    expect(axis).not.toBeNull()
    expect(axis!.min).toBeCloseTo(11.09 - (13.31 - 11.09), 5)
    expect(axis!.max).toBeCloseTo(11.09 + (13.31 - 11.09), 5)
  })
})

describe('buildMinuteOption', () => {
  it('marks high low avg with price+pct and keeps info-colored price line', () => {
    const bars = [
      bar('09:31:00', 17.2, 17.25, 17.1, 17.2),
      bar('10:00:00', 17.55, 17.6, 17.4, 17.3),
      bar('15:00:00', 17.44, 17.45, 17.4, 17.32),
    ]
    const option = buildMinuteOption({ bars, prevClose: 17.23 })
    const series = option.series as Array<{
      name?: string
      lineStyle?: { color?: string }
      markPoint?: { data?: Array<{ name?: string; label?: { formatter?: () => string } }> }
    }>
    const price = series.find((s) => s.name === '分时')
    const avg = series.find((s) => s.name === '均价')
    expect(price?.lineStyle?.color).toBe(readChartTokens().info)
    const names = price?.markPoint?.data?.map((d) => d.name)
    expect(names).toEqual(expect.arrayContaining(['高', '低', '现']))
    const highLabel = price?.markPoint?.data?.find((d) => d.name === '高')?.label?.formatter?.()
    const lowLabel = price?.markPoint?.data?.find((d) => d.name === '低')?.label?.formatter?.()
    expect(highLabel).toContain('17.60')
    expect(highLabel).toMatch(/\+/)
    expect(lowLabel).toContain('17.10')
    expect(lowLabel).toMatch(/-/)
    const avgLabel = avg?.markPoint?.data?.[0]?.label?.formatter?.()
    expect(avg?.markPoint?.data?.[0]).toMatchObject({ name: '均' })
    expect(avgLabel).toContain('17.32')
    expect(avgLabel).toMatch(/%/)
    const yAxis = option.yAxis as Array<{ min?: number; max?: number }>
    expect(yAxis[0]?.min).toBeLessThan(17.23)
    expect(yAxis[0]?.max).toBeGreaterThan(17.23)
  })

  it('skips high/low marks on flat limit-up and pins y-axis to prevClose', () => {
    const bars = [
      bar('09:31:00', 13.31, 13.31, 13.31, 13.31),
      bar('15:00:00', 13.31, 13.31, 13.31, 13.31),
    ]
    const option = buildMinuteOption({ bars, prevClose: 11.09 })
    const series = option.series as Array<{
      name?: string
      markPoint?: { data?: Array<{ name?: string }> }
    }>
    const price = series.find((s) => s.name === '分时')
    const names = price?.markPoint?.data?.map((d) => d.name) ?? []
    expect(names).toEqual(['现'])
    const yAxis = option.yAxis as Array<{ min?: number; max?: number }>
    expect(yAxis[0]?.min).toBeCloseTo(8.87, 2)
    expect(yAxis[0]?.max).toBeCloseTo(13.31, 2)
  })
})

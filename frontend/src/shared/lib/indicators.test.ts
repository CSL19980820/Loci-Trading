import { describe, expect, it } from 'vitest'

import {
  atr,
  bollinger,
  cci,
  kdj,
  macd,
  obv,
  resampleBars,
  roc,
  rsi,
  williamsR,
  type OhlcBar,
} from '@/shared/lib/indicators'

describe('indicators.resampleBars', () => {
  it('keeps daily bars unchanged for period=day', () => {
    const bars: OhlcBar[] = [
      {
        trade_date: '2026-07-01',
        open: 10,
        high: 11,
        low: 9.5,
        close: 10.5,
        volume: 1000,
      },
      {
        trade_date: '2026-07-02',
        open: 10.5,
        high: 11.2,
        low: 10.1,
        close: 11,
        volume: 1200,
      },
    ]
    expect(resampleBars(bars, 'day')).toHaveLength(2)
  })

  it('keeps turnover when aggregating weekly and monthly bars', () => {
    const bars: OhlcBar[] = [
      {
        trade_date: '2026-07-01',
        open: 10,
        high: 11,
        low: 9,
        close: 10.5,
        volume: 1000,
        amount: 10000,
        turnover: 0.1,
      },
      {
        trade_date: '2026-07-02',
        open: 10.5,
        high: 12,
        low: 10,
        close: 11.5,
        volume: 1200,
        amount: 13000,
        turnover: 0.2,
      },
      {
        trade_date: '2026-07-06',
        open: 11.5,
        high: 12.5,
        low: 11,
        close: 12,
        volume: 800,
        amount: 9000,
        turnover: 0.05,
      },
    ]

    const weeks = resampleBars(bars, 'week')
    expect(weeks.map((bar) => bar.trade_date)).toEqual(['2026-07-02', '2026-07-06'])
    expect(weeks[0]?.turnover).toBeCloseTo(0.3)
    expect(weeks[1]?.turnover).toBeCloseTo(0.05)
    expect(resampleBars(bars, 'month')[0]?.turnover).toBeCloseTo(0.35)
  })
})

describe('indicators.kdj', () => {
  it('waits for a complete RSV window and initializes K/D from that RSV', () => {
    const result = kdj(
      [10, 10, 10, 10],
      [0, 0, 0, 0],
      [8, 8, 8, 5],
      3,
    )

    expect(result.k.slice(0, 2)).toEqual([null, null])
    expect(result.d.slice(0, 2)).toEqual([null, null])
    expect(result.j.slice(0, 2)).toEqual([null, null])
    expect(result.k[2]).toBeCloseTo(80)
    expect(result.d[2]).toBeCloseTo(80)
    expect(result.j[2]).toBeCloseTo(80)
    expect(result.k[3]).toBeCloseTo(70)
    expect(result.d[3]).toBeCloseTo(76.6666667)
    expect(result.j[3]).toBeCloseTo(56.6666667)
  })
})

describe('indicators.common', () => {
  it('keeps RSI warmup and bounds values to 0..100', () => {
    const result = rsi([1, 2, 3, 4, 5], 3)
    expect(result.slice(0, 3)).toEqual([null, null, null])
    expect(result[3]).toBeCloseTo(100)
    expect(result.every((value) => value === null || (value >= 0 && value <= 100))).toBe(true)
  })

  it('computes OHLCV indicators with explicit missing data', () => {
    const highs = [11, 12, 13, 14]
    const lows = [9, 10, 11, 12]
    const closes = [10, 11, 12, 13]
    expect(atr(highs, lows, closes, 2)[0]).toBeNull()
    expect(atr(highs, lows, closes, 2)[2]).toBeCloseTo(2)
    expect(roc(closes, 2)[2]).toBeCloseTo(20)
    expect(williamsR(highs, lows, closes, 3)[2]).toBeCloseTo(-25)
    expect(cci(highs, lows, closes, 3)[2]).toBeCloseTo(100)
    expect(obv(closes, [100, 200, 300, 400])).toEqual([0, 200, 500, 900])
  })

  it('returns the same MACD components and BOLL band ordering', () => {
    const closes = [10, 11, 10, 12, 13, 12]
    const output = macd(closes, 2, 4, 2)
    expect(output.dif).toHaveLength(closes.length)
    const bands = bollinger(closes, 3, 2)
    const last = bands.mid.length - 1
    expect(bands.lower[last]).toBeLessThan(bands.mid[last] as number)
    expect(bands.upper[last]).toBeGreaterThan(bands.mid[last] as number)
  })
})

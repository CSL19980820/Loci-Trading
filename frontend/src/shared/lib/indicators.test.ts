import { describe, expect, it } from 'vitest'

import { resampleBars, type OhlcBar } from '@/shared/lib/indicators'

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
})

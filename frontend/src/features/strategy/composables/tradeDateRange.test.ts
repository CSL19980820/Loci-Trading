import { describe, expect, it } from 'vitest'

import {
  MAX_INCLUSIVE_DAYS,
  clampTradeDateRange,
  inclusiveDaySpan,
  isValidTradeDateRange,
  presetTradeDateRange,
  skillDateFromRange,
} from './tradeDateRange'

describe('tradeDateRange', () => {
  it('builds presets within one month', () => {
    const today = new Date(2026, 6, 31) // Jul 31
    expect(presetTradeDateRange('today', today)).toEqual(['2026-07-31', '2026-07-31'])
    expect(presetTradeDateRange('today', new Date(2026, 7, 1), '2026-07-31')).toEqual([
      '2026-07-31',
      '2026-07-31',
    ])
    expect(presetTradeDateRange('this_week', today)).toEqual(['2026-07-27', '2026-07-31'])
    expect(presetTradeDateRange('last_week', today)).toEqual(['2026-07-20', '2026-07-26'])
    expect(presetTradeDateRange('last_30', today)).toEqual(['2026-07-01', '2026-07-31'])
    expect(presetTradeDateRange('prev_month', today)).toEqual(['2026-06-01', '2026-06-30'])
    expect(inclusiveDaySpan('2026-07-01', '2026-07-31')).toBe(31)
    expect(isValidTradeDateRange(['2026-07-01', '2026-07-31'])).toBe(true)
  })

  it('clamps oversized ranges and exposes skill end date', () => {
    expect(clampTradeDateRange(['2026-06-01', '2026-07-31'])).toEqual([
      '2026-07-01',
      '2026-07-31',
    ])
    expect(isValidTradeDateRange(['2026-06-01', '2026-07-31'])).toBe(false)
    expect(skillDateFromRange(['2026-07-01', '2026-07-15'])).toBe('2026-07-15')
    expect(MAX_INCLUSIVE_DAYS).toBe(31)
  })
})

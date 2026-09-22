import { describe, expect, it } from 'vitest'
import { matchesWinRatePeriod } from './winRatePeriod'

describe('胜率周期与后端周一日期键一致', () => {
  it.each([
    ['2026-09-01', '2026-09', true],
    ['2026-08-31', '2026-09', false],
    ['2026-08-31', '2026-08-31', true],
    ['2026-09-01', '2026-08-31', true],
    ['2026-09-06', '2026-08-31', true],
    ['2026-09-07', '2026-08-31', false],
    ['2026-08-30', '2026-08-31', false],
    ['2027-01-01', '2026-12-28', true],
    ['2027-01-03', '2026-W53', true],
    ['2027-01-04', '2026-W53', false],
    ['2026-09-01', '2026-W36', true],
    ['invalid', '2026-09', false],
    ['2026-02-30', '2026-02', false],
    ['', '', false],
  ])('%s in %s is %s', (date, period, expected) => {
    expect(matchesWinRatePeriod(String(date), String(period))).toBe(expected)
  })
})

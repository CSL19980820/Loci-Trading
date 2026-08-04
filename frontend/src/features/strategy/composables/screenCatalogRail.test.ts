import { describe, expect, it } from 'vitest'

import { sampleConfidence } from '@/shared/lib/winrate'

/** 与 ScreenCatalogRail「有数才出数」一致：低样本不展示胜率数字。 */
function hasCredibleStats(sample: number, winRate: number | null): boolean {
  return sampleConfidence(sample) !== 'low' && winRate != null
}

describe('screen catalog rail stats', () => {
  it('hides noisy zero-sample stats', () => {
    expect(hasCredibleStats(0, null)).toBe(false)
    expect(hasCredibleStats(0, 50)).toBe(false)
    expect(hasCredibleStats(4, 60)).toBe(false)
  })

  it('shows win rate once sample is credible', () => {
    expect(hasCredibleStats(5, 62)).toBe(true)
    expect(hasCredibleStats(30, 48)).toBe(true)
  })
})

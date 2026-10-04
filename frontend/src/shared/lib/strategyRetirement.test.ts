import { describe, expect, it } from 'vitest'
import { BUILTIN_STRATEGY_OPTIONS, strategyLabel, strategyShortLabel } from './format'
import { strategyDisplayName } from '@/features/market/composables/pulseHomeLogic'

describe('retired strategy display and selection', () => {
  it('uses the generic unknown-strategy fallback without offering a retired strategy for new records', () => {
    expect(strategyLabel('tail-micro-right-v1')).toBe('tail-micro-right-v1')
    expect(strategyShortLabel('tail-micro-right-v1')).toBe('tail-micro-right-v1')
    expect(strategyDisplayName('tail-micro-right-v1')).toBe('自定义战法')
    expect(BUILTIN_STRATEGY_OPTIONS.some(option => option.value === 'tail-micro-right-v1')).toBe(false)
  })

  it('offers active built-in record choices with readable indicator names', () => {
    expect(BUILTIN_STRATEGY_OPTIONS.map(option => option.value)).toEqual([
      'qianlong-close-v3', 'sanyuan-tail-v1', 'yangshi-tail-v1',
      'impulse-inside-breakout-v1', 'contraction-rebreakout-v1',
    ])
    expect(strategyLabel('impulse-inside-breakout-v1')).toBe('大阳三日缩量突破')
    expect(strategyShortLabel('impulse-inside-breakout-v1')).toBe('大阳三日缩量突破')
    expect(BUILTIN_STRATEGY_OPTIONS).toContainEqual({
      label: '大阳三日缩量突破', value: 'impulse-inside-breakout-v1',
    })
  })
})

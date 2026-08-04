import { describe, expect, it } from 'vitest'

import { boardLimitRatio, detectLimitHit } from './limitBoard'

describe('limitBoard', () => {
  it('主板 10%、创业 20%、ST 5%', () => {
    expect(boardLimitRatio('600000')).toBe(0.1)
    expect(boardLimitRatio('000001')).toBe(0.1)
    expect(boardLimitRatio('300750')).toBe(0.2)
    expect(boardLimitRatio('688981')).toBe(0.2)
    expect(boardLimitRatio('600000', 'ST示例')).toBe(0.05)
  })

  it('detects limit up/down near threshold', () => {
    const prev = 10
    expect(detectLimitHit({ high: 11, low: 10.1, close: 11 }, prev, '600000')).toBe('up')
    expect(detectLimitHit({ high: 9.9, low: 9, close: 9 }, prev, '600000')).toBe('down')
    expect(detectLimitHit({ high: 10.5, low: 9.8, close: 10.2 }, prev, '600000')).toBe(null)
    expect(detectLimitHit({ high: 12, low: 11.5, close: 12 }, prev, '300750')).toBe('up')
  })

  it('地天板仍判跌停（开/低触板、收阳）', () => {
    const prev = 21.21
    expect(
      detectLimitHit({ high: 22.39, low: 19.09, close: 22.09 }, prev, '000048'),
    ).toBe('down')
  })

  it('close 模式不把冲高回落当成涨停', () => {
    const prev = 27.72
    const bar = { high: 30.49, low: 26.46, close: 26.5 }
    expect(detectLimitHit(bar, prev, '002674')).toBe('up')
    expect(detectLimitHit(bar, prev, '002674', null, 'close')).toBe(null)
  })
})

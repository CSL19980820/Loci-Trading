import { describe, expect, it, vi } from 'vitest'
import { formatTokens, quotaToUiValue, uiValueToQuota } from '../lib/adminFormat'

describe('adminFormat - 配额与格式转换', () => {
  it('配额 -1 与数字的双向转换', () => {
    // quotaToUiValue
    expect(quotaToUiValue(-1)).toEqual({ unlimited: true, value: 0 })
    expect(quotaToUiValue(undefined)).toEqual({ unlimited: true, value: 0 })
    expect(quotaToUiValue(50000)).toEqual({ unlimited: false, value: 50000 })
    expect(quotaToUiValue(0)).toEqual({ unlimited: false, value: 0 })

    // uiValueToQuota
    expect(uiValueToQuota(true, 50000)).toBe(-1)
    expect(uiValueToQuota(true, 0)).toBe(-1)
    expect(uiValueToQuota(false, 300000)).toBe(300000)
    expect(uiValueToQuota(false, 0)).toBe(0)
    expect(uiValueToQuota(false, -10)).toBe(0)
  })

  it('formatTokens 格式化规则', () => {
    expect(formatTokens(-1)).toBe('不限')
    expect(formatTokens(null)).toBe('0')
    expect(formatTokens(undefined)).toBe('0')
    expect(formatTokens(500)).toBe('500')
    expect(formatTokens(1500)).toBe('1.5k')
    expect(formatTokens(300000)).toBe('300.0k')
    expect(formatTokens(1200000)).toBe('1.2M')
  })
})

import { describe, expect, it } from 'vitest'

import { validateResearchBacktestForm } from './researchBacktestForm'

const validInput = {
  strategy: 'sanyuan-tail-v1',
  range: ['2024-01-02', '2025-12-31'],
  trainRange: ['2024-01-02', '2024-12-31'],
  oosRange: ['2025-01-01', '2025-12-31'],
  historicalUniverseId: 'ashare-2024-2025',
  strictPit: true,
}

describe('validateResearchBacktestForm', () => {
  it('accepts a complete, predeclared strict PIT study', () => {
    expect(validateResearchBacktestForm(validInput)).toBe('')
  })

  it('rejects strict PIT before any request when a required input is absent', () => {
    expect(validateResearchBacktestForm({ ...validInput, historicalUniverseId: '' }))
      .toContain('严格 PIT 模式要求')
    expect(validateResearchBacktestForm({ ...validInput, trainRange: [], oosRange: [] }))
      .toContain('严格 PIT 模式要求')
  })

  it('rejects a research run without a predeclared train/OOS split', () => {
    expect(validateResearchBacktestForm({
      ...validInput,
      strictPit: false,
      historicalUniverseId: '',
      trainRange: [],
      oosRange: [],
    })).toContain('未声明 OOS')
  })

  it('rejects an incomplete, overlapping, or out-of-range train/OOS declaration', () => {
    expect(validateResearchBacktestForm({ ...validInput, oosRange: [] }))
      .toBe('训练区间与 OOS 区间必须成对填写')
    expect(validateResearchBacktestForm({ ...validInput, oosRange: ['2024-12-31', '2025-12-31'] }))
      .toBe('OOS 必须严格晚于训练区间，不能重叠或倒序')
    expect(validateResearchBacktestForm({ ...validInput, trainRange: ['2023-12-29', '2024-12-31'] }))
      .toBe('训练区间和 OOS 区间必须完全位于回测总区间内')
  })
})

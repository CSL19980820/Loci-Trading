import { describe, expect, it } from 'vitest'

import { candidateDecisions, decimal, percent } from './assistantArtifacts'

describe('assistantArtifacts', () => {
  it('normalizes candidate evidence without inventing missing metrics', () => {
    const [candidate] = candidateDecisions({
      candidates: [{
        code: '600000', name: '浦发银行', decision: '精选', score: 91, reason: '量价配合',
        occurred_on: '2026-08-01', timing: '尾盘确认',
        evidence: { invalidation: '跌破 MA20', close: 12, pct_chg: 1.25, ma5: 11.4, ma20: 10, volume_ratio: 1.8 },
      }],
    })

    expect(candidate).toMatchObject({
      code: '600000', name: '浦发银行', decision: '精选', reason: '量价配合', timing: '尾盘确认',
      invalidation: '跌破 MA20', pctChange: 1.25, volumeRatio: 1.8,
    })
    expect(candidate?.ma5Deviation).toBeCloseTo(5.263, 2)
    expect(candidate?.ma20Deviation).toBe(20)
  })

  it('keeps unavailable numbers visibly unavailable', () => {
    const [candidate] = candidateDecisions({ candidates: [{ code: '600000', decision: '观察' }] })

    expect(candidate).toMatchObject({ code: '600000', name: '未命名候选', ma5Deviation: undefined, volumeRatio: undefined })
    expect(percent(undefined)).toBe('—')
    expect(decimal(undefined)).toBe('—')
  })
})

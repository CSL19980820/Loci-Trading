import { describe, expect, it } from 'vitest'

import {
  MEMORY_QUOTAS,
  groupMemoriesByTarget,
  joinMemoryDocument,
  memoryUsagePct,
} from './assistantMemoryQuotas'

describe('assistantMemoryQuotas', () => {
  it('clamps usage percent to 0–100', () => {
    expect(memoryUsagePct(0, MEMORY_QUOTAS.user)).toBe(0)
    expect(memoryUsagePct(700, MEMORY_QUOTAS.user)).toBe(32)
    expect(memoryUsagePct(9999, MEMORY_QUOTAS.user)).toBe(100)
    expect(memoryUsagePct(-1, 0)).toBe(0)
  })

  it('groups memories by target without mutating order within buckets', () => {
    const grouped = groupMemoriesByTarget([
      { id: '1', target: 'memory', content: 'a' },
      { id: '2', target: 'user', content: 'b' },
      { id: '3', target: 'memory', content: 'c' },
    ])
    expect(grouped.user.map((row) => row.id)).toEqual(['2'])
    expect(grouped.memory.map((row) => row.id)).toEqual(['1', '3'])
  })

  it('joins memory rows into one markdown document', () => {
    expect(joinMemoryDocument([
      { id: '1', target: 'user', content: '甲' },
      { id: '2', target: 'user', content: '乙' },
    ])).toBe('甲\n\n乙')
  })
})

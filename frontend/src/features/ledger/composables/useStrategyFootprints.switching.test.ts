import { flushPromises } from '@vue/test-utils'
import { effectScope, nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { listCandidates } from '@/shared/api/palace'
import { getJobs, getStrategies } from '@/shared/api/quant'
import type { Candidate } from '@/shared/types/palace'
import { useStrategyFootprints } from './useStrategyFootprints'

vi.mock('@/shared/api/palace', () => ({ listCandidates: vi.fn() }))
vi.mock('@/shared/api/quant', () => ({ getStrategies: vi.fn().mockResolvedValue([]), getJobs: vi.fn().mockResolvedValue([]) }))
vi.mock('@/shared/stores/user', () => ({ useUserStore: () => ({ user: { id: 'batch-switch-test', tenant_id: 'test' } }) }))

function candidate(code: string): Candidate {
  return {
    id: code, code, name: code, date: '2026-09-30', pool_id: 'fixture@2026-09-30',
    rule_version: 'fixture', decision: '精选', reason: 'test', source: 'api:screen',
    score: 90, timing: 'next_open', created_at: '2026-09-30 15:30:00', evidence: {},
  }
}

describe('strategy footprints while switching stocks', () => {
  it('clears old stock signals immediately and ignores responses from a stock already left', async () => {
    let resolveSecond!: (rows: Candidate[]) => void
    let resolveThird!: (rows: Candidate[]) => void
    const second = new Promise<Candidate[]>(resolve => { resolveSecond = resolve })
    const third = new Promise<Candidate[]>(resolve => { resolveThird = resolve })
    vi.mocked(listCandidates).mockImplementation(({ code } = {}) => {
      if (code === '000002') return second
      if (code === '000003') return third
      return Promise.resolve([candidate('000001')])
    })
    const code = ref('000001')
    const scope = effectScope()
    const footprints = scope.run(() => useStrategyFootprints(code))!
    try {
      await flushPromises()
      expect(footprints.candidates.value.map(row => row.code)).toEqual(['000001'])
      code.value = '000002'
      await nextTick()
      expect(footprints.candidates.value).toEqual([])
      expect(footprints.loading.value).toBe(true)

      code.value = '000003'
      await nextTick()
      resolveSecond([candidate('000002')])
      await flushPromises()
      expect(footprints.candidates.value).toEqual([])
      expect(footprints.loading.value).toBe(true)

      resolveThird([candidate('000003')])
      await flushPromises()
      expect(footprints.candidates.value.map(row => row.code)).toEqual(['000003'])
      expect(footprints.loading.value).toBe(false)
      expect(getStrategies).toHaveBeenCalledTimes(1)
      expect(getJobs).toHaveBeenCalledTimes(1)
    } finally { scope.stop() }
  })
})

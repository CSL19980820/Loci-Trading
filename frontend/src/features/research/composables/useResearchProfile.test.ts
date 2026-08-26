import { effectScope } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ResearchCatalog, ResearchRunResult } from '@/shared/types/quant'

const api = vi.hoisted(() => ({
  createResearchRun: vi.fn(),
  getResearchCatalog: vi.fn(),
  getResearchProfile: vi.fn(),
  getResearchRun: vi.fn(),
  resumeResearchRun: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

import { useResearchProfile } from './useResearchProfile'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const catalog = { dimensions: [] } as unknown as ResearchCatalog
const runResult = {
  run: { id: 'RR-new', status: 'completed', stages: {} },
  profile: { code: '000001', dimensions: [] },
} as unknown as ResearchRunResult

describe('useResearchProfile', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getResearchCatalog.mockResolvedValue(catalog)
    api.getResearchRun.mockResolvedValue(runResult)
  })

  it('does not let a stale profile response replace a later run read', async () => {
    const pendingProfile = deferred<ResearchRunResult['profile']>()
    api.getResearchProfile.mockReturnValue(pendingProfile.promise)
    const scope = effectScope()
    const state = scope.run(() => useResearchProfile())!

    const profileRequest = state.loadProfile('600519', 'standard')
    await vi.waitFor(() => expect(api.getResearchProfile).toHaveBeenCalledOnce())
    await state.loadRun('RR-new')
    pendingProfile.resolve({ code: '600519', dimensions: [] } as never)
    await profileRequest

    expect(state.profile.value?.code).toBe('000001')
    expect(state.activeRun.value?.id).toBe('RR-new')
    scope.stop()
  })
})

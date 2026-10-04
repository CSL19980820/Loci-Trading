import { useQuery } from '@pinia/colada'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { listCandidates } from '@/shared/api/palace'
import { useCandidatesQuery, type CandidatesFilter } from './useCandidatesQuery'

vi.mock('@pinia/colada', () => ({
  useQuery: vi.fn(() => ({ data: ref([]), isPending: ref(false), error: ref(null), refetch: vi.fn() })),
}))
vi.mock('@/shared/api/palace', () => ({ listCandidates: vi.fn().mockResolvedValue([]) }))

function options() {
  return vi.mocked(useQuery).mock.calls.at(-1)![0] as unknown as {
    key: () => readonly unknown[]
    query: () => Promise<unknown>
  }
}

describe('candidate list query history scope', () => {
  beforeEach(() => vi.clearAllMocks())

  it('keeps the default list free of historical backfills', async () => {
    useCandidatesQuery()
    await options().query()
    expect(vi.mocked(listCandidates)).toHaveBeenCalledWith(expect.objectContaining({ include_backfill: false, slim: true }))
  })

  it('separates cache keys and API parameters when toggling the history scope', async () => {
    const filters = ref<CandidatesFilter>({ strategy: 'fixture-yang', decision: '精选', include_backfill: false })
    useCandidatesQuery(filters)
    const query = options()
    const liveKey = query.key()
    filters.value.include_backfill = true
    expect(query.key()).not.toEqual(liveKey)
    await query.query()
    expect(vi.mocked(listCandidates)).toHaveBeenLastCalledWith(expect.objectContaining({
      strategy: 'fixture-yang', decision: '精选', include_backfill: true,
    }))
    filters.value.include_backfill = false
    expect(query.key()).toEqual(liveKey)
    await query.query()
    expect(vi.mocked(listCandidates)).toHaveBeenLastCalledWith(expect.objectContaining({ include_backfill: false }))
  })
})

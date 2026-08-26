import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

import { usePalaceStore } from '@/shared/stores/palace'
import { getTimeline } from '@/shared/api/palace'
import type { TimelineEvent } from '@/shared/types/palace'

vi.mock('@/shared/api/palace', () => ({
  getReviews: vi.fn(),
  getTimeline: vi.fn(),
}))

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function archiveCandidatesRoute(code: string): RouteLocationNormalizedLoaded {
  return {
    name: 'archive',
    params: { code },
    query: { view: 'candidates' },
    meta: {},
  } as unknown as RouteLocationNormalizedLoaded
}

function timeline(code: string): TimelineEvent[] {
  return [{ id: code, date: '2026-07-31', created_at: '', type: 'candidate', label: code, detail: {} }]
}

describe('usePalaceStore archive loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('keeps the latest archive timeline when an earlier archive request returns late', async () => {
    const a = deferred<TimelineEvent[]>()
    const b = deferred<TimelineEvent[]>()
    vi.mocked(getTimeline).mockImplementation((code) => (code === 'A' ? a.promise : b.promise))
    const store = usePalaceStore()

    const loadingA = store.loadRoute(archiveCandidatesRoute('A'), true)
    const loadingB = store.loadRoute(archiveCandidatesRoute('B'), true)

    b.resolve(timeline('B'))
    await loadingB
    expect(store.selectedCode).toBe('B')
    expect(store.selectedTimeline).toEqual(timeline('B'))

    a.resolve(timeline('A'))
    await loadingA

    expect(store.selectedCode).toBe('B')
    expect(store.selectedTimeline).toEqual(timeline('B'))
  })

  it('keeps the latest archive state when an earlier archive request fails late', async () => {
    const a = deferred<TimelineEvent[]>()
    const b = deferred<TimelineEvent[]>()
    vi.mocked(getTimeline).mockImplementation((code) => (code === 'A' ? a.promise : b.promise))
    const store = usePalaceStore()

    const loadingA = store.loadRoute(archiveCandidatesRoute('A'), true)
    const loadingB = store.loadRoute(archiveCandidatesRoute('B'), true)

    b.resolve(timeline('B'))
    await loadingB
    a.reject(new Error('A timeline failed'))
    await loadingA

    expect(store.selectedCode).toBe('B')
    expect(store.selectedTimeline).toEqual(timeline('B'))
    expect(store.error).toBe('')
  })

  it('exposes a current archive request failure to the view', async () => {
    vi.mocked(getTimeline).mockRejectedValue(new Error('B timeline failed'))
    const store = usePalaceStore()

    await store.loadRoute(archiveCandidatesRoute('B'), true)

    expect(store.error).toContain('B timeline failed')
  })
})

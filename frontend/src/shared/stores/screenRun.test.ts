import { createPinia, setActivePinia } from 'pinia'
import { watch } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cancelScreenRun, getScreenRunStatus, startScreenRun } from '@/shared/api/quant'
import type { ScreenResult, ScreenRunSlot, ScreenRunStatus } from '@/shared/types/quant'
import { useScreenRunStore } from './screenRun'
import { toast } from 'vue-sonner'

vi.mock('@/shared/api/quant', () => ({ getScreenRunStatus: vi.fn(), startScreenRun: vi.fn(), cancelScreenRun: vi.fn() }))
vi.mock('vue-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function slot(strategy: string, overrides: Partial<ScreenRunSlot> = {}): ScreenRunSlot {
  return { strategy, status: 'running', phase: 'scan', percent: 20, message: '扫描', trade_date: '2026-10-01',
    log: ['开始选股'], error: '', started_at: 1, updated_at: 2, result_omitted: true, ...overrides }
}
function snapshot(...slots: ScreenRunSlot[]): ScreenRunStatus {
  return { ...slots[0]!, runs: Object.fromEntries(slots.map(item => [item.strategy, item])), max_concurrent_runs: 4 }
}
function result(code: string): ScreenResult {
  return { strategy: 'a', trade_date: '2026-10-01', picks: [{ code, factors: {}, open: 10, close: 11 }], recorded: { written: 1 } } as ScreenResult
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

let store: ReturnType<typeof useScreenRunStore>
beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  setActivePinia(createPinia())
  store = useScreenRunStore()
})
afterEach(() => { store.$dispose(); vi.useRealTimers() })

describe('shared screen progress reads', () => {
  it('shares concurrent hydration and does not start a second request while a poll is in flight', async () => {
    const first = deferred<ScreenRunStatus>()
    const second = deferred<ScreenRunStatus>()
    vi.mocked(getScreenRunStatus).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const hydration = [store.hydrate(), store.hydrate(), store.hydrate()]
    expect(getScreenRunStatus).toHaveBeenCalledTimes(1)
    expect(getScreenRunStatus).toHaveBeenCalledWith({ view: 'progress' })
    first.resolve(snapshot(slot('a')))
    await Promise.all(hydration)
    expect(getScreenRunStatus).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1200)
    expect(getScreenRunStatus).toHaveBeenCalledTimes(2)
    store.ensurePoll()
    store.ensurePoll()
    expect(getScreenRunStatus).toHaveBeenCalledTimes(2)
    const hydrationDuringPoll = store.hydrate()
    expect(getScreenRunStatus).toHaveBeenCalledTimes(2)
    second.resolve(snapshot(slot('a', { percent: 40, updated_at: 3 })))
    await hydrationDuringPoll
  })

  it('reads a completed result once and preserves result, slot, track and unchanged dictionary references', async () => {
    const done = slot('a', { status: 'done', phase: 'done', percent: 100 })
    let active = slot('b')
    const body = result('000001')
    vi.mocked(getScreenRunStatus).mockImplementation(async options => options?.strategy
      ? { ...done, result: body, result_omitted: false }
      : structuredClone(snapshot(done, active)))
    await store.hydrate()
    await store.ensureResultFor('a')
    await vi.advanceTimersByTimeAsync(0)
    const stableSlot = store.runFor('a')
    const stableResult = store.resultFor('a')
    const stableTrack = store.tracks.b
    const observer = vi.fn()
    const stop = watch(() => store.resultFor('a'), observer)
    try {
      active = slot('b', { percent: 60, updated_at: 3 })
      vi.setSystemTime(Date.now() + 1200)
      await store.hydrate()
      expect(store.percentFor('b')).toBe(60)
      expect(store.runFor('a')).toBe(stableSlot)
      expect(store.resultFor('a')).toBe(stableResult)
      expect(store.tracks.b).toBe(stableTrack)
      expect(observer).not.toHaveBeenCalled()
      const stableDictionary = store.runs
      vi.setSystemTime(Date.now() + 1200)
      await store.hydrate()
      expect(store.runs).toBe(stableDictionary)
      expect(vi.mocked(getScreenRunStatus).mock.calls.filter(([options]) => options?.strategy === 'a')).toHaveLength(1)
    } finally { stop() }
  })

  it('never writes an old completed result over a newly started run', async () => {
    const old = slot('a', { status: 'done', percent: 100 })
    const oldBody = deferred<ScreenRunStatus>()
    const fresh = slot('a', { started_at: 10, updated_at: 10 })
    vi.mocked(getScreenRunStatus).mockImplementation(options => options?.strategy ? oldBody.promise : Promise.resolve(snapshot(old)))
    await store.hydrate()
    const restoring = store.ensureResultFor('a')
    const newProgress = deferred<ScreenRunStatus>()
    vi.mocked(getScreenRunStatus).mockImplementation(options => options?.strategy
      ? Promise.resolve({ ...fresh, status: 'done', updated_at: 11, result_omitted: false, result: result('000002') })
      : newProgress.promise)
    vi.mocked(startScreenRun).mockResolvedValue(fresh)
    expect(await store.start({ strategy: 'a' })).toBe('started')
    oldBody.resolve({ ...old, result_omitted: false, result: result('000001') })
    await restoring
    await vi.advanceTimersByTimeAsync(0)
    expect(store.isRunning('a')).toBe(true)
    expect(store.resultFor('a')).toBeNull()
    newProgress.resolve(snapshot({ ...fresh, status: 'done', updated_at: 11 }))
    await vi.advanceTimersByTimeAsync(0)
    expect(store.resultFor('a')?.picks[0]?.code).toBe('000002')
  })

  it('retries a failed terminal result on the next light poll and stops after successful loading', async () => {
    const done = slot('a', { status: 'done', percent: 100 })
    let attempts = 0
    vi.mocked(getScreenRunStatus).mockImplementation(async options => {
      if (!options?.strategy) return snapshot(done)
      if (++attempts === 1) throw new Error('temporary read failure')
      return { ...done, result_omitted: false, result: result('000001') }
    })
    await store.hydrate()
    await store.ensureResultFor('a')
    await vi.advanceTimersByTimeAsync(0)
    expect(store.resultFor('a')).toBeNull()
    await vi.advanceTimersByTimeAsync(1200)
    expect(store.resultFor('a')?.picks[0]?.code).toBe('000001')
    expect(attempts).toBe(2)
    const requests = vi.mocked(getScreenRunStatus).mock.calls.length
    await vi.advanceTimersByTimeAsync(3600)
    expect(getScreenRunStatus).toHaveBeenCalledTimes(requests)
  })

  it('continues reading another completed result when the only running strategy is cancelled', async () => {
    const done = slot('b', { status: 'done', percent: 100 })
    const oldResult = deferred<ScreenRunStatus>()
    let requests = 0
    vi.mocked(getScreenRunStatus).mockImplementation(options => {
      if (options?.strategy) return ++requests === 1 ? oldResult.promise : Promise.resolve({ ...done, result_omitted: false, result: result('000002') })
      return Promise.resolve(snapshot(slot('a'), done))
    })
    vi.mocked(cancelScreenRun).mockResolvedValue({ cancelled: true, status: 'running', strategy: 'a', percent: 20 })
    await store.hydrate()
    const restoring = store.ensureResultFor('b')
    await store.abandon('a')
    await vi.advanceTimersByTimeAsync(0)
    expect(store.runFor('a')).toBeNull()
    expect(store.resultFor('b')?.picks[0]?.code).toBe('000002')
    oldResult.resolve({ ...done, result_omitted: false, result: result('000001') })
    await restoring
    await vi.advanceTimersByTimeAsync(0)
    expect(store.resultFor('b')?.picks[0]?.code).toBe('000002')
  })

  it('keeps old servers that return full aggregate results compatible', async () => {
    const done = slot('a', { status: 'done', result: result('000001') })
    delete done.result_omitted
    vi.mocked(getScreenRunStatus).mockResolvedValue(snapshot(done))
    await store.hydrate()
    expect(store.resultFor('a')?.picks[0]?.code).toBe('000001')
    expect(getScreenRunStatus).toHaveBeenCalledTimes(1)
  })

  it('does not fan out full reads for 64 historical completed slots and shares a selected result request', async () => {
    const history = Array.from({ length: 64 }, (_, index) => slot(`history-${index}`, { status: 'done', percent: 100 }))
    const selected = deferred<ScreenRunStatus>()
    vi.mocked(getScreenRunStatus).mockImplementation(options => options?.strategy ? selected.promise : Promise.resolve(snapshot(...history)))
    await Promise.all([store.hydrate(), store.hydrate(), store.hydrate()])
    await vi.advanceTimersByTimeAsync(2400)
    expect(getScreenRunStatus).toHaveBeenCalledTimes(1)
    const consumers = [store.ensureResultFor('history-44'), store.ensureResultFor('history-44')]
    expect(getScreenRunStatus).toHaveBeenCalledTimes(2)
    selected.resolve({ ...history[44]!, result_omitted: false, result: result('000044') })
    await Promise.all(consumers)
    await store.ensureResultFor('history-44')
    expect(getScreenRunStatus).toHaveBeenCalledTimes(2)
    expect(store.resultFor('history-44')?.picks[0]?.code).toBe('000044')
  })

  it('hydrates a missing selected slot before recovering its result', async () => {
    const done = slot('a', { status: 'done', percent: 100 })
    vi.mocked(getScreenRunStatus).mockImplementation(async options => options?.strategy
      ? { ...done, result_omitted: false, result: result('000001') }
      : snapshot(done))
    await store.ensureResultFor('a')
    expect(getScreenRunStatus).toHaveBeenCalledTimes(2)
    expect(vi.mocked(getScreenRunStatus).mock.calls.map(([options]) => options)).toEqual([{ view: 'progress' }, { strategy: 'a' }])
    expect(store.resultFor('a')?.picks[0]?.code).toBe('000001')
  })

  it('notifies a newly completed run once using the full result receipt', async () => {
    let progress = slot('a')
    vi.mocked(getScreenRunStatus).mockImplementation(async options => options?.strategy
      ? { ...progress, result_omitted: false, result: result('000001') }
      : snapshot(progress))
    await store.hydrate()
    progress = slot('a', { status: 'done', percent: 100, updated_at: 3 })
    vi.setSystemTime(Date.now() + 1200)
    await store.hydrate()
    await vi.advanceTimersByTimeAsync(0)
    expect(toast.success).toHaveBeenCalledTimes(1)
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('入库 1 条'))
    await store.hydrate()
    expect(toast.success).toHaveBeenCalledTimes(1)
    expect(vi.mocked(getScreenRunStatus).mock.calls.filter(([options]) => options?.strategy)).toHaveLength(1)
  })

  it('reuses a recent progress sample across sequential page mounts but forces a read for a missing selection', async () => {
    vi.mocked(getScreenRunStatus).mockResolvedValue(snapshot(slot('a')))
    await store.hydrate()
    await store.hydrate()
    expect(getScreenRunStatus).toHaveBeenCalledTimes(1)
    const done = slot('b', { status: 'done', percent: 100 })
    vi.mocked(getScreenRunStatus).mockImplementation(async options => options?.strategy
      ? { ...done, result_omitted: false, result: result('000002') }
      : snapshot(slot('a'), done))
    await store.ensureResultFor('b')
    expect(getScreenRunStatus).toHaveBeenCalledTimes(3)
    expect(store.resultFor('b')?.picks[0]?.code).toBe('000002')
  })
})

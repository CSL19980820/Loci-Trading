import { shallowMount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, ref, watch } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getScreenRunStatus } from '@/shared/api/quant'
import { useScreenRunStore } from '@/shared/stores/screenRun'
import type { ScreenResult, ScreenRunSlot, ScreenRunStatus } from '@/shared/types/quant'
import ScreenRunPanel from './ScreenRunPanel.vue'

vi.mock('@/shared/api/quant', () => ({ getScreenRunStatus: vi.fn(), startScreenRun: vi.fn(), cancelScreenRun: vi.fn() }))
vi.mock('vue-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ path: '/screen-history' }) }))

const SLUG = 'qianlong-close-v3'
let store: ReturnType<typeof useScreenRunStore>
let wrapper: VueWrapper | undefined

function result(range = false): ScreenResult {
  return {
    strategy: SLUG, strategy_revision: 'builtin:qianlong-close-v3.3', entry_timing: 'next_open',
    trade_date: '2026-09-30', universe_size: 1200, elapsed_seconds: 8.5,
    params: {}, effective_params: {}, picks: [], watch_picks: [],
    ...(range ? { range: { start: '2026-09-29', end: '2026-09-30', trading_days: 2, days: [], written_total: 0 } } : {}),
  }
}

function slot(overrides: Partial<ScreenRunSlot> = {}): ScreenRunSlot {
  return {
    strategy: SLUG, status: 'done', phase: 'done', percent: 100, message: '完成',
    trade_date: '2026-09-30', log: [], error: '', started_at: 1000, updated_at: 1120,
    result_omitted: true, ...overrides,
  }
}

function snapshot(selected: ScreenRunSlot): ScreenRunStatus {
  return { ...selected, runs: { [SLUG]: selected }, max_concurrent_runs: 3 }
}

function mountFlow() {
  const Harness = defineComponent({
    setup() {
      // 与选股页一致：ref 会代理结果，store 的 shallowRef 保留原始对象。
      const lastResult = ref<ScreenResult | null>(null)
      watch(() => store.resultFor(SLUG), value => { if (value?.picks) lastResult.value = value }, { immediate: true })
      return () => h(ScreenRunPanel, {
        kind: 'engine', selectedName: '潜龙出海', snap: store.runFor(SLUG),
        running: store.isRunning(SLUG), percent: store.percentFor(SLUG), lastResult: lastResult.value,
        skillBusy: false, skillLog: [], skillRun: null, skillReply: '',
      })
    },
  })
  wrapper = shallowMount(Harness, { global: { renderStubDefaultSlot: true, stubs: { ScreenRunPanel: false } } })
  return wrapper
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  setActivePinia(createPinia())
  store = useScreenRunStore()
})

afterEach(() => { wrapper?.unmount(); store.$dispose(); vi.useRealTimers() })

describe('completed screen task elapsed time', () => {
  it.each([false, true])('restores total and stage times from completed %s-range result and preserves them across progress reads', async range => {
    const done = slot()
    vi.mocked(getScreenRunStatus).mockImplementation(async options => options?.strategy
      ? { ...done, result_omitted: false, result: result(range) }
      : structuredClone(snapshot(done)))
    const panel = mountFlow()
    await store.ensureResultFor(SLUG)
    await vi.advanceTimersByTimeAsync(0)
    expect(panel.get('.run-results__hint').text()).toContain('总用时 120.0s · 选股阶段 8.5s')
    const restored = store.resultFor(SLUG)
    await store.hydrate(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(store.resultFor(SLUG)).toBe(restored)
    expect(panel.get('.run-results__hint').text()).toContain('总用时 120.0s · 选股阶段 8.5s')
    expect(restored?.elapsed_seconds).toBe(8.5)
  })

  it.each([
    { started_at: undefined }, { updated_at: undefined }, { started_at: 0 },
    { updated_at: 999 }, { updated_at: Number.POSITIVE_INFINITY },
  ])('does not claim total elapsed time for an invalid timestamp pair %j', async timestamps => {
    const done = slot(timestamps)
    vi.mocked(getScreenRunStatus).mockImplementation(async options => options?.strategy
      ? { ...done, result_omitted: false, result: result() }
      : snapshot(done))
    const panel = mountFlow()
    await store.ensureResultFor(SLUG)
    await vi.advanceTimersByTimeAsync(0)
    expect(panel.get('.run-results__hint').text()).toContain('选股阶段 8.5s')
    expect(panel.get('.run-results__hint').text()).not.toContain('总用时')
  })

  it('does not attach a new run total to the previous result while the new completed result is still loading', async () => {
    let current = slot()
    vi.mocked(getScreenRunStatus).mockImplementation(async options => options?.strategy
      ? { ...current, result_omitted: false, result: result() }
      : snapshot(current))
    const panel = mountFlow()
    await store.ensureResultFor(SLUG)
    await vi.advanceTimersByTimeAsync(0)
    current = slot({ status: 'running', started_at: 1200, updated_at: 1210 })
    await store.hydrate(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(panel.get('.run-results__hint').text()).not.toContain('总用时')
    current = slot({ started_at: 1200, updated_at: 1450 })
    vi.mocked(getScreenRunStatus).mockImplementation(options => options?.strategy
      ? new Promise(() => {})
      : Promise.resolve(snapshot(current)))
    await store.hydrate(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(panel.get('.run-results__hint').text()).toContain('选股阶段 8.5s')
    expect(panel.get('.run-results__hint').text()).not.toContain('250.0s')
    expect(panel.get('.run-results__hint').text()).not.toContain('总用时')
  })
})

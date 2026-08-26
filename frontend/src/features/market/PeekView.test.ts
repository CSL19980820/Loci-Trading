import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getLiveTape: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)
vi.mock('@/shared/composables/useLivePolling', () => ({
  useLivePolling: vi.fn((opts: { tick: () => void | Promise<void> }) => ({
    refreshOnce: opts.tick,
  })),
}))

import PeekView from './PeekView.vue'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function stubViewport(width: number, height: number): void {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height })
}

describe('PeekView request lifecycle', () => {
  afterEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
    delete (window as unknown as { pywebview?: unknown }).pywebview
    delete document.documentElement.dataset.peekPhase
    delete document.documentElement.dataset.peekEdge
    document.getElementById('boot-splash')?.remove()
    stubViewport(1024, 768)
  })

  it('leaves boot splash dismissal to the shared startup lifecycle', async () => {
    const splash = document.createElement('div')
    splash.id = 'boot-splash'
    document.body.appendChild(splash)
    api.getLiveTape.mockResolvedValue({
      indices: [],
      as_of: '2026-08-01 10:00:00',
      error: '',
      title: 'Loci · 行情',
    })

    const wrapper = mount(PeekView)
    await flushPromises()

    expect(splash.isConnected).toBe(true)
    wrapper.unmount()
  })

  it('does not let a pending initial quote update the document title after unmount', async () => {
    const pending = deferred<{
      indices: []
      as_of: string
      error: string
      title: string
    }>()
    api.getLiveTape.mockReturnValue(pending.promise)
    document.title = 'before-peek'

    const wrapper = mount(PeekView)
    expect(api.getLiveTape).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    pending.resolve({
      indices: [],
      as_of: '2026-08-01 10:00:00',
      error: '',
      title: 'stale-quote',
    })
    await flushPromises()

    expect(document.title).toBe('before-peek')
  })

  it('keeps opaque free UI when host says collapsed but window is still free-sized', async () => {
    // 复现：desktop.json peek_collapsed=true + create_window(340,340) → 旧逻辑白方块
    stubViewport(340, 340)
    api.getLiveTape.mockResolvedValue({
      indices: [{ code: '000001', label: '上证', pct: -0.5, price: 3000 }],
      as_of: '2026-08-01 10:00:00',
      error: '',
      title: 'Loci · 行情',
    })
    ;(window as unknown as { pywebview: { api: Record<string, unknown> } }).pywebview = {
      api: {
        peek_get_state: () => ({ phase: 'collapsed', edge: 'right' }),
        peek_pointer_enter: () => undefined,
        peek_pointer_leave: () => undefined,
        peek_close: () => undefined,
      },
    }

    const wrapper = mount(PeekView)
    await flushPromises()

    expect(wrapper.find('.peek--ghost').exists()).toBe(false)
    expect(wrapper.find('.peek-kicker').text()).toBe('盘面')
    expect(document.documentElement.dataset.peekPhase).toBe('free')

    wrapper.unmount()
  })

  it('shows tip ghost only when collapsed and viewport is tip-sized', async () => {
    stubViewport(22, 22)
    api.getLiveTape.mockResolvedValue({
      indices: [],
      as_of: '2026-08-01 10:00:00',
      error: '',
      title: 'Loci · 行情',
    })
    ;(window as unknown as { pywebview: { api: Record<string, unknown> } }).pywebview = {
      api: {
        peek_get_state: () => ({ phase: 'collapsed', edge: 'right' }),
        peek_pointer_enter: () => undefined,
        peek_pointer_leave: () => undefined,
        peek_close: () => undefined,
      },
    }

    const wrapper = mount(PeekView)
    await flushPromises()

    expect(wrapper.find('.peek--ghost').exists()).toBe(true)
    expect(document.documentElement.dataset.peekPhase).toBe('collapsed')

    wrapper.unmount()
  })

  it('re-syncs host phase after reveal that raced ahead of the first bridge push', async () => {
    vi.useFakeTimers()
    stubViewport(22, 22)
    api.getLiveTape.mockResolvedValue({
      indices: [],
      as_of: '2026-08-01 10:00:00',
      error: '',
      title: 'Loci · 行情',
    })

    let hostPhase: 'collapsed' | 'free' = 'collapsed'
    ;(window as unknown as { pywebview: { api: Record<string, unknown> } }).pywebview = {
      api: {
        peek_get_state: () => ({ phase: hostPhase, edge: 'right' }),
        peek_pointer_enter: () => undefined,
        peek_pointer_leave: () => undefined,
        peek_close: () => undefined,
      },
    }

    const wrapper = mount(PeekView)
    await flushPromises()
    expect(wrapper.find('.peek--ghost').exists()).toBe(true)
    expect(document.documentElement.dataset.peekPhase).toBe('collapsed')

    hostPhase = 'free'
    stubViewport(340, 340)
    window.dispatchEvent(new Event('resize'))
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()

    expect(wrapper.find('.peek--ghost').exists()).toBe(false)
    expect(wrapper.find('.peek-kicker').text()).toBe('盘面')
    expect(document.documentElement.dataset.peekPhase).toBe('free')

    wrapper.unmount()
  })
})

import { flushPromises, mount } from '@vue/test-utils'
import { KeepAlive, defineComponent, h, nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { getMarketSession } from '@/shared/api/quant'

import { useLivePolling } from './useLivePolling'

vi.mock('@/shared/api/quant', () => ({
  getMarketSession: vi.fn().mockResolvedValue({ live_allowed: false }),
}))

describe('useLivePolling', () => {
  it('does not start a second tick while the previous one is pending', async () => {
    let release!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const tick = vi.fn(() => pending)
    let polling!: ReturnType<typeof useLivePolling>

    const Probe = defineComponent({
      setup() {
        polling = useLivePolling({ intervalMs: 60_000, tick })
        return () => h('div')
      },
    })

    const wrapper = mount(Probe)
    await flushPromises()
    polling.stop()
    polling.liveAllowed.value = true

    const first = polling.runTick()
    await Promise.resolve()
    const second = polling.runTick()

    expect(tick).toHaveBeenCalledTimes(1)
    release()
    await Promise.all([first, second])
    wrapper.unmount()
  })

  it('allows one manual refresh without the session gate while keeping a single flight', async () => {
    let release!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const tick = vi.fn(() => pending)
    let polling!: ReturnType<typeof useLivePolling>

    const Probe = defineComponent({
      setup() {
        polling = useLivePolling({ intervalMs: 60_000, tick })
        return () => h('div')
      },
    })

    const wrapper = mount(Probe)
    await flushPromises()
    expect(polling.liveAllowed.value).toBe(false)

    const first = polling.refreshOnce()
    await Promise.resolve()
    polling.liveAllowed.value = true
    const second = polling.runTick()

    expect(tick).toHaveBeenCalledTimes(1)
    release()
    await Promise.all([first, second])
    polling.stop()
    wrapper.unmount()
  })

  it('ignores a session response from a superseded start', async () => {
    type Session = Awaited<ReturnType<typeof getMarketSession>>
    let resolveFirst!: (session: Session) => void
    let resolveSecond!: (session: Session) => void
    const first = new Promise<Session>((resolve) => {
      resolveFirst = resolve
    })
    const second = new Promise<Session>((resolve) => {
      resolveSecond = resolve
    })
    const sessionMock = vi.mocked(getMarketSession)
    sessionMock.mockReset()
    sessionMock.mockImplementationOnce(() => first).mockImplementationOnce(() => second)

    let polling!: ReturnType<typeof useLivePolling>
    const Probe = defineComponent({
      setup() {
        polling = useLivePolling({ intervalMs: 60_000, tick: vi.fn() })
        return () => h('div')
      },
    })

    const wrapper = mount(Probe)
    polling.start()
    resolveSecond({ live_allowed: true } as Session)
    await flushPromises()
    resolveFirst({ live_allowed: false } as Session)
    await flushPromises()

    expect(polling.liveAllowed.value).toBe(true)
    polling.stop()
    wrapper.unmount()
  })

  it('does not create polling work while disabled', async () => {
    vi.useFakeTimers()
    const sessionMock = vi.mocked(getMarketSession)
    sessionMock.mockClear()
    const enabled = ref(false)
    let polling!: ReturnType<typeof useLivePolling>
    const Probe = defineComponent({
      setup() {
        polling = useLivePolling({ intervalMs: 1000, tick: vi.fn(), enabled })
        return () => h('div')
      },
    })

    const wrapper = mount(Probe)
    await flushPromises()

    expect(sessionMock).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    polling.stop()
    wrapper.unmount()
  })

  it('fails closed when the session request fails', async () => {
    const sessionMock = vi.mocked(getMarketSession)
    sessionMock.mockReset()
    sessionMock.mockRejectedValue(new Error('session unavailable'))
    const tick = vi.fn()
    let polling!: ReturnType<typeof useLivePolling>
    const Probe = defineComponent({
      setup() {
        polling = useLivePolling({ intervalMs: 1000, tick })
        return () => h('div')
      },
    })

    const wrapper = mount(Probe)
    await flushPromises()
    await polling.runTick()

    expect(polling.liveAllowed.value).toBe(false)
    expect(tick).not.toHaveBeenCalled()
    polling.stop()
    wrapper.unmount()
  })

  it('stops timers on deactivate and restarts on activate', async () => {
    vi.useFakeTimers()
    const tick = vi.fn()
    let polling!: ReturnType<typeof useLivePolling>
    const Probe = defineComponent({
      setup() {
        polling = useLivePolling({ intervalMs: 1000, tick })
        return () => h('div')
      },
    })

    const wrapper = mount(Probe)
    await flushPromises()
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    polling.stop()
    expect(vi.getTimerCount()).toBe(0)

    polling.start()
    await flushPromises()
    expect(vi.getTimerCount()).toBeGreaterThan(0)
    polling.stop()
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('KeepAlive deactivate stops timers and activate restarts them', async () => {
    vi.useFakeTimers()
    const sessionMock = vi.mocked(getMarketSession)
    sessionMock.mockResolvedValue({ live_allowed: false } as never)
    const tick = vi.fn()
    const show = ref(true)

    const Child = defineComponent({
      name: 'LivePollingChild',
      setup() {
        useLivePolling({ intervalMs: 1000, tick })
        return () => h('div', 'child')
      },
    })

    const Host = defineComponent({
      setup() {
        return () =>
          h(KeepAlive, null, {
            default: () => (show.value ? h(Child) : null),
          })
      },
    })

    const wrapper = mount(Host)
    await flushPromises()
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    show.value = false
    await nextTick()
    await flushPromises()
    expect(vi.getTimerCount()).toBe(0)

    show.value = true
    await nextTick()
    await flushPromises()
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    wrapper.unmount()
    vi.useRealTimers()
  })
})

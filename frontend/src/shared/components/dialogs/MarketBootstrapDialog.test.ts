import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MarketBootstrapDialog from './MarketBootstrapDialog.vue'

const api = vi.hoisted(() => ({
  getDataLocation: vi.fn(),
  getMarketBootstrap: vi.fn(),
  startMarketBootstrap: vi.fn(),
}))
const setSyncing = vi.hoisted(() => vi.fn())

vi.mock('@/shared/api/quant', () => api)
vi.mock('@/shared/composables/useMarketSyncGate', () => ({
  useMarketSyncGate: () => ({ setSyncing }),
}))

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function snapshot(status: 'running' | 'done' | 'idle'): Record<string, unknown> {
  return {
    status,
    percent: status === 'running' ? 10 : status === 'done' ? 100 : 0,
    message: '',
    needed: status !== 'done',
    backfill_kind: 'empty',
  }
}

function mountDialog() {
  return mount(MarketBootstrapDialog, {
    global: {
      stubs: {
        ElDialog: {
          template: '<div><slot name="header" /><slot /><slot name="footer" /></div>',
        },
      },
    },
  })
}

describe('MarketBootstrapDialog lifecycle', () => {
  afterEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
  })

  it('ignores an in-flight bootstrap probe after unmount', async () => {
    const probe = deferred<Record<string, unknown>>()
    api.getDataLocation.mockResolvedValue({
      data_dir: 'data',
      market_db: 'data/market.db',
      needs_setup: false,
    })
    api.getMarketBootstrap.mockReturnValue(probe.promise)

    const wrapper = mountDialog()
    await flushPromises()
    expect(api.getMarketBootstrap).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    probe.resolve(snapshot('running'))
    await flushPromises()

    expect(setSyncing).toHaveBeenLastCalledWith(false)
    expect(setSyncing).not.toHaveBeenCalledWith(
      true,
      expect.anything(),
      expect.anything(),
    )
  })

  it('ignores a late data-location response after unmount', async () => {
    const location = deferred<Record<string, unknown>>()
    api.getDataLocation.mockReturnValue(location.promise)

    const wrapper = mountDialog()
    wrapper.unmount()
    location.resolve({
      data_dir: 'data',
      market_db: 'data/market.db',
      needs_setup: false,
    })
    await flushPromises()

    expect(api.getMarketBootstrap).not.toHaveBeenCalled()
  })

  it('does not start a second poll while the first poll is pending', async () => {
    const firstOpen = deferred<Record<string, unknown>>()
    const firstPoll = deferred<Record<string, unknown>>()
    const secondOpen = deferred<Record<string, unknown>>()
    api.getDataLocation.mockResolvedValue({
      data_dir: 'data',
      market_db: 'data/market.db',
      needs_setup: true,
    })
    api.getMarketBootstrap
      .mockImplementationOnce(() => firstOpen.promise)
      .mockImplementationOnce(() => firstPoll.promise)
      .mockImplementationOnce(() => secondOpen.promise)

    const wrapper = mountDialog()
    await flushPromises()
    window.dispatchEvent(new CustomEvent('loci:open-bootstrap', {
      detail: { autoStart: false },
    }))
    firstOpen.resolve(snapshot('running'))
    await flushPromises()
    window.dispatchEvent(new CustomEvent('loci:open-bootstrap', {
      detail: { autoStart: false },
    }))
    await flushPromises()

    expect(api.getMarketBootstrap).toHaveBeenCalledTimes(3)
    secondOpen.resolve(snapshot('running'))
    await flushPromises()
    expect(api.getMarketBootstrap).toHaveBeenCalledTimes(3)
    firstPoll.resolve(snapshot('done'))
    await flushPromises()
    wrapper.unmount()
  })
})

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getLiveTape: vi.fn(),
  getMarketSession: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

import { useDashboardLive } from './useDashboardLive'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useDashboardLive lifecycle', () => {
  afterEach(() => vi.clearAllMocks())

  it('ignores an in-flight live response after unmount', async () => {
    const pending = deferred<Record<string, unknown>>()
    api.getMarketSession.mockResolvedValue({ live_allowed: false })
    api.getLiveTape.mockReturnValue(pending.promise)

    let live!: ReturnType<typeof useDashboardLive>
    const Probe = defineComponent({
      setup() {
        live = useDashboardLive(() => [
          {
            code: '600519',
            name: '贵州茅台',
            shares: 100,
            cost: 100,
            cost_value: 10000,
            available_shares: 100,
            updated_on: '2026-07-31',
            note: '',
          },
        ])
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    wrapper.unmount()
    pending.resolve({
      as_of: '2026-07-31 10:00:00',
      error: '',
      positions: [
        {
          code: '600519',
          ok: true,
          price: 120,
          pct: 2,
          market_value: 12000,
        },
      ],
    })
    await flushPromises()

    expect(live.liveMarketValue.value).toBeNull()
    expect(live.liveError.value).toBe('')
  })
})

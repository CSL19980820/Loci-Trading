import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useMarketCatalog } from './useMarketCatalog'

const api = vi.hoisted(() => ({
  getStrategies: vi.fn(),
  getSkills: vi.fn(),
  fetchLanesCatalog: vi.fn(),
  getAkshareSources: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function strategy(slug: string): Record<string, unknown> {
  return {
    slug,
    name: slug,
    description: '',
    entry_timing: 'close',
    source_kind: 'builtin',
    editable: false,
  }
}

describe('useMarketCatalog request ordering', () => {
  afterEach(() => vi.clearAllMocks())

  it('does not let an older catalog response replace a newer load', async () => {
    const oldResult = deferred<Record<string, unknown>[]>()
    const newResult = deferred<Record<string, unknown>[]>()
    api.getStrategies
      .mockImplementationOnce(() => oldResult.promise)
      .mockImplementationOnce(() => newResult.promise)
    api.getSkills.mockResolvedValue([])
    api.fetchLanesCatalog.mockResolvedValue({ lanes: [], providers: [] })
    api.getAkshareSources.mockResolvedValue({ sources: [] })

    let catalog!: ReturnType<typeof useMarketCatalog>
    const Probe = defineComponent({
      setup() {
        catalog = useMarketCatalog()
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    const firstLoad = catalog.load()
    const secondLoad = catalog.load()
    newResult.resolve([strategy('new')])
    await secondLoad
    oldResult.resolve([strategy('old')])
    await firstLoad
    await flushPromises()

    expect(catalog.items.value.map((item) => item.slug)).toEqual(['new'])
    wrapper.unmount()
  })
})

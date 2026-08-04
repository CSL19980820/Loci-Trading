import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getAkshareCatalog: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

import { useSourceDatasets } from './useSourceDatasets'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useSourceDatasets lifecycle', () => {
  afterEach(() => vi.clearAllMocks())

  it('ignores a catalog response after the owning component unmounts', async () => {
    const pending = deferred<{ capabilities: Array<{ name: string }> }>()
    api.getAkshareCatalog.mockReturnValue(pending.promise)

    let datasets!: ReturnType<typeof useSourceDatasets>
    const Probe = defineComponent({
      setup() {
        datasets = useSourceDatasets()
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    const load = datasets.load('akshare')
    wrapper.unmount()
    pending.resolve({ capabilities: [{ name: 'late_catalog' }] })
    await load
    await flushPromises()

    expect(datasets.datasets.value).toEqual([])
    expect(datasets.error.value).toBe('')
    expect(datasets.loading.value).toBe(true)
  })
})

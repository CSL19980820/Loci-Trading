import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getAkshareCatalog: vi.fn(),
  getAkshareVersion: vi.fn(),
  probeAkshareCatalog: vi.fn(),
  probeAkshareCatalogBatch: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

import { useAkshareTools } from './useAkshareTools'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useAkshareTools lifecycle', () => {
  afterEach(() => vi.clearAllMocks())

  it('ignores a catalog response after its owning component unmounts', async () => {
    const pending = deferred<{ capabilities: [] }>()
    api.getAkshareCatalog.mockReturnValue(pending.promise)

    let tools!: ReturnType<typeof useAkshareTools>
    const Probe = defineComponent({
      setup() {
        tools = useAkshareTools()
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    const load = tools.load()
    wrapper.unmount()
    pending.resolve({ capabilities: [] })
    await load
    await flushPromises()

    expect(tools.catalog.value).toBeNull()
    expect(tools.loading.value).toBe(true)
  })
})

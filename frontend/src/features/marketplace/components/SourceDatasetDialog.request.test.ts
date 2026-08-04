import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AkshareCatalogCapability } from '@/shared/types/quant'

const api = vi.hoisted(() => ({ probeAkshareCatalog: vi.fn() }))
vi.mock('@/shared/api/quant', () => ({ probeAkshareCatalog: api.probeAkshareCatalog }))

import SourceDatasetDialog from './SourceDatasetDialog.vue'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function dataset(name: string): AkshareCatalogCapability {
  return {
    name,
    category: 'market',
    provider: 'akshare',
    signature: `${name}()`,
    status: 'available',
    summary: name,
    parameters: [],
    execution_mode: 'direct',
    param_docs: {},
    returns: '',
  }
}

function mountDialog() {
  return mount(SourceDatasetDialog, {
    props: { modelValue: true, dataset: dataset('old_api') },
    global: {
      stubs: {
        'el-dialog': { template: '<div><slot /></div>' },
        'el-table': { props: ['data'], template: '<div>{{ JSON.stringify(data) }}</div>' },
        'el-table-column': true,
        'el-input': true,
        'el-button': { template: '<button><slot /></button>' },
        'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
      },
    },
  })
}

describe('SourceDatasetDialog request ordering', () => {
  afterEach(() => vi.clearAllMocks())

  it('keeps probe columns attached to the newest dataset', async () => {
    const oldProbe = deferred<Record<string, unknown>>()
    const newProbe = deferred<Record<string, unknown>>()
    api.probeAkshareCatalog.mockImplementation((name: string) =>
      name === 'old_api' ? oldProbe.promise : newProbe.promise,
    )

    const wrapper = mountDialog()
    await wrapper.setProps({ dataset: dataset('new_api') })
    newProbe.resolve({ columns_detail: [{ raw: 'new_column', cn: '新列', en: 'new_column' }] })
    await flushPromises()
    oldProbe.resolve({ columns_detail: [{ raw: 'old_column', cn: '旧列', en: 'old_column' }] })
    await flushPromises()

    expect(wrapper.text()).toContain('new_column')
    expect(wrapper.text()).not.toContain('old_column')
    wrapper.unmount()
  })
})

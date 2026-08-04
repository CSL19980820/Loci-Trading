import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ getDataLocation: vi.fn(), saveDataLocation: vi.fn() }))
vi.mock('@/shared/api/quant', () => api)

import DataSetupDialog from './DataSetupDialog.vue'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function mountDialog() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/public', component: DataSetupDialog, meta: { public: true } },
      { path: '/private', component: DataSetupDialog, meta: { public: false } },
    ],
  })
  return router.push('/public').then(async () => {
    await router.isReady()
    return { router, wrapper: mount(DataSetupDialog, {
      global: {
        plugins: [router],
        stubs: {
          'el-dialog': {
            props: ['modelValue'],
            template: '<div data-open>{{ modelValue }}<slot /></div>',
          },
          'el-form': { template: '<div><slot /></div>' },
          'el-form-item': { template: '<div><slot /></div>' },
          'el-input': true,
          'el-button': { template: '<button><slot /></button>' },
          'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
        },
      },
    }) }
  })
}

describe('DataSetupDialog request ordering', () => {
  afterEach(() => vi.clearAllMocks())

  it('keeps the newest route probe result', async () => {
    const oldProbe = deferred<Record<string, unknown>>()
    const newProbe = deferred<Record<string, unknown>>()
    api.getDataLocation
      .mockImplementationOnce(() => oldProbe.promise)
      .mockImplementationOnce(() => newProbe.promise)

    const { router, wrapper } = await mountDialog()
    await router.push('/private')
    newProbe.resolve({
      needs_setup: false,
      default_dir: 'new-default',
      install_dir: 'new-install',
      data_dir: 'new-data',
      discovered_dirs: [],
    })
    await flushPromises()
    oldProbe.resolve({
      needs_setup: true,
      default_dir: 'old-default',
      install_dir: 'old-install',
      data_dir: 'old-data',
      discovered_dirs: [],
    })
    await flushPromises()

    expect(wrapper.get('[data-open]').text()).toMatch(/^false/)
    wrapper.unmount()
  })
})

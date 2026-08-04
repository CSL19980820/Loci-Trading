import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import BasicFormField from './BasicFormField.vue'
import type { BasicFormSchema } from './basicFormTypes'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function schema(request: (query?: Record<string, unknown>) => Promise<unknown[]>): BasicFormSchema {
  return {
    field: 'source',
    label: '来源',
    component: 'select',
    componentProps: { request },
  }
}

describe('BasicFormField remote options', () => {
  it('does not let an older request replace options for a newer schema', async () => {
    const older = deferred<unknown[]>()
    const newer = deferred<unknown[]>()
    const oldRequest = vi.fn().mockReturnValue(older.promise)
    const newRequest = vi.fn().mockReturnValue(newer.promise)
    const wrapper = mount(BasicFormField, {
      props: { schema: schema(oldRequest), model: { source: '' } },
      global: {
        stubs: {
          'el-select': { template: '<div><slot /></div>' },
          'el-option': {
            props: ['label'],
            template: '<span class="option">{{ label }}</span>',
          },
        },
      },
    })

    await wrapper.setProps({ schema: schema(newRequest) })
    newer.resolve([{ label: '新来源', value: 'new' }])
    await flushPromises()
    older.resolve([{ label: '旧来源', value: 'old' }])
    await flushPromises()

    expect(wrapper.text()).toContain('新来源')
    expect(wrapper.text()).not.toContain('旧来源')
    wrapper.unmount()
  })
})

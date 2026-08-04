import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import McpToolsDialog from './McpToolsDialog.vue'
import { getMcpServers } from '@/shared/api/quant'

vi.mock('@/shared/api/quant', () => ({
  getMcpServers: vi.fn(),
  probeMcpServer: vi.fn(),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function server(name: string) {
  return { name, tools: [], builtin: false } as never
}

function mountDialog() {
  return mount(McpToolsDialog, {
    props: { modelValue: false, server: server('first') },
    global: {
      stubs: {
        'el-dialog': {
          props: ['modelValue'],
          template: '<section v-if="modelValue"><slot name="header" title-id="head" title-class="head" /><slot /><slot name="footer" /></section>',
        },
        'el-button': { template: '<button><slot /></button>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-table': { template: '<div><slot /></div>' },
        'el-table-column': true,
        EmptyState: { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('McpToolsDialog session changes', () => {
  beforeEach(() => vi.mocked(getMcpServers).mockReset())

  it('does not restore a closed dialog with an older server response after reopening another server', async () => {
    const first = deferred<never[]>()
    const second = deferred<never[]>()
    vi.mocked(getMcpServers).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const wrapper = mountDialog()

    await wrapper.setProps({ modelValue: true })
    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ server: server('second'), modelValue: true })
    second.resolve([server('second')])
    await flushPromises()
    expect(wrapper.text()).toContain('second')

    first.resolve([server('first')])
    await flushPromises()
    expect(wrapper.text()).toContain('second')
    expect(wrapper.text()).not.toContain('first')
  })
})

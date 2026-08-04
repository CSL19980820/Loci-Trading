import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import McpToolListDrawer from './McpToolListDrawer.vue'
import { getMcpServers } from '@/shared/api/quant'

vi.mock('@/shared/api/quant', () => ({ getMcpServers: vi.fn() }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function server(toolName: string) {
  return [{ name: 'loci-market', tools: [{ name: toolName }] }] as never
}

function mountDrawer() {
  return mount(McpToolListDrawer, {
    props: { modelValue: false },
    global: {
      stubs: {
        'el-drawer': { template: '<section><slot /><slot name="footer" /></section>' },
        'el-button': {
          props: ['loading'],
          template: '<button :data-loading="String(loading)"><slot /></button>',
        },
        'el-tag': { template: '<span><slot /></span>' },
        'el-empty': true,
      },
    },
  })
}

describe('McpToolListDrawer async loading', () => {
  beforeEach(() => vi.mocked(getMcpServers).mockReset())

  it('keeps the newest open request and loading state when reopened before the prior request finishes', async () => {
    const first = deferred<never>()
    const second = deferred<never>()
    vi.mocked(getMcpServers).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const wrapper = mountDrawer()

    await wrapper.setProps({ modelValue: true })
    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ modelValue: true })
    second.resolve(server('fresh_tool'))
    await flushPromises()

    expect(wrapper.text()).toContain('fresh_tool')
    expect(wrapper.get('button').attributes('data-loading')).toBe('true')

    first.resolve(server('stale_tool'))
    await flushPromises()

    expect(wrapper.text()).toContain('fresh_tool')
    expect(wrapper.text()).not.toContain('stale_tool')
    expect(wrapper.get('button').attributes('data-loading')).toBe('false')
  })
})

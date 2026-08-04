import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import McpTab from './McpTab.vue'
import { getMcpServers, saveMcpServer } from '@/shared/api/quant'
import { createOpsFeedback, provideOpsFeedback } from '../composables/useOpsFeedback'

vi.mock('@/shared/api/quant', () => ({
  CapabilityUnavailableError: class CapabilityUnavailableError extends Error {},
  deleteMcpServer: vi.fn(),
  getMcpServers: vi.fn(),
  saveMcpServer: vi.fn(),
  toggleMcpServer: vi.fn(),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const stubs = {
  SettingsPanel: { props: ['receipt'], template: '<div>{{ receipt[0].value }}<slot /></div>' },
  EmptyState: { template: '<div><slot /></div>' },
  McpToolsDialog: true,
  'el-button': {
    emits: ['click'],
    template: '<button @click="$emit(\'click\', $event)"><slot /></button>',
  },
  'el-table': { template: '<div><slot /></div>' },
  'el-table-column': true,
  'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<div><slot /></div>' },
  'el-input': {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-checkbox': true,
  'el-tag': true,
}

function mountTab() {
  return mount(McpTab, {
    global: {
      stubs,
    },
  })
}

function mountTabWithFeedback() {
  const feedback = createOpsFeedback()
  const Host = defineComponent({
    setup() {
      provideOpsFeedback(feedback)
      return () => h(McpTab)
    },
  })
  const host = mount(Host, { global: { stubs } })
  return { feedback, host, tab: host.findComponent(McpTab) }
}

describe('McpTab loading', () => {
  beforeEach(() => {
    vi.mocked(getMcpServers).mockReset()
    vi.mocked(saveMcpServer).mockReset()
  })

  it('does not let an older refresh replace the newest server list', async () => {
    const first = deferred<never>()
    const second = deferred<never>()
    vi.mocked(getMcpServers).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const wrapper = mountTab()

    const load = wrapper.vm.load as () => Promise<void>
    void load()
    void load()
    second.resolve([{ name: 'fresh', tools: [], is_active: true }] as never)
    await flushPromises()
    expect(wrapper.text()).toContain('1 台')

    first.resolve([] as never)
    await flushPromises()
    expect(wrapper.text()).toContain('1 台')
  })

  it('does not send the unsupported proxy field when saving a server', async () => {
    vi.mocked(saveMcpServer).mockResolvedValue({ name: 'demo', tools: [] } as never)
    vi.mocked(getMcpServers).mockResolvedValue([] as never)
    const wrapper = mountTab()
    await wrapper.get('input[placeholder="my-data-source"]').setValue('demo')
    await wrapper.get('input[placeholder="https://mcp.example.com"]').setValue('https://example.com/mcp')
    await wrapper.get('input[placeholder="用途说明"]').setValue('test')
    const saveButton = wrapper.findAll('button').find((button) => button.text() === '保存并发现工具')
    expect(saveButton).toBeDefined()
    await saveButton!.trigger('click')
    await flushPromises()

    expect(saveMcpServer).toHaveBeenCalledWith({
      name: 'demo',
      url: 'https://example.com/mcp',
      token: undefined,
      note: 'test',
      verify: true,
    })
  })

  it('marks the list as stale when a successful save cannot refresh it', async () => {
    const { feedback, tab } = mountTabWithFeedback()
    vi.mocked(getMcpServers).mockResolvedValueOnce([
      { name: 'old-server', tools: [], is_active: true },
    ] as never)
    await (tab.vm.load as () => Promise<void>)()

    vi.mocked(saveMcpServer).mockResolvedValue({ name: 'new-server', tools: [] } as never)
    vi.mocked(getMcpServers).mockRejectedValueOnce(new Error('MCP 列表不可用'))
    await tab.get('input[placeholder="my-data-source"]').setValue('new-server')
    await tab.get('input[placeholder="https://mcp.example.com"]').setValue('https://example.com/mcp')
    const saveButton = tab.findAll('button').find((button) => button.text() === '保存并发现工具')
    expect(saveButton).toBeDefined()
    await saveButton!.trigger('click')
    await flushPromises()

    expect(feedback.errorText.value).toContain('列表刷新失败')
    expect(feedback.notice.value).toBe('')
    expect(tab.text()).toContain('1 台')
    expect(tab.emitted('changed')).toBeUndefined()
  })
})

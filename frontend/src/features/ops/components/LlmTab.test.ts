import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LlmTab from './LlmTab.vue'
import { getProviders, saveProvider } from '@/shared/api/quant'
import { createOpsFeedback, provideOpsFeedback } from '../composables/useOpsFeedback'

vi.mock('@/shared/api/quant', () => ({
  CapabilityUnavailableError: class CapabilityUnavailableError extends Error {},
  deleteProvider: vi.fn(),
  getProviders: vi.fn(),
  refreshProviderModels: vi.fn(),
  saveProvider: vi.fn(),
  setDefaultProvider: vi.fn(),
  testProvider: vi.fn(),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const dialogPayload = {
  name: 'fresh-provider',
  base_url: 'https://llm.example.com/v1',
  api_key: '',
  protocol: 'openai_compatible' as const,
  model: 'model-a',
  proxy_url: '',
  note: '',
  validate_key: false,
  discover_models: false,
  is_default: false,
}

const stubs = {
  SettingsPanel: { template: '<div><slot /><slot name="action" /></div>' },
  EmptyState: { template: '<div><slot /></div>' },
  LlmProviderCard: true,
  LlmProviderDialog: {
    emits: ['save'],
    setup(_props: unknown, { emit }: { emit: (name: 'save', payload: typeof dialogPayload) => void }) {
      return () =>
        h(
          'button',
          {
            'data-testid': 'save-provider',
            onClick: () => emit('save', dialogPayload),
          },
          '保存供应商',
        )
    },
  },
  LlmModelCatalogDrawer: true,
  'el-button': {
    emits: ['click'],
    template: '<button @click="$emit(\'click\', $event)"><slot /></button>',
  },
}

function mountTab() {
  return mount(LlmTab, {
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
      return () => h(LlmTab)
    },
  })
  const host = mount(Host, { global: { stubs } })
  return { feedback, host, tab: host.findComponent(LlmTab) }
}

describe('LlmTab loading', () => {
  beforeEach(() => {
    vi.mocked(getProviders).mockReset()
    vi.mocked(saveProvider).mockReset()
  })

  it('keeps providers from the latest refresh when requests resolve out of order', async () => {
    const first = deferred<never>()
    const second = deferred<never>()
    vi.mocked(getProviders).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const wrapper = mountTab()

    const load = wrapper.vm.load as () => Promise<void>
    void load()
    void load()
    second.resolve([{ id: '2', name: 'fresh', models: [] }] as never)
    await flushPromises()
    expect((wrapper.vm.providers as Array<{ name: string }>)[0]?.name).toBe('fresh')

    first.resolve([{ id: '1', name: 'stale', models: [] }] as never)
    await flushPromises()
    expect((wrapper.vm.providers as Array<{ name: string }>)[0]?.name).toBe('fresh')
  })

  it('marks the list as stale when a successful save cannot refresh it', async () => {
    const { feedback, tab } = mountTabWithFeedback()
    vi.mocked(getProviders).mockResolvedValueOnce([
      { id: 'old', name: 'old-provider', models: [] },
    ] as never)
    await (tab.vm.load as () => Promise<void>)()

    vi.mocked(saveProvider).mockResolvedValue({ id: 'new', name: 'fresh-provider', models: [] } as never)
    vi.mocked(getProviders).mockRejectedValueOnce(new Error('供应商列表不可用'))
    const create = tab.findAll('button').find((button) => button.text() === '+ 添加供应商')
    expect(create).toBeDefined()
    await create!.trigger('click')
    await tab.get('[data-testid="save-provider"]').trigger('click')
    await flushPromises()

    expect(feedback.errorText.value).toContain('列表刷新失败')
    expect(feedback.notice.value).toBe('')
    expect((tab.vm.providers as Array<{ name: string }>)[0]?.name).toBe('old-provider')
    expect(tab.emitted('changed')).toBeUndefined()
  })
})

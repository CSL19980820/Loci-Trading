import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, inject, provide, type PropType } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LlmModelCatalogDrawer from './LlmModelCatalogDrawer.vue'
import { updateProviderModels } from '@/shared/api/quant'
import type { LlmModel, LlmProvider } from '@/shared/types/quant'

vi.mock('@/shared/api/quant', () => ({
  refreshProviderModels: vi.fn(),
  updateProviderModels: vi.fn(),
}))

const tableRowsKey = Symbol('model-catalog-table-rows')

const TableStub = defineComponent({
  props: {
    data: { type: Array as PropType<LlmModel[]>, required: true },
  },
  setup(props, { slots }) {
    provide(tableRowsKey, props.data)
    return () => h('div', { 'data-testid': 'catalog-table' }, slots.default?.())
  },
})

const TableColumnStub = defineComponent({
  setup(_props, { slots }) {
    const rows = inject<LlmModel[]>(tableRowsKey, [])
    return () => h('div', rows.map((row) => slots.default?.({ row })))
  },
})

const SwitchStub = defineComponent({
  props: {
    modelValue: { type: Boolean, required: true },
    disabled: { type: Boolean, default: false },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () =>
      h('button', {
        'data-testid': 'model-switch',
        disabled: props.disabled,
        onClick: () => emit('update:modelValue', !props.modelValue),
      })
  },
})

const stubs = {
  'el-drawer': {
    props: ['modelValue'],
    template: '<section v-if="modelValue"><slot /></section>',
  },
  'el-button': { template: '<button><slot /></button>' },
  'el-input': true,
  'el-input-number': true,
  'el-select': { template: '<div data-testid="default-select"><slot /></div>' },
  'el-option': {
    props: ['label', 'value'],
    template: '<span data-testid="default-option" :data-value="value">{{ label }}</span>',
  },
  'el-switch': SwitchStub,
  'el-table': TableStub,
  'el-table-column': TableColumnStub,
  'el-tag': { template: '<span><slot /></span>' },
}

function provider(defaultModel = 'model-a'): LlmProvider {
  return {
    id: 'provider-1',
    name: 'catalog-provider',
    default_model: defaultModel,
    models: ['model-a'],
    model_catalog: [
      {
        id: 'model-a',
        name: 'Model A',
        enabled: true,
        context_window: null,
        max_output_tokens: null,
        source: 'discovered',
      },
      {
        id: 'model-b',
        name: 'Model B',
        enabled: false,
        context_window: null,
        max_output_tokens: null,
        source: 'discovered',
      },
    ],
  } as LlmProvider
}

function mountDrawer(defaultModel?: string) {
  return mount(LlmModelCatalogDrawer, {
    props: { open: true, provider: provider(defaultModel) },
    global: { stubs },
  })
}

describe('LlmModelCatalogDrawer default model', () => {
  beforeEach(() => {
    vi.mocked(updateProviderModels).mockReset()
  })

  it('only offers enabled models as the default and keeps the current default enabled', async () => {
    const wrapper = mountDrawer()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="default-option"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="default-option"]').attributes('data-value')).toBe('model-a')
    expect(wrapper.findAll('[data-testid="model-switch"]')[0].attributes('disabled')).toBeDefined()
  })

  it('replaces a persisted disabled default with the first enabled model', async () => {
    const wrapper = mountDrawer('model-b')
    await flushPromises()

    expect((wrapper.vm as unknown as { defaultModel: string }).defaultModel).toBe('model-a')
  })
})

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AssistantRuntimeBar from './AssistantRuntimeBar.vue'

const providers = [
  {
    name: 'deepseek',
    models: ['deepseek-v4-flash', 'deepseek-reasoner'],
    default_model: 'deepseek-v4-flash',
    is_active: true,
    is_default: true,
  },
  {
    name: 'openrouter',
    models: ['openai/gpt-4.1-mini'],
    default_model: 'openai/gpt-4.1-mini',
    is_active: true,
    is_default: false,
  },
]

describe('AssistantRuntimeBar', () => {
  it('emits a provider+model pair from the grouped model select', async () => {
    const wrapper = mount(AssistantRuntimeBar, {
      props: {
        providers,
        provider: 'deepseek',
        model: 'deepseek-v4-flash',
        thinking: 'off',
      },
      global: {
        stubs: {
          'el-select': {
            props: ['modelValue'],
            emits: ['update:modelValue'],
            template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', ($event.target).value)"><slot /></select>',
          },
          'el-option-group': { template: '<optgroup><slot /></optgroup>' },
          'el-option': {
            props: ['value', 'label'],
            template: '<option :value="value">{{ label }}</option>',
          },
        },
      },
    })

    const modelSelect = wrapper.findAll('select')[0]
    await modelSelect.setValue(`openrouter\u0000openai/gpt-4.1-mini`)
    expect(wrapper.emitted('select')?.[0]).toEqual([{ provider: 'openrouter', model: 'openai/gpt-4.1-mini' }])
  })

  it('emits thinking level changes', async () => {
    const wrapper = mount(AssistantRuntimeBar, {
      props: {
        providers,
        provider: 'deepseek',
        model: 'deepseek-v4-flash',
        thinking: 'off',
      },
      global: {
        stubs: {
          'el-select': {
            props: ['modelValue'],
            emits: ['update:modelValue'],
            template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', ($event.target).value)"><slot /></select>',
          },
          'el-option-group': { template: '<optgroup><slot /></optgroup>' },
          'el-option': {
            props: ['value', 'label'],
            template: '<option :value="value">{{ label }}</option>',
          },
        },
      },
    })

    const thinkingSelect = wrapper.findAll('select')[1]
    await thinkingSelect.setValue('high')
    expect(wrapper.emitted('thinking')?.[0]).toEqual(['high'])
  })
})

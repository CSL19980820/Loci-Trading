import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AssistantConfirmCard from './AssistantConfirmCard.vue'

const stubs = {
  'el-button': {
    props: ['type'],
    emits: ['click'],
    template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
  },
  'el-tag': { template: '<span><slot /></span>' },
  'el-input': {
    props: ['modelValue'],
    emits: ['update:modelValue', 'focus'],
    template:
      '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @focus="$emit(\'focus\')" />',
  },
}

describe('AssistantConfirmCard', () => {
  it('emits reply when an option chip is clicked', async () => {
    const wrapper = mount(AssistantConfirmCard, {
      props: {
        ask: { prompt: '选路径？', options: ['提交', '再看看'] },
      },
      global: { stubs },
    })

    await wrapper.findAll('button')[0]!.trigger('click')
    expect(wrapper.emitted('reply')?.[0]).toEqual(['提交'])
    wrapper.unmount()
  })

  it('emits reply on digit key 1 outside inputs', async () => {
    const wrapper = mount(AssistantConfirmCard, {
      props: {
        ask: { prompt: '选路径？', options: ['提交', '再看看'] },
      },
      attachTo: document.body,
      global: { stubs },
    })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: '2', bubbles: true }))
    expect(wrapper.emitted('reply')?.[0]).toEqual(['再看看'])
    wrapper.unmount()
  })

  it('submits structured answers for multi-question ask', async () => {
    const wrapper = mount(AssistantConfirmCard, {
      props: {
        ask: {
          prompt: '请确认',
          questions: [
            { id: 'path', prompt: '选路径？', options: ['提交', '再看看'] },
            { id: 'note', prompt: '备注？', allow_free_text: true },
          ],
        },
      },
      global: { stubs },
    })

    expect(wrapper.find('[data-testid="assistant-confirm-questions"]').exists()).toBe(true)
    await wrapper.findAll('.assistant-ask__chip')[0]!.trigger('click')
    await wrapper.find('textarea').setValue('先观望')
    await wrapper.get('[data-testid="assistant-confirm-submit"]').trigger('click')
    expect(wrapper.emitted('reply')?.[0]?.[0]).toContain('[path] 选路径？ → 提交')
    expect(wrapper.emitted('reply')?.[0]?.[0]).toContain('[note] 备注？ → 先观望')
    wrapper.unmount()
  })

  it('blocks empty required answers and restores multi options from ask', async () => {
    const wrapper = mount(AssistantConfirmCard, {
      props: {
        ask: {
          prompt: '请确认',
          questions: [
            { id: 'path', prompt: '选路径？', options: ['提交', '再看看'] },
            { id: 'side', prompt: '方向？', options: ['多', '空'] },
          ],
        },
      },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('选路径？')
    expect(wrapper.text()).toContain('方向？')
    expect(wrapper.text()).toContain('提交')
    expect(wrapper.text()).toContain('多')
    await wrapper.get('[data-testid="assistant-confirm-submit"]').trigger('click')
    expect(wrapper.emitted('reply')).toBeUndefined()
    expect(wrapper.get('[data-testid="assistant-confirm-error"]').text()).toContain('请先回答')
    wrapper.unmount()
  })
})

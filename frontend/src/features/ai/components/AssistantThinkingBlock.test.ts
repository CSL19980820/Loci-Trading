import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick } from 'vue'

vi.mock('vue-element-plus-x/es/Thinking/index.js', () => ({
  default: defineComponent({
    name: 'ThinkingStub',
    props: {
      modelValue: { type: Boolean, default: true },
      content: { type: String, default: '' },
      status: { type: String, default: 'start' },
      autoCollapse: { type: Boolean, default: false },
    },
    emits: ['update:modelValue'],
    template: `
      <div data-testid="thinking-stub" :data-status="status" :data-expanded="String(modelValue)">
        <div class="elx-thinking__content"><pre>{{ content }}</pre></div>
      </div>
    `,
  }),
}))

import AssistantThinkingBlock from './AssistantThinkingBlock.vue'

describe('AssistantThinkingBlock', () => {
  it('stays expanded while streaming', async () => {
    const wrapper = mount(AssistantThinkingBlock, {
      props: { content: '先看仓位', streaming: true, autoCollapse: false },
    })
    await nextTick()
    expect(wrapper.get('[data-testid="thinking-stub"]').attributes('data-expanded')).toBe('true')
    expect(wrapper.get('[data-testid="thinking-stub"]').attributes('data-status')).toBe('thinking')
  })

  it('collapses when thinking ends and autoCollapse is on', async () => {
    const wrapper = mount(AssistantThinkingBlock, {
      props: { content: '先看仓位', streaming: true, autoCollapse: false },
    })
    await wrapper.setProps({ streaming: false, autoCollapse: true })
    await nextTick()
    expect(wrapper.get('[data-testid="thinking-stub"]').attributes('data-status')).toBe('end')
    expect(wrapper.get('[data-testid="thinking-stub"]').attributes('data-expanded')).toBe('false')
  })
})

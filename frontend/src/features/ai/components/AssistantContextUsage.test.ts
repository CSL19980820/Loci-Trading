import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'

import type { ContextUsageSnapshot } from '../assistantContextUsage'
import AssistantContextUsage from './AssistantContextUsage.vue'

const usage: ContextUsageSnapshot = {
  used: 38400,
  window: 128000,
  remaining: 89600,
  percent: 30,
  segments: [
    { kind: 'system', label: '系统提示', tokens: 360, color: '#94a3b8' },
    { kind: 'tools', label: '工具定义', tokens: 3300, color: '#7c3aed' },
  ],
}

/** EP-like: click trigger alone owns visibility (no parent double-toggle). */
const PopoverStub = defineComponent({
  name: 'ElPopover',
  props: {
    visible: { type: Boolean, default: false },
    trigger: { type: String, default: 'click' },
  },
  emits: ['update:visible'],
  setup(props, { emit, slots }) {
    function onReferenceClick(): void {
      if (props.trigger === 'click') emit('update:visible', !props.visible)
    }
    return () => [
      h('div', { class: 'popover-ref', onClick: onReferenceClick }, slots.reference?.()),
      props.visible
        ? h('div', { class: 'popover-body', 'data-testid': 'ctx-usage-panel' }, slots.default?.())
        : null,
    ]
  },
})

const buttonStub = {
  template: '<button v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
}

describe('AssistantContextUsage', () => {
  it('keeps the panel open after one trigger click (no flash-close)', async () => {
    const wrapper = mount(AssistantContextUsage, {
      props: { usage },
      global: {
        stubs: {
          'el-popover': PopoverStub,
          'el-button': buttonStub,
        },
      },
    })

    await wrapper.get('.popover-ref').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-testid="ctx-usage-panel"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="assistant-context-usage-trigger"]').attributes('aria-expanded')).toBe('true')
  })

  it('closes from the panel close control', async () => {
    const wrapper = mount(AssistantContextUsage, {
      props: { usage },
      global: {
        stubs: {
          'el-popover': PopoverStub,
          'el-button': buttonStub,
        },
      },
    })

    await wrapper.get('.popover-ref').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="ctx-usage-panel"]').exists()).toBe(true)

    await wrapper.get('[aria-label="关闭"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="ctx-usage-panel"]').exists()).toBe(false)
  })
})

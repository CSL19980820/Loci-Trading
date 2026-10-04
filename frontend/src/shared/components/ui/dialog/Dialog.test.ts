import { mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import Dialog from './Dialog.vue'
import DialogTrigger from './DialogTrigger.vue'

function body({ open, close }: { open: boolean; close: () => void }) {
  return [
    h(DialogTrigger, {}, () => 'Open dialog'),
    h('span', { 'data-dialog-state': '' }, open ? 'open' : 'closed'),
    h('button', { 'data-close': '', onClick: close }, 'Close dialog'),
  ]
}

describe('dialog open-state contract', () => {
  it('retains uncontrolled trigger and default-open behavior', async () => {
    const wrapper = mount(Dialog, { props: { defaultOpen: true }, slots: { default: body } })
    try {
      expect(wrapper.get('[data-dialog-state]').text()).toBe('open')
      await wrapper.get('[data-close]').trigger('click')
      expect(wrapper.get('[data-dialog-state]').text()).toBe('closed')
      await wrapper.get('[data-slot="dialog-trigger"]').trigger('click')
      expect(wrapper.get('[data-dialog-state]').text()).toBe('open')
      expect(wrapper.emitted('update:open')).toEqual([[false], [true]])
    } finally { wrapper.unmount() }
  })

  it('emits one controlled close request and follows the caller model', async () => {
    const wrapper = mount(Dialog, { props: { open: true }, slots: { default: body } })
    try {
      await wrapper.get('[data-close]').trigger('click')
      expect(wrapper.emitted('update:open')).toEqual([[false]])
      expect(wrapper.get('[data-dialog-state]').text()).toBe('open')
      await wrapper.setProps({ open: false })
      expect(wrapper.get('[data-dialog-state]').text()).toBe('closed')
    } finally { wrapper.unmount() }
  })

  it('preserves an uncontrolled dialog across cached page deactivation', async () => {
    const sourceVisible = ref(true)
    const source = defineComponent({ setup: () => () => h(Dialog, { defaultOpen: true }, { default: body }) })
    const host = defineComponent({ setup: () => () => h(KeepAlive, {}, { default: () => sourceVisible.value ? h(source) : null }) })
    const wrapper = mount(host)
    try {
      expect(wrapper.get('[data-dialog-state]').text()).toBe('open')
      sourceVisible.value = false
      await nextTick()
      sourceVisible.value = true
      await nextTick()
      expect(wrapper.get('[data-dialog-state]').text()).toBe('open')
    } finally { wrapper.unmount() }
  })
})

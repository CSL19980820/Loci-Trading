import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { describe, expect, it } from 'vitest'
import PageHost from './PageHost.vue'

function archiveRoute(code: string, date = ''): RouteLocationNormalizedLoaded {
  return {
    name: 'archive', params: { code }, query: date ? { date } : {},
    fullPath: `/archive/${code}${date ? `?date=${date}` : ''}`,
  } as unknown as RouteLocationNormalizedLoaded
}

const Slot = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) })
const Dialog = defineComponent({
  props: { open: Boolean },
  setup: (props, { slots }) => () => props.open ? h('section', slots.default?.()) : null,
})
const global = { stubs: { Dialog, DialogContent: Slot, DialogTitle: Slot, DialogDescription: Slot } }

describe('archive workspace route reuse', () => {
  it('keeps the batch list and workspace settings when switching stocks or signal dates', async () => {
    const route = ref(archiveRoute('000001'))
    let mounts = 0
    const archive = defineComponent({
      setup: (_, { expose }) => {
        mounts++
        const period = ref('day')
        expose({ close: () => {} })
        return () => h('div', [
          h('ol', { 'data-batch-list': '' }, [h('li', '候选池')]),
          h('input', { 'data-workspace-setting': '', value: period.value, onInput: (event: Event) => { period.value = (event.target as HTMLInputElement).value } }),
          h('p', { 'data-stock': '' }, String(route.value.params.code)),
        ])
      },
    })
    const wrapper = mount(PageHost, { props: { component: archive, route: route.value }, global })
    try {
      const list = wrapper.get('[data-batch-list]').element as HTMLElement
      const setting = wrapper.get('[data-workspace-setting]').element as HTMLInputElement
      list.scrollTop = 640
      await wrapper.get('[data-workspace-setting]').setValue('week')

      route.value = archiveRoute('000002')
      await wrapper.setProps({ route: route.value })
      expect(wrapper.get('[data-stock]').text()).toBe('000002')
      expect(wrapper.get('[data-batch-list]').element).toBe(list)
      expect(list.scrollTop).toBe(640)
      expect(wrapper.get('[data-workspace-setting]').element).toBe(setting)
      expect(setting.value).toBe('week')

      route.value = archiveRoute('000002', '2026-09-30')
      await wrapper.setProps({ route: route.value })
      expect(wrapper.get('[data-batch-list]').element).toBe(list)
      expect(list.scrollTop).toBe(640)
      expect(mounts).toBe(1)
    } finally { wrapper.unmount() }
  })

  it('starts a fresh archive workspace after returning to the source page', async () => {
    let mounts = 0
    const archive = defineComponent({ setup: () => { mounts++; return () => h('div', { 'data-archive': '' }) } })
    const source = defineComponent({ setup: () => () => h('div', { 'data-source': '' }) })
    const wrapper = mount(PageHost, { props: { component: archive, route: archiveRoute('000001') }, global })
    try {
      await wrapper.setProps({ component: source, route: { name: 'pool', fullPath: '/pool' } as RouteLocationNormalizedLoaded })
      expect(wrapper.find('[data-archive]').exists()).toBe(false)
      await wrapper.setProps({ component: archive, route: archiveRoute('000002') })
      expect(wrapper.find('[data-archive]').exists()).toBe(true)
      expect(mounts).toBe(2)
    } finally { wrapper.unmount() }
  })
})

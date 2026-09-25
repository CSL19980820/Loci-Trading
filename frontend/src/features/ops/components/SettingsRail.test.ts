import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { expect, it } from 'vitest'
import SettingsRail from './SettingsRail.vue'

it('connects a single vertical tablist to its panel and navigates across groups with the keyboard', async () => {
  const host = mount(defineComponent({
    components: { SettingsRail },
    setup() {
      const active = ref('llm')
      const anchor = ref('')
      const groups = [
        { title: '模型', items: [{ name: 'llm', label: '大模型' }] },
        { title: '系统', items: [{ name: 'system', label: '系统设置', children: [{ label: '外观', anchor: 'appearance' }] }] },
      ]
      return { active, anchor, groups }
    },
    template: `<SettingsRail v-model="active" panel-id="settings-panel" :groups="groups" @select-anchor="anchor = $event" />
      <section id="settings-panel" role="tabpanel" tabindex="0" :aria-labelledby="'settings-panel-tab-' + active">{{ active }} {{ anchor }}</section>`,
  }), { attachTo: document.body })
  try {
    await flushPromises()
    expect(host.findAll('[role="tablist"]')).toHaveLength(1)
    expect(host.get('[role="tablist"]').attributes('aria-orientation')).toBe('vertical')
    const tabs = host.findAll('[role="tab"]')
    expect(tabs.map(tab => tab.attributes('id'))).toEqual(['settings-panel-tab-llm', 'settings-panel-tab-system'])
    expect(tabs.every(tab => tab.attributes('aria-controls') === 'settings-panel')).toBe(true)
    ;(tabs[0]!.element as HTMLElement).focus()
    await tabs[0]!.trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()
    expect(document.activeElement?.id).toBe('settings-panel-tab-system')
    expect(host.get('[role="tabpanel"]').attributes('aria-labelledby')).toBe('settings-panel-tab-system')
    await host.get('[data-settings-anchor="appearance"]').trigger('click')
    expect(host.get('[role="tabpanel"]').text()).toContain('appearance')
  } finally {
    host.unmount()
  }
})

import { mount, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import { createEmptyScreenSkillDraft } from '../composables/screenSkillDraft'
import ScreenSkillCodePanel from './ScreenSkillCodePanel.vue'
import ScreenSkillSettingsDrawer from './ScreenSkillSettingsDrawer.vue'

describe('screen skill runtime controls', () => {
  it('requests a normalized runtime switch without mutating the draft directly', async () => {
    const draft = createEmptyScreenSkillDraft()
    const wrapper = mount(ScreenSkillCodePanel, {
      props: { draft, showEditor: false },
      global: { plugins: [ElementPlus] },
    })

    const runtimeSelect = wrapper.findAllComponents({ name: 'ElSelect' })[0]
    expect(runtimeSelect).toBeDefined()
    runtimeSelect!.vm.$emit('update:modelValue', 'python')
    await nextTick()

    expect(draft.runtime).toBe('formula')
    expect(wrapper.emitted('runtime-change')).toEqual([['python']])
  })

  it('forwards runtime switch requests from the settings drawer', async () => {
    const wrapper = shallowMount(ScreenSkillSettingsDrawer, {
      props: {
        draft: createEmptyScreenSkillDraft(),
        fieldOptions: [],
        requiredFields: [],
        presets: [],
        stats: null,
      },
      global: {
        stubs: {
          ElDrawer: { template: '<div><slot /></div>' },
          ElTabs: { template: '<div><slot /></div>' },
          ElTabPane: { template: '<div><slot /></div>' },
        },
      },
    })

    wrapper.findComponent(ScreenSkillCodePanel).vm.$emit('runtime-change', 'python')
    await nextTick()

    expect(wrapper.emitted('runtime-change')).toEqual([['python']])
  })
})

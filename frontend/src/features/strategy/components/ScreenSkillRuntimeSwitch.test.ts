import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import { createEmptyScreenSkillDraft } from '../composables/screenSkillDraft'
import ScreenSkillCodePanel from './ScreenSkillCodePanel.vue'

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
})

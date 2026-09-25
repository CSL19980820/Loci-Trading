import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { reactive } from 'vue'
import ScreenSkillLogicPanel from './ScreenSkillLogicPanel.vue'
import { createEmptyScreenSkillDraft } from '../composables/screenSkillDraft'

const wrappers: VueWrapper[] = []
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('strategy token fields', () => {
  it('adds and removes factor and citation tokens while preserving string draft fields', async () => {
    const draft = reactive(createEmptyScreenSkillDraft())
    draft.factorsText = 'MA, VOL'
    draft.logic[0]!.citationsText = 'ref-one, ref-two'
    const wrapper = mount(ScreenSkillLogicPanel, {
      props: { draft }, attachTo: document.body,
      global: { stubs: { HintTooltip: { template: '<span><slot /></span>' } } },
    })
    wrappers.push(wrapper)
    const factors = wrapper.get('input[aria-label="因子清单"]')
    await factors.setValue('RSI')
    await factors.trigger('keydown', { key: 'Enter' })
    expect(draft.factorsText).toBe('MA, VOL, RSI')
    expect(wrapper.get('[aria-label="移除因子 VOL"]').attributes('aria-labelledby')).toBeUndefined()
    await wrapper.get('[aria-label="移除因子 VOL"]').trigger('click')
    expect(draft.factorsText).toBe('MA, RSI')
    const citations = wrapper.get('input[aria-label="引用编号"]')
    await citations.setValue('ref-three')
    await citations.trigger('blur')
    expect(draft.logic[0]!.citationsText).toBe('ref-one, ref-two, ref-three')
    await wrapper.get('[aria-label="移除引用 ref-one"]').trigger('click')
    expect(draft.logic[0]!.citationsText).toBe('ref-two, ref-three')
  })
})

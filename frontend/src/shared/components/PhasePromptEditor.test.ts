import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import PhasePromptEditor from './PhasePromptEditor.vue'

let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); document.body.replaceChildren() })

async function openStage(name: string) {
  const tab = wrapper!.findAll('[role="tab"]').find(item => item.text() === name)!
  await tab.trigger('mousedown', { button: 0 })
  await tab.trigger('click')
}

describe('PhasePromptEditor blank-stage fallback copy', () => {
  it('names the built-in stage prompt while the trader intraday prompt is still built-in', async () => {
    wrapper = mount(PhasePromptEditor, { attachTo: document.body, props: { prompt: '内置盘中', defaultPrompt: '内置盘中', premarketPrompt: '', separateWeekly: true } })
    await openStage('盘前')
    expect(wrapper.text()).toContain('未独立配置，当前使用共用基调与内置阶段提示词。')
    expect(wrapper.get('textarea').attributes('placeholder')).toBe('留空时自动使用内置阶段提示词')
  })

  it('names the intraday prompt once it is customised, and for agents without a built-in default', async () => {
    wrapper = mount(PhasePromptEditor, { attachTo: document.body, props: { prompt: '我的盘中方法', defaultPrompt: '内置盘中', reviewPrompt: '', separateWeekly: true } })
    await openStage('日复盘')
    expect(wrapper.text()).toContain('未独立配置，当前使用共用基调与盘中提示词。')
    wrapper.unmount()
    wrapper = mount(PhasePromptEditor, { attachTo: document.body, props: { prompt: '智能体盘中', premarketPrompt: '' } })
    await openStage('盘前')
    expect(wrapper.text()).toContain('未独立配置，当前使用共用基调与盘中提示词。')
  })
})

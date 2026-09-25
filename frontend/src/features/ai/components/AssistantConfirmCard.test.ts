import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import AssistantConfirmCard from './AssistantConfirmCard.vue'

const wrappers: VueWrapper[] = []
function render(ask: Record<string, unknown>) {
  const wrapper = mount(AssistantConfirmCard, {
    props: { ask },
    attachTo: document.body,
    global: { stubs: { HintTooltip: { template: '<span><slot /></span>' } } },
  })
  wrappers.push(wrapper)
  return wrapper
}
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('assistant confirmation answers', () => {
  it('keeps single choice immediate submission', async () => {
    const wrapper = render({ prompt: '继续吗', options: ['继续', '取消'] })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('reply')).toEqual([['继续']])
  })

  it('submits multi-question radio choices and free text using the existing reply format', async () => {
    const wrapper = render({ questions: [
      { id: 'market', prompt: '选择市场', options: ['A股', '港股'] },
      { id: 'reason', prompt: '说明原因', allow_free_text: true },
    ] })
    await wrapper.get('[data-testid=assistant-confirm-submit]').trigger('click')
    expect(wrapper.find('[data-testid=assistant-confirm-error]').exists()).toBe(true)
    await wrapper.get('[role=radio]').trigger('click')
    expect(wrapper.emitted('reply')).toBeUndefined()
    await wrapper.get('textarea').setValue('观察成交量')
    await wrapper.get('[data-testid=assistant-confirm-submit]').trigger('click')
    expect(wrapper.emitted('reply')).toEqual([['1. [market] 选择市场 → A股\n2. [reason] 说明原因 → 观察成交量']])
  })

  it('keeps numeric shortcuts scoped to the focused question and does not intercept free text', async () => {
    const wrapper = render({ questions: [
      { id: 'one', prompt: '第一题', options: ['甲', '乙'] },
      { id: 'two', prompt: '第二题', options: ['丙', '丁'], allow_free_text: true },
    ] })
    await wrapper.findAll('fieldset')[1]!.trigger('focusin')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '2', bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('[role=radio]')[3]!.attributes('aria-checked')).toBe('true')
    await wrapper.get('textarea').setValue('自定')
    await wrapper.get('textarea').trigger('keydown', { key: '1' })
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('自定')
    expect(wrapper.emitted('reply')).toBeUndefined()
  })

  it('announces answered count and focuses the first required unanswered question', async () => {
    const wrapper = render({ questions: [
      { id: 'market', prompt: '选择市场', options: ['A股', '港股'] },
      { id: 'reason', prompt: '说明原因', allow_free_text: true },
    ] })
    expect(wrapper.get('[role=status]').text()).toContain('已回答 0/2')
    await wrapper.get('[data-testid=assistant-confirm-submit]').trigger('click')
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(wrapper.get('[role=radio]').element)
    expect(wrapper.get('[role=radiogroup]').attributes('aria-invalid')).toBe('true')
    expect(wrapper.get('[data-testid=assistant-confirm-error]').text()).toContain('选择市场')
    await wrapper.get('[role=radio]').trigger('click')
    expect(wrapper.get('[role=status]').text()).toContain('已回答 1/2')
    await wrapper.get('[data-testid=assistant-confirm-submit]').trigger('click')
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(wrapper.get('textarea').element)
    expect(wrapper.get('textarea').attributes('aria-describedby')).toBeTruthy()
    await wrapper.get('textarea').setValue('补充说明')
    expect(wrapper.get('[role=status]').text()).toContain('已回答 2/2')
    expect(wrapper.get('textarea').attributes('aria-invalid')).toBeUndefined()
    expect(wrapper.find('[data-testid=assistant-confirm-error]').exists()).toBe(false)
  })

  it('does not submit a held numeric key or IME composition', async () => {
    const wrapper = render({ prompt: '继续吗', options: ['继续', '取消'] })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '1', repeat: true }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '1', isComposing: true }))
    expect(wrapper.emitted('reply')).toBeUndefined()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '1' }))
    expect(wrapper.emitted('reply')).toEqual([['继续']])
  })
})

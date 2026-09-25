import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import TextField from './app/TextField.vue'
import Pager from './app/Pager.vue'
import UiField from './UiField.vue'
import { Input } from './input'
import PageTabs from './PageTabs.vue'
import { VISITOR_MODE } from '@/shared/composables/useAccess'

let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); document.body.replaceChildren() })

describe('shared foundation contracts', () => {
  it('preserves password reveal, clear, focus and visitor read controls', async () => {
    wrapper = mount(TextField, { attachTo: document.body, props: { modelValue: 'secret', showPassword: true, clearable: true }, global: { provide: { [VISITOR_MODE as symbol]: ref(true) } } })
    expect(wrapper.get('input').attributes('type')).toBe('password')
    await wrapper.get('[aria-label="显示密码"]').trigger('click')
    expect(wrapper.get('input').attributes('type')).toBe('text')
    await wrapper.get('[aria-label="清空输入"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([''])
    expect(document.activeElement).toBe(wrapper.get('input').element)
  })

  it('links a visible field label, description and error to the actual input', async () => {
    const Form = defineComponent({ components: { UiField, Input }, props: { error: String }, template: '<UiField label="名称" description="用于显示" :error="error"><Input /></UiField>' })
    wrapper = mount(Form, { props: { error: '' } })
    const input = wrapper.get('input')
    expect(wrapper.get('label').attributes('for')).toBe(input.attributes('id'))
    expect(wrapper.find(`#${input.attributes('aria-describedby')}`).text()).toBe('用于显示')
    await wrapper.setProps({ error: '请填写名称' })
    expect(input.attributes('aria-invalid')).toBe('true')
    expect(wrapper.find(`#${input.attributes('aria-describedby')}`).text()).toBe('请填写名称')
  })

  it('emits one page change and respects disabled and last-page bounds', async () => {
    wrapper = mount(Pager, { props: { currentPage: 1, pageSize: 10, total: 21 } })
    await wrapper.get('[aria-label="下一页"]').trigger('click')
    expect(wrapper.emitted('current-change')).toEqual([[2]])
    await wrapper.setProps({ currentPage: 3 })
    expect(wrapper.get('[aria-label="下一页"]').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ disabled: true })
    expect(wrapper.get('[aria-label="上一页"]').attributes('disabled')).toBeDefined()
  })

  it('uses filter buttons without phantom tab panels and pairs actual tabs explicitly', async () => {
    wrapper = mount(PageTabs, { props: { modelValue: 'a', items: [{ name: 'a', label: '全部' }, { name: 'b', label: '已启用' }] } })
    expect(wrapper.find('[role="tab"]').exists()).toBe(false)
    await wrapper.get('[data-slot="toggle-group-item"][data-state="on"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.setProps({ panelId: 'settings-content' })
    const tab = wrapper.get('[role="tab"][data-state="active"]')
    expect(tab.attributes('id')).toBe('settings-content-tab-a')
    expect(tab.attributes('aria-controls')).toBe('settings-content')
  })
})

import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import BasicForm from './BasicForm.vue'
import type { BasicFormSchema } from './basicFormTypes'

const schemas: BasicFormSchema[] = [
  { field: 'code', label: '代码', hint: '默认按日期归池', required: true },
  {
    field: 'strategy',
    label: '战法',
    hint: '战法标识要与工坊里的 slug 一致，比如 qianlong-close-v3 或 sanyuan-tail-v1',
  },
  { field: 'reason', label: '理由', componentProps: { type: 'textarea' }, fullRow: true },
]

function mountForm(props: Record<string, unknown> = {}) {
  return mount(BasicForm, {
    global: { plugins: [ElementPlus] },
    props: { schemas, ...props },
  })
}

describe('BasicForm 表单契约', () => {
  it('栅格落在 el-form 自身，el-form 与 el-form-item 之间没有裸元素', () => {
    const wrapper = mountForm({ columns: 2, hint: '同日同池同标的会覆盖上次裁决' })
    const form = wrapper.find('form.el-form')

    expect(form.classes()).toContain('basic-form--c2')
    // 契约核心：所有 form-item 都是 form 的直接子节点（插一层 div 就绕过 EP 的 label 宽度计算）
    const items = form.element.querySelectorAll('.el-form-item')
    expect(items.length).toBe(schemas.length + 1) // 3 字段 + 1 条表单级说明
    for (const item of items) {
      // 直接父节点就是 form 本身：中间多一层 div 这里立刻红
      expect(item.parentElement?.tagName).toBe('FORM')
      expect(item.parentElement?.className).toContain('basic-form')
    }
    wrapper.unmount()
  })

  it('默认右对齐 + label 宽取 --form-label-w，可被 prop 覆盖', () => {
    const wrapper = mountForm()
    expect(wrapper.find('form.el-form').classes()).toContain('el-form--label-right')
    const label = wrapper.find('.el-form-item__label')
    expect(label.attributes('style')).toContain('var(--form-label-w)')
    wrapper.unmount()

    const narrow = mountForm({ labelWidth: '72px' })
    expect(narrow.find('.el-form-item__label').attributes('style')).toContain('72px')
    narrow.unmount()
  })

  it('表单级说明借无 label 的 form-item 拿到与控件同缩进', () => {
    const wrapper = mountForm({ hint: '同日同池同标的会覆盖上次裁决' })
    const lead = wrapper.find('.basic-form__lead')
    expect(lead.exists()).toBe(true)
    expect(lead.find('.el-form-item__label').exists()).toBe(false)
    expect(lead.find('.el-form-item__content').attributes('style')).toContain(
      'var(--form-label-w)',
    )
    expect(lead.text()).toBe('同日同池同标的会覆盖上次裁决')
    wrapper.unmount()
  })

  it('hint ≤20 字跟控件左缘，>20 字沉到 label 旁的 tooltip', () => {
    const wrapper = mountForm()
    const items = wrapper.findAll('.el-form-item')
    const codeItem = items[0]
    const strategyItem = items[1]

    // 短说明：渲染在 content 里（控件左缘），不占 label 列
    const inlineHint = codeItem.find('.basic-form__hint')
    expect(inlineHint.exists()).toBe(true)
    expect(inlineHint.text()).toBe('默认按日期归池')
    expect(codeItem.find('.el-form-item__content').element.contains(inlineHint.element)).toBe(true)
    expect(codeItem.find('.basic-form__tip').exists()).toBe(false)

    // 长说明：版面上不留文案，只留 label 旁可聚焦的 tooltip 图标
    expect(strategyItem.find('.basic-form__hint').exists()).toBe(false)
    const tip = strategyItem.find('.basic-form__tip')
    expect(tip.exists()).toBe(true)
    expect(tip.attributes('tabindex')).toBe('0')
    expect(tip.attributes('aria-label')).toContain('qianlong-close-v3')
    wrapper.unmount()
  })

  it('fullRow 字段整行占满，必填星号钉在 label 右端', () => {
    const wrapper = mountForm({ columns: 2 })
    const items = wrapper.findAll('.el-form-item')
    expect(items[2].classes()).toContain('is-full-row')
    expect(items[0].classes()).toContain('asterisk-right')
    wrapper.unmount()
  })
})

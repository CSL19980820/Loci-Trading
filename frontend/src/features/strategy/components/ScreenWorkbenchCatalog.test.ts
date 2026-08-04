import { mount } from '@vue/test-utils'
import ElementPlus, { ElSelect, ElTabs } from 'element-plus'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import type { ScreenSkillCatalog } from '@/shared/types/quant'

import ScreenWorkbenchCatalog from './ScreenWorkbenchCatalog.vue'

const catalog: ScreenSkillCatalog = {
  runtimes: [],
  dialects: [],
  fields: [],
  functions: [
    {
      name: 'MA',
      category: '趋势',
      signature: 'MA(X, N)',
      summary: '移动平均。',
      description: '返回 N 周期简单移动平均。',
      insert_text: 'MA(CLOSE, N)',
      examples: ['BASE: MA(CLOSE, N);'],
      dialects: ['loci', 'tdx', 'ths'],
      source: 'formula',
    },
    {
      name: 'CROSS',
      category: '交叉',
      signature: 'CROSS(A, B)',
      summary: '上穿判断。',
      description: 'A 上穿 B 时为真。',
      insert_text: 'CROSS(A, B)',
      examples: [],
      dialects: ['loci'],
      source: 'formula',
    },
  ],
  snippets: [],
}

describe('ScreenWorkbenchCatalog', () => {
  it('keeps the chosen category until the user changes catalog tabs', async () => {
    const wrapper = mount(ScreenWorkbenchCatalog, {
      props: { catalog },
      global: { plugins: [ElementPlus] },
    })
    const categorySelect = wrapper.findAllComponents(ElSelect)[0]!

    categorySelect.vm.$emit('update:modelValue', '趋势')
    await nextTick()
    expect(categorySelect.props('modelValue')).toBe('趋势')

    wrapper.findComponent(ElTabs).vm.$emit('update:modelValue', 'fields')
    await nextTick()
    expect(categorySelect.props('modelValue')).toBe('')
  })
})

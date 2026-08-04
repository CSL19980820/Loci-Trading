import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import BasicForm from './BasicForm.vue'
import type { BasicFormSchema } from './basicFormTypes'

const schemas: BasicFormSchema[] = [
  {
    field: 'dateRange',
    label: '日期',
    component: 'date-picker',
    componentProps: {
      type: 'daterange',
      'value-format': 'YYYY-MM-DD',
    },
  },
]

describe('BasicForm daterange sync', () => {
  it('does not chase parent-cloned array refs into an update loop', async () => {
    let emits = 0
    let modelValue: Record<string, unknown> = { dateRange: null }

    const wrapper = mount(BasicForm, {
      global: { plugins: [ElementPlus] },
      props: {
        schemas,
        modelValue,
        'onUpdate:modelValue': (value: Record<string, unknown>) => {
          emits += 1
          if (emits > 40) throw new Error('BasicForm v-model update loop')
          const range = value.dateRange
          // 模拟 Journal/Pool：每次 setter 都 new 一个数组
          modelValue = {
            dateRange:
              Array.isArray(range) && range.length === 2
                ? [String(range[0] ?? ''), String(range[1] ?? '')]
                : null,
          }
          void wrapper.setProps({ modelValue })
        },
      },
    })

    wrapper.vm.setFieldsValue({ dateRange: ['2026-07-01', '2026-07-29'] })
    await nextTick()
    await nextTick()
    await nextTick()

    expect(emits).toBeLessThan(5)
    expect(modelValue.dateRange).toEqual(['2026-07-01', '2026-07-29'])
    wrapper.unmount()
  })
})

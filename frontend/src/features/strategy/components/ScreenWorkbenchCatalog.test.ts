import { mount } from '@vue/test-utils'
import ElementPlus, { ElTabs } from 'element-plus'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import type { ScreenSkillCatalog } from '@/shared/types/quant'

import ScreenWorkbenchCatalog from './ScreenWorkbenchCatalog.vue'

const catalog: ScreenSkillCatalog = {
  runtimes: [],
  dialects: [],
  fields: [
    {
      name: 'open',
      label: '开盘价',
      summary: '当日开盘成交价',
      source: 'market.daily.open',
    },
  ],
  functions: [
    {
      name: 'MA',
      category: '均线',
      signature: 'MA(X, N)',
      summary: '简单移动平均',
      description: '最近 N 根的简单均线。',
      insert_text: 'MA(CLOSE, N)',
      examples: ['BASE: MA(CLOSE, N);'],
      dialects: ['loci', 'tdx', 'ths'],
      source: 'formula',
    },
    {
      name: 'CROSS',
      category: '逻辑',
      signature: 'CROSS(A, B)',
      summary: '上穿',
      description: 'A 上穿 B 时为真。',
      insert_text: 'CROSS(A, B)',
      examples: [],
      dialects: ['loci'],
      source: 'formula',
    },
  ],
  snippets: [
    {
      id: 'ma-breakout',
      title: '均线突破',
      runtime: 'formula',
      dialect: 'loci',
      summary: '均线突破',
      code: 'PICK: CLOSE>MA(CLOSE,N);',
      required_fields: ['close'],
      params: {},
      factors: [],
    },
  ],
}

describe('ScreenWorkbenchCatalog', () => {
  it('keeps the chosen category until the user changes catalog tabs', async () => {
    const wrapper = mount(ScreenWorkbenchCatalog, {
      props: { catalog, layout: 'dialog' },
      global: { plugins: [ElementPlus] },
    })

    const trendBtn = wrapper.findAll('.catalog__cat').find((node) => node.text().includes('均线'))
    expect(trendBtn).toBeTruthy()
    await trendBtn!.trigger('click')
    await nextTick()
    expect(wrapper.find('.catalog__cat--active').text()).toContain('均线')

    wrapper.findComponent(ElTabs).vm.$emit('update:modelValue', 'fields')
    await nextTick()
    expect(wrapper.find('.catalog__cat--active').text()).toContain('全部')
    expect(wrapper.text()).toContain('开盘价')
    expect(wrapper.text()).toContain('日线行情')
    expect(wrapper.text()).not.toContain('market.daily.open')
  })
})

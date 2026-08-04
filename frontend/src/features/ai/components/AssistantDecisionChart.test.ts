import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AssistantDecisionChart from './AssistantDecisionChart.vue'

const stubs = {
  ElTag: { template: '<span><slot /></span>' },
  ElDescriptions: { template: '<dl><slot /></dl>' },
  ElDescriptionsItem: { props: ['label'], template: '<div><dt>{{ label }}</dt><dd><slot /></dd></div>' },
  ElEmpty: { props: ['description'], template: '<p>{{ description }}</p>' },
}

describe('AssistantDecisionChart', () => {
  it('displays the candidate evidence returned by the verdict artifact', () => {
    const wrapper = mount(AssistantDecisionChart, {
      props: {
        artifact: {
          id: 'verdict-1', kind: 'candidate_verdict', title: '候选精选图',
          data: {
            candidates: [{
              code: '600000', name: '浦发银行', decision: '精选', reason: '量价配合', timing: '尾盘确认',
              evidence: { invalidation: '跌破 MA20', close: 12, pct_chg: 1.25, ma5: 11.4, ma20: 10, volume_ratio: 1.8 },
            }],
          },
        },
      },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('600000')
    expect(wrapper.text()).toContain('+1.25%')
    expect(wrapper.text()).toContain('+5.26%')
    expect(wrapper.text()).toContain('1.80')
    expect(wrapper.text()).toContain('量价配合')
    expect(wrapper.text()).toContain('尾盘确认')
    expect(wrapper.text()).toContain('跌破 MA20')
  })

  it('shows an empty state for broken or empty artifacts without throwing', () => {
    const wrapper = mount(AssistantDecisionChart, {
      props: {
        artifact: {
          id: 'broken-1',
          kind: 'qianlong_kline',
          title: '坏图',
          data: null as unknown as Record<string, unknown>,
        },
      },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('工具未返回可展示的数据')
  })
})

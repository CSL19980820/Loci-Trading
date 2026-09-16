import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import GuardianReportDocument from './GuardianReportDocument.vue'

it('keeps a named stock, its accounting and all exit plans in one section', () => {
  const wrapper = mount(GuardianReportDocument, { props: { sections: [
    { heading: '全天复盘', kind: 'overview', paragraphs: ['整体判断'], stats: [], plans: [] },
    { heading: '精华制药（002349）', kind: 'stock', paragraphs: ['今日个股回顾'], stats: [{ label: '含费成本', value: '8.7023元/股' }], plan_date: '2026-09-15', plans: [
      { label: '持股', detail: '趋势保持', meta: '次日复核' }, { label: '止盈 · 2500股', detail: '冲高滞涨', meta: '盘中复核' }, { label: '止损 · 4500股', detail: '逻辑失效', meta: 'T+1后执行' },
    ] },
  ] } })
  const stock = wrapper.find('.kind-stock')
  expect(stock.text()).toContain('精华制药（002349）')
  expect(stock.text()).toContain('8.7023元/股')
  expect(stock.findAll('.document-plan')).toHaveLength(3)
  expect(wrapper.findAll('.kind-stock')).toHaveLength(1)
  expect(wrapper.find('.kind-overview').text()).not.toContain('止损')
  wrapper.unmount()
})

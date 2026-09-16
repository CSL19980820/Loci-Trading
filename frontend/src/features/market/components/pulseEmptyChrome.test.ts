import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-router', () => ({
  useRoute: () => ({ fullPath: '/' }),
  useRouter: () => ({ push: () => Promise.resolve() }),
}))

import EmptyState from '@/shared/components/ui/EmptyState.vue'

import PulseIndexStrip from './PulseIndexStrip.vue'
import PulseMarketBoard from './PulseMarketBoard.vue'
import PulsePickTable from './PulsePickTable.vue'
import PulseTrackTable from './PulseTrackTable.vue'

function mountTable(component: object, props: Record<string, unknown>) {
  return mount(component, {
    props,
    global: {
      stubs: {
        StockLink: { props: ['code', 'name'], template: '<span>{{ name }}</span>' },
        'el-tooltip': { template: '<div><slot /></div>' },
      },
    },
  })
}

function columnLabels(wrapper: {
  findAllComponents: (query: { name: string }) => Array<{ props: (key: string) => unknown }>
}): string[] {
  return wrapper
    .findAllComponents({ name: 'ElTableColumn' })
    .map((col) => String(col.props('label') ?? ''))
    .filter(Boolean)
}

function columnAligns(
  wrapper: { findAllComponents: (query: { name: string }) => Array<{ props: (key: string) => unknown }> },
  labels: string[],
): string[] {
  const columns = wrapper.findAllComponents({ name: 'ElTableColumn' })
  return labels.map((label) => {
    const col = columns.find((item) => String(item.props('label') ?? '') === label)
    return String(col?.props('align') ?? '')
  })
}

describe('盯盘空态仍露终端骨架', () => {
  it('指数带无报价时仍占满五个主指数槽，数值是 —', () => {
    const wrapper = mount(PulseIndexStrip, {
      props: { indices: [], alertCount: 0 },
    })

    expect(wrapper.find('.tape--void').exists()).toBe(true)
    expect(wrapper.findAll('.tape__cell').length).toBeGreaterThanOrEqual(5)
    expect(wrapper.text()).toContain('上证指数')
    expect(wrapper.text()).toContain('深证成指')
    expect(wrapper.text()).toContain('创业板指')
    expect(wrapper.text()).toContain('科创50')
    expect(wrapper.text()).toContain('沪深300')
    expect(wrapper.findAll('.tape__price').every((el) => el.text() === '—')).toBe(true)
    wrapper.unmount()
  })

  it('近选跟踪无行时仍挂表与列定义', () => {
    const wrapper = mountTable(PulseTrackTable, {
      title: '近选跟踪',
      rows: [],
      empty: '近5日无精选',
    })

    expect(wrapper.find('.pulse-table').exists()).toBe(true)
    expect(columnLabels(wrapper)).toEqual(expect.arrayContaining(['名称', '选入', '最新', '涨跌幅']))
    expect(columnAligns(wrapper, ['名称', '选入', '涨跌幅', '战法'])).toEqual([
      'left',
      'right',
      'right',
      'left',
    ])
    expect(wrapper.findComponent(EmptyState).props('description')).toBe('近5日无精选')
    expect(wrapper.find('.pulse-panel__empty').text()).toContain('去选股')
    wrapper.unmount()
  })

  it('今日选股无行时仍挂表与列定义', () => {
    const wrapper = mountTable(PulsePickTable, {
      title: '今日选股',
      rows: [],
      empty: '今日未选出',
    })

    expect(wrapper.find('.pulse-table').exists()).toBe(true)
    expect(columnLabels(wrapper)).toEqual(expect.arrayContaining(['#', '名称', '今涨', '评分']))
    expect(columnAligns(wrapper, ['名称', '今涨', '评分'])).toEqual(['left', 'right', 'right'])
    expect(wrapper.findComponent(EmptyState).props('description')).toBe('今日未选出')
    wrapper.unmount()
  })

  it('样本榜无行时仍挂表与列定义', () => {
    const wrapper = mountTable(PulseMarketBoard, {
      tab: 'gain',
      rows: [],
      pctOf: () => null,
    })

    expect(wrapper.find('.pulse-table').exists()).toBe(true)
    expect(columnLabels(wrapper)).toEqual(expect.arrayContaining(['名称', '涨幅', '板块']))
    expect(columnAligns(wrapper, ['名称', '涨幅', '板块'])).toEqual(['left', 'right', 'left'])
    expect(wrapper.findComponent(EmptyState).props('description')).toBe('暂无榜单')
    expect(wrapper.find('.pulse-panel__empty').text()).toContain('重新加载')
    wrapper.unmount()
  })
})

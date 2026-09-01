import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import WinRateView from './WinRateView.vue'
import { getWinRateSummary, getWinRateTrend } from '@/shared/api/quant'

vi.mock('@/shared/api/quant', () => ({
  CapabilityUnavailableError: class CapabilityUnavailableError extends Error {},
  getWinRateSummary: vi.fn(),
  getWinRateTrend: vi.fn(),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('WinRateView trend changes', () => {
  it('keeps the trend for the latest granularity when a slower prior request resolves last', async () => {
    const month = deferred<never>()
    const week = deferred<never>()
    vi.mocked(getWinRateSummary).mockResolvedValue([{ strategy_tag: 'A' }] as never)
    vi.mocked(getWinRateTrend).mockImplementation((options) =>
      options?.granularity === 'month' ? month.promise : week.promise,
    )
    const wrapper = mount(WinRateView, {
      global: {
        stubs: {
          HeaderActions: { template: '<div><slot /></div>' },
          Sheet: { template: '<section><slot /><slot name="actions" /></section>' },
          BasicTable: { props: ['dataSource'], template: '<pre>{{ dataSource }}</pre>' },
          EmptyState: true,
          PageBusy: true,
          'el-select': {
            props: ['modelValue'],
            template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>',
          },
          'el-option': true,
          'el-checkbox': true,
          'el-button': { template: '<button><slot /></button>' },
          'el-tag': { template: '<span><slot /></span>' },
        },
      },
    })
    await flushPromises()

    await wrapper.get('select').setValue('week')
    week.resolve([{ period: '2026-W01', strategy_tag: 'A', win_rate: 88 }] as never)
    await flushPromises()
    month.resolve([{ period: '2026-01', strategy_tag: 'A', win_rate: 12 }] as never)
    await flushPromises()

    expect(wrapper.text()).toContain('2026-W01')
    expect(wrapper.text()).not.toContain('2026-01')
  })
})

describe('WinRateView 战法展示', () => {
  /*
   * 用户反复点名：界面上不许再出现 `sanyuan-tail-v1` 这类英文 slug。
   * 主表战法列、分周期 check-tag、趋势表头三处都要落中文短名，
   * slug 只允许留在 row-key / activeTags / 调试 tooltip 里。
  */
  it('renders Chinese strategy names instead of English slugs', async () => {
    vi.mocked(getWinRateSummary).mockResolvedValue([
      {
        strategy_tag: 'sanyuan-tail-v1',
        source: 'candidates',
        total: 14,
        wins: 8,
        win_rate: 57.1,
        avg_return: 1.23,
        last_reviewed: '2026-08-20',
        horizons: { t1: { n: 14, win_rate: 57.1 }, t3: { n: 4, win_rate: 75 } },
      },
    ] as never)
    vi.mocked(getWinRateTrend).mockResolvedValue([
      { period: '2026-08', strategy_tag: 'sanyuan-tail-v1', win_rate: 60, total: 5 },
    ] as never)

    const wrapper = mount(WinRateView, {
      global: {
        stubs: {
          Sheet: { template: '<section><slot name="actions" /><slot /></section>' },
          BasicTable: {
            props: ['dataSource', 'columns'],
            template:
              '<div><span v-for="col in columns" :key="col.prop">{{ col.label }}</span>' +
              '<div v-for="(row, i) in dataSource" :key="i"><slot name="tag" :row="row" /></div></div>',
          },
          EmptyState: true,
          PageBusy: true,
          'el-select': { template: '<select><slot /></select>' },
          'el-option': true,
          'el-check-tag': { template: '<span><slot /></span>' },
          'el-tooltip': { template: '<span><slot /></span>' },
          'el-button': { template: '<button><slot /></button>' },
          'el-tag': { template: '<span><slot /></span>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('三源尾盘共振')
    expect(wrapper.text()).not.toContain('sanyuan-tail-v1')
    wrapper.unmount()
  })
})

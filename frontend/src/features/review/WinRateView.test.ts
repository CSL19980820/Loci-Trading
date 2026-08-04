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

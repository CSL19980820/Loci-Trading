import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { StrategyInfo } from '@/shared/types/quant'

vi.mock('@/shared/api/quant', () => ({ runBacktest: vi.fn(), runHorizonBacktest: vi.fn() }))
vi.mock('element-plus', async importOriginal => ({
  ...await importOriginal<Record<string, unknown>>(),
  ElMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))
import { runHorizonBacktest } from '@/shared/api/quant'
import QuantBacktestPanel from './QuantBacktestPanel.vue'

const strategy: StrategyInfo = {
  slug: 'ui-test', name: '界面测试战法', params: {}, description: '', required_fields: [], min_bars: 60,
  entry_timing: 'next_open',
}
const wrappers: Array<{ unmount: () => void }> = []

function mountPanel() {
  const wrapper = mount(QuantBacktestPanel, {
    props: { strategies: [strategy] },
    attachTo: document.body,
    global: { plugins: [createPinia()] },
  })
  wrappers.push(wrapper)
  return wrapper
}

describe('backtest controls while waiting', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    localStorage.clear()
    vi.mocked(runHorizonBacktest).mockImplementation((_payload, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    }))
  })
  afterEach(() => {
    wrappers.splice(0).forEach(wrapper => wrapper.unmount())
    document.body.innerHTML = ''
  })

  it('submits once and leaves a usable stop action outside any loading mask', async () => {
    const wrapper = mountPanel()
    await wrapper.get('.bt-rail__form').trigger('submit')
    await flushPromises()
    expect(runHorizonBacktest).toHaveBeenCalledTimes(1)
    expect(wrapper.get('.bt').attributes('aria-busy')).toBe('true')
    expect(wrapper.get('[role="status"]').text()).toContain('正在回测')
    expect(wrapper.get('.bt').element.querySelector(':scope > .el-loading-mask')).toBeNull()

    const stop = wrapper.findAll('button').find(button => button.text() === '停止等待')
    expect(stop?.exists()).toBe(true)
    expect(stop?.attributes('disabled')).toBeUndefined()
    await stop!.trigger('click')
    await flushPromises()
    expect(vi.mocked(runHorizonBacktest).mock.calls[0]?.[1]?.signal?.aborted).toBe(true)
    expect(wrapper.get('.bt').attributes('aria-busy')).toBe('false')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.findAll('button').some(button => button.text() === '停止等待')).toBe(false)
  })

  it('cancels the request when the panel unmounts', async () => {
    const wrapper = mountPanel()
    await wrapper.get('.bt-rail__form').trigger('submit')
    await flushPromises()
    const signal = vi.mocked(runHorizonBacktest).mock.calls[0]?.[1]?.signal
    expect(signal?.aborted).toBe(false)
    wrapper.unmount()
    wrappers.pop()
    await flushPromises()
    expect(signal?.aborted).toBe(true)
  })
})

import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { StrategyInfo } from '@/shared/types/quant'
import { useResearchBacktestJob } from './useResearchBacktestJob'

vi.mock('@/shared/api/quant', () => ({ getStrategies: vi.fn() }))
vi.mock('@/shared/api/quant_research', () => ({
  getResearchBacktestJob: vi.fn(), getResearchBacktestRun: vi.fn(), getResearchWorkflow: vi.fn(),
  listResearchBacktestRuns: vi.fn(), replayResearchBacktestRun: vi.fn(), submitResearchBacktestJob: vi.fn(),
}))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<Record<string, unknown>>(),
  ElMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))
import { getResearchBacktestJob, submitResearchBacktestJob } from '@/shared/api/quant_research'

const strategy: StrategyInfo = {
  slug: 'impulse-pullback-tail-v1', name: '涨停大涨回落转强',
  description: '原式尾盘回放', entry_timing: 'next_open', params: {},
  required_fields: ['open', 'high', 'low', 'close', 'volume'], min_bars: 60,
  backtest_config: {
    hold_days: 9, stop_loss_pct: null, take_profit_pct: null,
    commission_bps: 3, stamp_duty_bps: 10, slippage_bps: 7,
    strict_limit_prices: true, economic_returns: true,
    signal_dataset: 'impulse-1450-20250101-20260911-v1', valuation_end: '2026-09-11',
    start: '2025-01-01', end: '2026-09-11', account_model: 'daily_close',
    initial_capital: 200000, max_positions: 5, lot_size: 100,
    split: { train_start: '2025-01-01', train_end: '2025-12-31', oos_start: '2026-01-01', oos_end: '2026-09-11' },
  },
}
const wrappers: Array<{ unmount: () => void }> = []
function harness() {
  let panel!: ReturnType<typeof useResearchBacktestJob>
  const wrapper = mount(defineComponent({ setup() {
    panel = useResearchBacktestJob()
    return () => null
  } }))
  wrappers.push(wrapper)
  return panel
}

describe('research backtest strategy template', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const job = { id: 'test-job', status: 'running', request: {}, run_id: '', error: '', created_at: '', updated_at: '' } as const
    vi.mocked(submitResearchBacktestJob).mockResolvedValue({ job })
    vi.mocked(getResearchBacktestJob).mockResolvedValue({ job })
  })
  afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))

  it('initializes ranges and capital then submits the complete nested execution contract', async () => {
    const panel = harness()
    panel.strategies.value = [strategy]
    panel.form.value.strategy = strategy.slug
    await flushPromises()
    expect(panel.range.value).toEqual(['2025-01-01', '2026-09-11'])
    expect(panel.trainRange.value).toEqual(['2025-01-01', '2025-12-31'])
    expect(panel.oosRange.value).toEqual(['2026-01-01', '2026-09-11'])
    expect(panel.form.value).toMatchObject({ holdDays: 9, initialCapital: 200000, maxPositions: 5, strictPit: false })
    await panel.submit()
    const request = vi.mocked(submitResearchBacktestJob).mock.calls[0]?.[0]
    expect(request).toMatchObject({
      strategy: strategy.slug, start: '2025-01-01', end: '2026-09-11',
      account_model: 'daily_close', initial_capital: 200000, max_positions: 5, lot_size: 100,
      strict_pit: false, split: strategy.backtest_config?.split,
    })
    expect(request?.backtest_config).toEqual({
      hold_days: 9, stop_loss_pct: null, take_profit_pct: null,
      commission_bps: 3, stamp_duty_bps: 10, slippage_bps: 7,
      strict_limit_prices: true, economic_returns: true,
      signal_dataset: 'impulse-1450-20250101-20260911-v1', valuation_end: '2026-09-11',
    })
  })

  it('follows edited end without resetting it on a catalog refresh', async () => {
    const panel = harness()
    panel.strategies.value = [strategy]
    panel.form.value.strategy = strategy.slug
    await flushPromises()
    panel.range.value = ['2025-01-01', '2026-06-30']
    panel.oosRange.value = ['2026-01-01', '2026-06-30']
    panel.strategies.value = [{ ...strategy }]
    await flushPromises()
    await panel.submit()
    expect(vi.mocked(submitResearchBacktestJob).mock.calls[0]?.[0]).toMatchObject({
      end: '2026-06-30', backtest_config: { valuation_end: '2026-06-30' },
    })
  })

  it('leaves ordinary strategy execution and account defaults unchanged', async () => {
    const panel = harness()
    panel.strategies.value = [{ slug: 'legacy', name: '普通战法' } as StrategyInfo]
    panel.form.value.strategy = 'legacy'
    panel.range.value = ['2025-01-01', '2026-09-11']
    panel.trainRange.value = ['2025-01-01', '2025-12-31']
    panel.oosRange.value = ['2026-01-01', '2026-09-11']
    await flushPromises()
    await panel.submit()
    const request = vi.mocked(submitResearchBacktestJob).mock.calls[0]?.[0]
    expect(request?.backtest_config).toEqual({ hold_days: 3 })
    expect(request?.max_positions).toBe(2)
    expect(request).not.toHaveProperty('account_model')
    expect(request).not.toHaveProperty('lot_size')
  })
})

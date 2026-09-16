import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { BacktestResult, StrategyInfo } from '@/shared/types/quant'
import { useQuantBacktestPanel, type QuantBacktestPanel } from './useQuantBacktestPanel'

vi.mock('@/shared/api/quant', () => ({ runBacktest: vi.fn(), runHorizonBacktest: vi.fn() }))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<Record<string, unknown>>(),
  ElMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))
import { runBacktest, runHorizonBacktest } from '@/shared/api/quant'

const strategy: StrategyInfo = {
  slug: 'impulse-pullback-tail-v1', name: '涨停大涨回落转强', entry_timing: 'next_open', params: {},
  description: '原式尾盘回放', required_fields: ['open', 'high', 'low', 'close', 'volume'], min_bars: 60,
  backtest_config: {
    hold_days: 9, stop_loss_pct: null, take_profit_pct: null, benchmark: null,
    commission_bps: 3, stamp_duty_bps: 10, slippage_bps: 7,
    strict_limit_prices: true, economic_returns: true,
    signal_dataset: 'impulse-1450-20250101-20260911-v1', valuation_end: '2026-09-11',
    start: '2025-01-01', end: '2026-09-11', account_model: 'daily_close',
    initial_capital: 200000, max_positions: 5, lot_size: 100,
  },
}
const wrappers: Array<{ unmount: () => void }> = []

function harness(items = [strategy]) {
  const strategies = ref(items)
  let panel!: QuantBacktestPanel
  const wrapper = mount(defineComponent({ setup() {
    panel = useQuantBacktestPanel({ strategies })
    return () => null
  } }), { global: { plugins: [createPinia()] } })
  wrappers.push(wrapper)
  return { panel, strategies }
}

describe('quant backtest strategy template', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    vi.mocked(runBacktest).mockResolvedValue({ metrics: { trades: 0 } } as BacktestResult)
  })
  afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))

  it('loads the template and sends all execution fields, including explicit null exits', async () => {
    sessionStorage.setItem('loci.quant-backtest.prefs.v1', JSON.stringify({ commissionBps: 12, stampDutyBps: 20, slippageBps: 15 }))
    const { panel } = harness()
    await flushPromises()
    expect(panel.mode.value).toBe('trade')
    expect(panel.range.value).toEqual(['2025-01-01', '2026-09-11'])
    expect(panel.holdDays.value).toBe(9)
    expect(panel.stopLossEnabled.value).toBe(false)
    expect(panel.slippageBps.value).toBe(7)
    expect(panel.entryDetail.value).toContain('含买入日 10 日')
    await panel.run()
    expect(runHorizonBacktest).not.toHaveBeenCalled()
    expect(runBacktest).toHaveBeenCalledWith({
      strategy: strategy.slug, start: '2025-01-01', end: '2026-09-11', mode: 'trade',
      hold_days: 9, stop_loss_pct: null, take_profit_pct: null, benchmark: null,
      commission_bps: 3, stamp_duty_bps: 10, slippage_bps: 7,
      strict_limit_prices: true, economic_returns: true,
      signal_dataset: 'impulse-1450-20250101-20260911-v1', valuation_end: '2026-09-11',
      include_trades: true,
    }, { signal: expect.any(AbortSignal) })
  })

  it('uses edited end for valuation and preserves edits when the same catalog entry refreshes', async () => {
    const { panel, strategies } = harness()
    await flushPromises()
    panel.range.value = ['2026-01-01', '2026-06-30']
    panel.onRangeChange()
    strategies.value = [{ ...strategy }]
    await flushPromises()
    expect(panel.range.value).toEqual(['2026-01-01', '2026-06-30'])
    await panel.run()
    expect(vi.mocked(runBacktest).mock.calls[0]?.[0]).toMatchObject({ end: '2026-06-30', valuation_end: '2026-06-30' })
  })

  it('does not add replay fields to an ordinary strategy or after switching away', async () => {
    const legacy = { slug: 'legacy', name: '普通战法', params: {} } as StrategyInfo
    const { panel } = harness([strategy, legacy])
    await flushPromises()
    panel.strategySlug.value = legacy.slug
    await flushPromises()
    await panel.run()
    const payload = vi.mocked(runBacktest).mock.calls[0]?.[0]
    expect(payload).not.toHaveProperty('signal_dataset')
    expect(payload).not.toHaveProperty('valuation_end')
    expect(payload).not.toHaveProperty('strict_limit_prices')
    expect(payload).not.toHaveProperty('economic_returns')
  })

  it('rejects Horizon rather than silently discarding the historical snapshot dataset', async () => {
    const { panel } = harness()
    await flushPromises()
    panel.mode.value = 'horizon'
    panel.range.value = ['2026-01-01', '2026-06-30']
    await panel.run()
    expect(runBacktest).not.toHaveBeenCalled()
    expect(runHorizonBacktest).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('该战法的历史14:50数据用于成交回测，请选择成交模式')
  })
})

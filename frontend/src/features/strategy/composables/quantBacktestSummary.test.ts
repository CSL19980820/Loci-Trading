import { describe, expect, it } from 'vitest'

import {
  buildHorizonCompareRows,
  buildHorizonSummaryText,
  buildTradeSummaryText,
  formatSignedPct,
  optimismGapPct,
  skippedText,
} from './quantBacktestSummary'

describe('quantBacktestSummary', () => {
  it('computes optimism gap as high minus close', () => {
    expect(optimismGapPct(8.5, 3.2)).toBe(5.3)
    expect(optimismGapPct(null, 1)).toBeNull()
  })

  it('formats signed percents', () => {
    expect(formatSignedPct(1.2)).toBe('+1.20%')
    expect(formatSignedPct(-2)).toBe('-2.00%')
    expect(formatSignedPct(null)).toBe('—')
  })

  it('builds compare rows and summaries', () => {
    const t1 = { n: 10, win_rate: 55, avg: 4, close_avg: 1.5 }
    const t3 = { n: 9, win_rate: 50, avg: 6, close_avg: 2 }
    const rows = buildHorizonCompareRows(t1, t3)
    expect(rows.find((r) => r.key === 'gap')?.t1).toBe('+2.50%')
    const hz = buildHorizonSummaryText({
      strategy: 'demo',
      range: '2026-01-01 — 2026-03-01',
      entry: '尾盘买',
      t1,
      t3,
    })
    expect(hz).toContain('T+1')
    expect(hz).toContain('乐观差')
    const trade = buildTradeSummaryText({
      strategy: 'demo',
      range: '2026-01-01 — 2026-03-01',
      metrics: { trades: 12, win_rate: 50, avg_net_return: 1.2, profit_factor: 1.5, expectancy: 1.2 },
      performance: {
        available: true,
        cumulative_return_pct: 8,
        max_drawdown_pct: -5,
        sharpe: 0.8,
        cagr_pct: 20,
      },
    })
    expect(trade).toContain('诊断累计')
    expect(trade).toContain('非真实多仓')
  })

  it('joins skipped reasons', () => {
    expect(skippedText({ 停牌: 2, 无信号: 0 })).toBe('停牌 2')
    expect(skippedText(undefined)).toBe('')
  })
})

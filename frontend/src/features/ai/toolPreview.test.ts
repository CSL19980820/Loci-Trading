import { describe, expect, it } from 'vitest'

import { formatToolPreview } from './toolPreview'

describe('formatToolPreview', () => {
  it('summarizes ledger dashboard json instead of dumping it', () => {
    const preview = formatToolPreview(
      'ledger_dashboard',
      JSON.stringify({
        as_of: '2026-08-05',
        account: {
          cost_exposure: 100908,
          today_realized_pnl: 4154,
          unrealized_pnl: -120,
          cash: 130320.87,
        },
        positions: [{}, {}, {}, {}],
      }),
    )
    expect(preview).toContain('2026-08-05')
    expect(preview).toContain('持仓 4 只')
    expect(preview).toContain('成本敞口')
    expect(preview).not.toContain('"as_of"')
  })

  it('keeps human preview text as-is', () => {
    expect(formatToolPreview('ledger_positions', '持仓 4 只 · 成本 100908')).toBe(
      '持仓 4 只 · 成本 100908',
    )
  })
})

import { describe, expect, it } from 'vitest'

import { resolveKlineDblclickIndex } from './klineDblclick'

const dates = [
  '2025-04-30',
  '2025-05-06',
  '2026-07-09',
  '2026-07-31',
]

describe('resolveKlineDblclickIndex', () => {
  it('prefers category name over filtered dataIndex', () => {
    // Zoom shows last two bars; filtered dataIndex 0 would wrongly hit 2025-04-30
    expect(
      resolveKlineDblclickIndex({
        dates,
        name: '2026-07-09',
        dataIndex: 0,
        hoverIndex: 3,
      }),
    ).toBe(2)
  })

  it('falls back to hover index when name missing', () => {
    expect(
      resolveKlineDblclickIndex({
        dates,
        dataIndex: 0,
        hoverIndex: 3,
      }),
    ).toBe(3)
  })

  it('uses absolute dataIndex only when name/hover absent', () => {
    expect(
      resolveKlineDblclickIndex({
        dates,
        dataIndex: 2,
      }),
    ).toBe(2)
  })

  it('rejects stale name/dataIndex mismatch', () => {
    expect(
      resolveKlineDblclickIndex({
        dates,
        name: '2099-01-01',
        dataIndex: 0,
      }),
    ).toBe(-1)
  })
})

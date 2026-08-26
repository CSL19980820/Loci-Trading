import { describe, expect, it } from 'vitest'

import type { SecondWaveLatest } from '@/shared/api/quant_ops'

import { snapshotMeta, snapshotRows } from './pulseSecondWaveLogic'

const snap: SecondWaveLatest = {
  available: true,
  slug: 'dragon-second-wave',
  trade_date: '2026-08-13',
  observed_at: '2026-08-13T10:05:00+08:00',
  quote_source: 'sina',
  breadth_pct: 61,
  gate_pass: true,
  pool_size: 39,
  pool_checked: 38,
  min_strength: 45,
  below_min_strength: 1,
  triggered: [
    { code: '603580', name: '艾艾精工', strength: 80, price: 12.3, pct: 2.1, tags: ['涨幅甜区'] },
    { code: '000002', name: '弱票', strength: 30, price: 10, pct: -1, tags: ['涨幅险区'] },
  ],
  picks: [{ code: '603580', score: 80 }],
}

describe('pulseSecondWaveLogic', () => {
  it('marks picks as alerted and keeps below-line rows', () => {
    const rows = snapshotRows(snap, 45)
    expect(rows).toHaveLength(2)
    expect(rows[0]?.alerted).toBe(true)
    expect(rows[1]?.alerted).toBe(false)
    expect(rows[0]?.tags).toContain('甜区')
  })

  it('shows scan clock in meta', () => {
    expect(snapshotMeta(snap, false)).toContain('10:05')
    expect(snapshotMeta(null, true)).toContain('读取')
    expect(snapshotMeta(null, false)).toContain('尚未跑过')
  })
})

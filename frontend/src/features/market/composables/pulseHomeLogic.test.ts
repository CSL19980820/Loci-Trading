import { describe, expect, it } from 'vitest'

import type { BoardRow } from '@/shared/types/quant'

import {
  changeFromEntry,
  dedupeTrackRowsByDayCode,
  effectivePct,
  horizonReturn,
  localIsoDate,
  rankBoardRows,
  splitScreenDates,
} from './pulseHomeLogic'

function row(partial: Partial<BoardRow> & { code: string }): BoardRow {
  return {
    code: partial.code,
    name: partial.name ?? partial.code,
    market: '',
    board: '',
    industry: '',
    instrument_type: 'STOCK',
    status: 'normal',
    local_date: '',
    local_close: null,
    local_pct: partial.local_pct ?? null,
    local_change: null,
    price: null,
    pct: partial.pct ?? null,
    change: null,
    open: null,
    high: null,
    low: null,
    prev_close: null,
    volume: null,
    amount: null,
    turnover: partial.turnover ?? null,
    trade_time: '',
    ok: false,
    source: '',
  }
}

describe('pulseHomeLogic', () => {
  it('localIsoDate uses local calendar not UTC', () => {
    const d = new Date(2026, 6, 31, 8, 0, 0) // Jul 31 local
    expect(localIsoDate(d)).toBe('2026-07-31')
  })

  it('splitScreenDates picks today vs previous screen day', () => {
    expect(splitScreenDates(['2026-07-31', '2026-07-30', '2026-07-29'], '2026-07-31')).toEqual({
      todayHit: '2026-07-31',
      ydayHit: '2026-07-30',
    })
    expect(splitScreenDates(['2026-07-30', '2026-07-29'], '2026-07-31')).toEqual({
      todayHit: '',
      ydayHit: '2026-07-30',
    })
  })

  it('splitScreenDates uses last trading day on weekend', () => {
    expect(
      splitScreenDates(['2026-07-31', '2026-07-30'], '2026-08-01', '2026-07-31'),
    ).toEqual({
      todayHit: '2026-07-31',
      ydayHit: '2026-07-30',
    })
  })

  it('rankBoardRows keeps turnover order and resorts gain/loss by pct', () => {
    const rows = [
      row({ code: '1', pct: 1, turnover: 0.1 }),
      row({ code: '2', pct: 5, turnover: 0.05 }),
      row({ code: '3', pct: -2, turnover: 0.2 }),
    ]
    expect(rankBoardRows(rows, 'turnover').map((r) => r.code)).toEqual(['1', '2', '3'])
    expect(rankBoardRows(rows, 'gain').map((r) => r.code)).toEqual(['2', '1', '3'])
    expect(rankBoardRows(rows, 'loss').map((r) => r.code)).toEqual(['3', '1', '2'])
  })

  it('effectivePct prefers live pct over local', () => {
    expect(effectivePct(row({ code: '1', pct: 1.2, local_pct: 9 }))).toBe(1.2)
    expect(effectivePct(row({ code: '1', local_pct: 3.3 }))).toBe(3.3)
  })

  it('changeFromEntry and horizonReturn read real prices only', () => {
    expect(changeFromEntry(10, 11)).toBeCloseTo(10)
    expect(changeFromEntry(null, 11)).toBeNull()
    expect(horizonReturn({ t1: 1.5, t3: null }, 1)).toBe(1.5)
    expect(horizonReturn({ t1: 1.5, t3: null }, 3)).toBeNull()
  })

  it('dedupeTrackRowsByDayCode keeps one row per day+code preferring current strategy', () => {
    const rows = [
      { code: '002123', date: '2026-07-31', strategy: 'qianlong-close', score: 90 },
      { code: '002123', date: '2026-07-31', strategy: 'qianlong-close-v3', score: 80 },
      { code: '002123', date: '2026-07-30', strategy: 'qianlong-close-v3', score: 70 },
      { code: '301234', date: '2026-07-31', strategy: 'lugw-sanwai-v2', score: 50 },
      { code: '301234', date: '2026-07-31', strategy: 'lugw-sanwai', score: 60 },
    ]
    const out = dedupeTrackRowsByDayCode(rows)
    expect(out).toHaveLength(3)
    expect(out.find((r) => r.code === '002123' && r.date === '2026-07-31')?.strategy).toBe(
      'qianlong-close-v3',
    )
    expect(out.find((r) => r.code === '301234')?.strategy).toBe('lugw-sanwai')
  })
})

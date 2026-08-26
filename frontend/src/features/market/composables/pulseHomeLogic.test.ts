import { describe, expect, it } from 'vitest'

import type { BoardRow } from '@/shared/types/quant'

import {
  boardRowsToSpotMap,
  changeFromEntry,
  dedupeTrackRowsByDayCode,
  effectivePct,
  excludeTodayFromTrack,
  horizonReturn,
  localIsoDate,
  rankBoardRows,
  rankSectorRows,
  screenSessionDay,
  splitScreenDates,
  swingFromLowHigh,
  trackAsOfDate,
} from './pulseHomeLogic'

function row(partial: Partial<BoardRow> & { code: string }): BoardRow {
  return {
    code: partial.code,
    name: partial.name ?? partial.code,
    market: '',
    board: '',
    industry: partial.industry ?? '',
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
    amount: partial.amount ?? null,
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

  it('screenSessionDay falls back to coverage day before open', () => {
    expect(
      screenSessionDay({
        calendarToday: '2026-08-10',
        lastTradingDay: '2026-08-10',
        coverageLastDate: '2026-08-07',
        liveReason: 'before_open',
      }),
    ).toBe('2026-08-07')
    expect(
      screenSessionDay({
        calendarToday: '2026-08-10',
        lastTradingDay: '2026-08-10',
        coverageLastDate: '2026-08-07',
        liveReason: 'live_window',
      }),
    ).toBe('2026-08-10')
  })

  it('rankBoardRows keeps turnover order and resorts gain by pct', () => {
    const rows = [
      row({ code: '1', pct: 1, turnover: 0.1, industry: '半导体' }),
      row({ code: '2', pct: 5, turnover: 0.05, industry: '电力设备' }),
      row({ code: '3', pct: -2, turnover: 0.2, industry: '半导体' }),
      row({ code: '4', pct: 3, turnover: 0.08, industry: '电力设备' }),
    ]
    expect(rankBoardRows(rows, 'turnover').map((r) => r.code)).toEqual([
      '1',
      '2',
      '3',
      '4',
    ])
    expect(rankBoardRows(rows, 'gain').map((r) => r.code)).toEqual(['2', '4', '1', '3'])
    expect(rankBoardRows(rows, 'sector')).toEqual([])
  })

  it('rankSectorRows aggregates industry pct by amount weight', () => {
    const rows = [
      row({ code: '1', pct: 2, amount: 100, industry: '半导体' }),
      row({ code: '2', pct: 8, amount: 100, industry: '半导体' }),
      row({ code: '3', pct: 1, amount: 50, industry: '电力设备' }),
    ]
    expect(rankSectorRows(rows)).toEqual([
      { name: '半导体', pct: 5, count: 2 },
      { name: '电力设备', pct: 1, count: 1 },
    ])
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

  it('swingFromLowHigh computes low-to-high pct', () => {
    expect(swingFromLowHigh(10, 12)).toBeCloseTo(20)
    expect(swingFromLowHigh(10, 9)).toBeNull()
    expect(swingFromLowHigh(null, 12)).toBeNull()
  })

  it('trackAsOfDate anchors on last closed day while trading', () => {
    expect(trackAsOfDate('2026-08-05', '2026-08-04', true)).toBe('2026-08-04')
    expect(trackAsOfDate('2026-08-05', '2026-08-04', false)).toBe('2026-08-04')
    expect(trackAsOfDate('2026-08-05', '', false)).toBe('2026-08-05')
  })

  it('excludeTodayFromTrack drops rows dated calendar today', () => {
    const rows = [
      { date: '2026-08-05', code: '1' },
      { date: '2026-08-04', code: '2' },
    ]
    expect(excludeTodayFromTrack(rows, '2026-08-05').map((r) => r.code)).toEqual(['2'])
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

  // 14:50 两档已连代码删除；旧库可能还有历史行，要让位给现行战法。
  it('dedupeTrackRowsByDayCode outranks deleted 14:50 history rows', () => {
    const rows = [
      { code: '600001', date: '2026-08-17', strategy: 'sanyuan-tail-1450', score: 90 },
      { code: '600001', date: '2026-08-17', strategy: 'sanyuan-tail-v1', score: 80 },
      { code: '600002', date: '2026-08-17', strategy: 'yangshi-tail-1450', score: 70 },
      { code: '600002', date: '2026-08-17', strategy: 'yangshi-tail-v1', score: 60 },
    ]
    const out = dedupeTrackRowsByDayCode(rows)
    expect(out).toHaveLength(2)
    expect(out.find((r) => r.code === '600001')?.strategy).toBe('sanyuan-tail-v1')
    expect(out.find((r) => r.code === '600002')?.strategy).toBe('yangshi-tail-v1')
  })

  it('indexes board rows by code for spot reuse', () => {
    const map = boardRowsToSpotMap([row({ code: '600519' }), row({ code: '000001' })])
    expect(map.size).toBe(2)
    expect(map.get('600519')?.code).toBe('600519')
  })
})

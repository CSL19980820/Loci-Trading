import { describe, expect, it } from 'vitest'

import {
  ASSISTANT_KLINE_MIN_VISIBLE,
  candidateDecisions,
  decimal,
  parseCodePayload,
  parseEchartsOption,
  parseEquityPayload,
  parseKlineBars,
  parseSources,
  parseTablePayload,
  percent,
} from './assistantArtifacts'

describe('assistantArtifacts', () => {
  it('normalizes candidate evidence without inventing missing metrics', () => {
    const [candidate] = candidateDecisions({
      candidates: [{
        code: '600000', name: '浦发银行', decision: '精选', score: 91, reason: '量价配合',
        occurred_on: '2026-08-01', timing: '尾盘确认',
        evidence: { invalidation: '跌破 MA20', close: 12, pct_chg: 1.25, ma5: 11.4, ma20: 10, volume_ratio: 1.8 },
      }],
    })

    expect(candidate).toMatchObject({
      code: '600000', name: '浦发银行', decision: '精选', reason: '量价配合', timing: '尾盘确认',
      invalidation: '跌破 MA20', pctChange: 1.25, volumeRatio: 1.8,
    })
    expect(candidate?.ma5Deviation).toBeCloseTo(5.263, 2)
    expect(candidate?.ma20Deviation).toBe(20)
  })

  it('keeps unavailable numbers visibly unavailable', () => {
    const [candidate] = candidateDecisions({ candidates: [{ code: '600000', decision: '观察' }] })

    expect(candidate).toMatchObject({ code: '600000', name: '未命名候选', ma5Deviation: undefined, volumeRatio: undefined })
    expect(percent(undefined)).toBe('—')
    expect(decimal(undefined)).toBe('—')
  })

  it('parses object and array kline bars without inventing prices', () => {
    const bars = parseKlineBars({
      bars: [
        { trade_date: '2026-08-01', open: 10, high: 11, low: 9, close: 10.5, volume: 100 },
        ['2026-08-04', 10, 12, 9.5, 11, 200],
        [10, 11, 12, 9],
      ],
    })
    expect(bars).toHaveLength(3)
    expect(bars[0]).toMatchObject({ trade_date: '2026-08-01', open: 10, close: 10.5 })
    expect(bars[1]).toMatchObject({ trade_date: '2026-08-04', open: 10, high: 12, low: 9.5, close: 11 })
    expect(bars[2]).toMatchObject({ open: 10, close: 11, high: 12, low: 9 })
    expect(ASSISTANT_KLINE_MIN_VISIBLE).toBe(20)
  })

  it('paginates tables over 50 rows and rejects non-whitelisted echarts series', () => {
    const rows = Array.from({ length: 51 }, (_, i) => ({ code: String(i), name: `N${i}` }))
    const table = parseTablePayload({ columns: [{ prop: 'code', label: '代码' }, { prop: 'name', label: '名称' }], rows })
    expect(table.paginate).toBe(true)
    expect(table.rows).toHaveLength(51)

    expect(parseEchartsOption({
      option: { series: [{ type: 'line', data: [1, 2] }] },
    })).toMatchObject({ series: [{ type: 'line' }] })
    expect(parseEchartsOption({
      option: { series: [{ type: 'custom', data: [1] }] },
    })).toBeNull()
  })

  it('parses equity, sources, and code payloads from tool truth', () => {
    expect(parseEquityPayload({
      points: [{ date: '2026-01-01', equity: 100 }, { date: '2026-01-02', equity: 101 }],
    })).toEqual({ dates: ['2026-01-01', '2026-01-02'], values: [100, 101] })

    expect(parseSources({ sources: [{ label: 'market.db', code: '600000', date: '2026-08-01' }] })).toEqual([
      { label: 'market.db', detail: undefined, code: '600000', date: '2026-08-01', hash: undefined },
    ])

    expect(parseCodePayload({ language: 'json', text: '{"ok":true}' })).toEqual({
      language: 'json', text: '{"ok":true}',
    })
  })
})

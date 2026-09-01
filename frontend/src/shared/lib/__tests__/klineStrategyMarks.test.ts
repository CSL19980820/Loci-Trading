import { describe, expect, it } from 'vitest'
import { buildStrategySignalMarks, type StrategySignalMark } from '@/shared/lib/klineStrategyMarks'
import type { OhlcBar } from '@/shared/lib/indicators'

describe('klineStrategyMarks', () => {
  const bars: OhlcBar[] = [
    { trade_date: '2026-08-25', open: 10, high: 10.5, low: 9.8, close: 10.2, volume: 1000 },
    { trade_date: '2026-08-26', open: 10.2, high: 11.0, low: 10.1, close: 10.8, volume: 1500 },
    { trade_date: '2026-08-27', open: 10.8, high: 11.5, low: 10.6, close: 11.2, volume: 1800 },
  ]
  const dates = ['2026-08-25', '2026-08-26', '2026-08-27']

  it('没有信号时返回空数组', () => {
    const marks = buildStrategySignalMarks(bars, dates, [])
    expect(marks).toEqual([])
  })

  it('单日单策略正确生成向上箭头与标注', () => {
    const signals: StrategySignalMark[] = [
      {
        date: '2026-08-26',
        strategyName: '潜龙低吸',
        strategySlug: 'qianlong_dip',
        reason: '突破20日均线',
      },
    ]
    const marks = buildStrategySignalMarks(bars, dates, signals)
    expect(marks.length).toBe(1)
    expect(marks[0].coord).toEqual(['2026-08-26', 10.1])
    expect(marks[0].value).toBe('潜龙低吸')
    expect(marks[0].symbol).toContain('path://')
  })

  it('单日多策略统一合并标注并在多日分别展示', () => {
    const signals: StrategySignalMark[] = [
      {
        date: '2026-08-25',
        strategyName: '放量突破',
        strategySlug: 'breakout',
      },
      {
        date: '2026-08-27',
        strategyName: '阳狮之尾',
        strategySlug: 'yangshi_tail',
      },
      {
        date: '2026-08-27',
        strategyName: '潜龙二波',
        strategySlug: 'dragon_wave',
      },
    ]
    const marks = buildStrategySignalMarks(bars, dates, signals)
    expect(marks.length).toBe(2)
    // 08-25 标出单策略
    const mark25 = marks.find((m) => (m.coord as [string, number])[0] === '2026-08-25')
    expect(mark25?.value).toBe('放量突破')

    // 08-27 标出合并多策略
    const mark27 = marks.find((m) => (m.coord as [string, number])[0] === '2026-08-27')
    expect(mark27?.value).toBe('阳狮之尾 + 潜龙二波')
    expect(mark27?.coord).toEqual(['2026-08-27', 10.6])
  })
})

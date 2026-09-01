import { describe, expect, it } from 'vitest'

import {
  computeSessionRuler,
  formatGap,
  minutesUntilNextOpen,
  pctOfMinute,
  RULER_END_MIN,
  RULER_SEGMENTS,
  RULER_START_MIN,
  segmentFill,
} from './sessionRuler'

/** 2026-08-27 周四（交易日）；08-28 周五；08-29 周六；08-31 周一。 */
function at(hhmm: string, day = '2026-08-27'): Date {
  const [h, m] = hhmm.split(':').map(Number)
  const [y, mo, d] = day.split('-').map(Number)
  return new Date(y, mo - 1, d, h, m, 0, 0)
}

describe('computeSessionRuler 边界', () => {
  it('09:14 还在开盘前，不画刻针', () => {
    const state = computeSessionRuler({ now: at('09:14'), isTradingDay: true })
    expect(state.phase).toBe('pre')
    expect(state.markerPct).toBeNull()
    expect(state.progress).toBe(0)
    expect(state.dimmed).toBe(false)
    expect(state.statusText).toBe('开盘前 · 距集合竞价 1 分')
  })

  it('09:15 整点进入集合竞价，刻针贴左端', () => {
    const state = computeSessionRuler({ now: at('09:15'), isTradingDay: true })
    expect(state.phase).toBe('auction-open')
    expect(state.markerPct).toBe(0)
  })

  it('09:20 集合竞价中，报距开盘', () => {
    const state = computeSessionRuler({ now: at('09:20'), isTradingDay: true })
    expect(state.phase).toBe('auction-open')
    expect(state.statusText).toBe('集合竞价 · 距开盘 10 分')
  })

  it('09:25–09:30 是断口，算待开盘', () => {
    expect(computeSessionRuler({ now: at('09:25'), isTradingDay: true }).phase).toBe('pre-open')
    expect(computeSessionRuler({ now: at('09:29'), isTradingDay: true }).phase).toBe('pre-open')
  })

  it('09:30 开盘；10:48 报「早盘 · 距午休 42 分」', () => {
    expect(computeSessionRuler({ now: at('09:30'), isTradingDay: true }).phase).toBe('morning')
    const state = computeSessionRuler({ now: at('10:48'), isTradingDay: true })
    expect(state.statusText).toBe('早盘 · 距午休 42 分')
  })

  it('11:30 整点已进午休；11:31 仍是午休', () => {
    expect(computeSessionRuler({ now: at('11:30'), isTradingDay: true }).phase).toBe('lunch')
    const state = computeSessionRuler({ now: at('11:31'), isTradingDay: true })
    expect(state.phase).toBe('lunch')
    expect(state.statusText).toBe('午休 · 距午盘 1 小时 29 分')
  })

  it('12:59 午休最后一分钟；13:00 开午盘', () => {
    expect(computeSessionRuler({ now: at('12:59'), isTradingDay: true }).phase).toBe('lunch')
    expect(computeSessionRuler({ now: at('13:00'), isTradingDay: true }).phase).toBe('afternoon')
  })

  it('14:56 仍是午盘；14:57 与 14:58 是收盘竞价', () => {
    expect(computeSessionRuler({ now: at('14:56'), isTradingDay: true }).phase).toBe('afternoon')
    expect(computeSessionRuler({ now: at('14:57'), isTradingDay: true }).phase).toBe(
      'auction-close',
    )
    const state = computeSessionRuler({ now: at('14:58'), isTradingDay: true })
    expect(state.phase).toBe('auction-close')
    expect(state.statusText).toBe('收盘竞价 · 距收盘 2 分')
  })

  it('15:00 与 15:01 已收盘：整轨降级、无刻针', () => {
    for (const clock of ['15:00', '15:01']) {
      const state = computeSessionRuler({ now: at(clock), isTradingDay: true })
      expect(state.phase).toBe('closed')
      expect(state.markerPct).toBeNull()
      expect(state.dimmed).toBe(true)
      expect(state.statusText.startsWith('已收盘 · 距下次开盘 ')).toBe(true)
    }
  })

  it('周六休市：不画针、整轨降级、报距周一开盘', () => {
    const state = computeSessionRuler({ now: at('10:00', '2026-08-29') })
    expect(state.phase).toBe('holiday')
    expect(state.isTradingDay).toBe(false)
    expect(state.dimmed).toBe(true)
    expect(state.markerPct).toBeNull()
    // 周六 10:00 → 周一 09:30 = 47.5 小时
    expect(state.statusText).toBe('休市 · 距下次开盘 1 天 23 小时')
  })

  it('后端说今天不是交易日就以后端为准（节假日日历只在后端）', () => {
    const state = computeSessionRuler({ now: at('10:00'), isTradingDay: false })
    expect(state.phase).toBe('holiday')
    expect(state.statusText.startsWith('休市 · 距下次开盘 ')).toBe(true)
  })

  it('缺 isTradingDay 时按工作日兜底', () => {
    expect(computeSessionRuler({ now: at('10:00') }).phase).toBe('morning')
  })
})

describe('刻度换算', () => {
  it('左右端点夹在 0 与 100', () => {
    expect(pctOfMinute(RULER_START_MIN)).toBe(0)
    expect(pctOfMinute(RULER_END_MIN)).toBe(100)
    expect(pctOfMinute(RULER_START_MIN - 60)).toBe(0)
    expect(pctOfMinute(RULER_END_MIN + 60)).toBe(100)
  })

  it('午休段是断口而不是可交易段', () => {
    expect(RULER_SEGMENTS.find((s) => s.id === 'lunch')?.kind).toBe('break')
    expect(RULER_SEGMENTS.find((s) => s.id === 'pre-open')?.kind).toBe('break')
  })

  it('段内填充按时间比例', () => {
    const morning = RULER_SEGMENTS.find((s) => s.id === 'morning')!
    expect(segmentFill(morning, null)).toBe(0)
    expect(segmentFill(morning, 9 * 60)).toBe(0)
    expect(segmentFill(morning, 10 * 60 + 30)).toBeCloseTo(0.5, 5)
    expect(segmentFill(morning, 14 * 60)).toBe(1)
  })
})

describe('时长文案', () => {
  it('分 / 小时 / 天三档', () => {
    expect(formatGap(0.2)).toBe('不到 1 分')
    expect(formatGap(42)).toBe('42 分')
    expect(formatGap(60)).toBe('1 小时')
    expect(formatGap(150)).toBe('2 小时 30 分')
    expect(formatGap(60 * 24 + 90)).toBe('1 天 1 小时')
  })
})

describe('下次开盘', () => {
  it('交易日开盘前取当天 09:30', () => {
    expect(minutesUntilNextOpen(at('08:30'), true)).toBe(60)
  })

  it('周五收盘后跳过周末', () => {
    const minutes = minutesUntilNextOpen(at('15:30', '2026-08-28'), true)
    // → 2026-08-31（周一）09:30
    expect(minutes).toBe(3 * 24 * 60 - 6 * 60)
  })
})

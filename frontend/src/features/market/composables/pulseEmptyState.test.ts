import { describe, expect, it } from 'vitest'

import {
  formatRunClock,
  todayEmptyShort,
  todayEmptyText,
  todayNoteText,
  trackEmptyShort,
  trackEmptyText,
  type PulseEmptyInput,
} from './pulseEmptyState'

function input(patch: Partial<PulseEmptyInput> = {}): PulseEmptyInput {
  return {
    screenHistoryTotal: 12,
    hasEnabledScreenJob: true,
    nextScreenRunAt: '2026-08-27T15:30:00',
    ...patch,
  }
}

describe('formatRunClock', () => {
  it('无值返回空串', () => {
    expect(formatRunClock(null)).toBe('')
    expect(formatRunClock('  ')).toBe('')
  })

  it('可解析时间压成 MM-DD HH:mm', () => {
    expect(formatRunClock('2026-08-28T09:05:00')).toBe('08-28 09:05')
    expect(formatRunClock('2026-08-28 09:05:00')).toBe('08-28 09:05')
  })

  it('解析不了就原样返回', () => {
    expect(formatRunClock('每天收盘后')).toBe('每天收盘后')
  })
})

describe('trackEmptyText', () => {
  it('历史未知：承认读不到，不臆测排程', () => {
    const text = trackEmptyText(input({ screenHistoryTotal: null }))
    expect(text).toContain('没读到')
    expect(text).toContain('【选股】')
    expect(text).not.toContain('15:30')
    expect(text).not.toContain('定时')
  })

  it('新用户（0 条历史）：只引导立刻手动跑，不提定时/15:30', () => {
    const text = trackEmptyText(input({ screenHistoryTotal: 0, hasEnabledScreenJob: true }))
    expect(text).toContain('还没有任何选股记录')
    expect(text).toContain('【选股】')
    expect(text).not.toContain('定时')
    expect(text).not.toContain('15:30')
  })

  it('有历史 + 已启用任务 + 有下次触发：报真实时间', () => {
    const text = trackEmptyText(input({ nextScreenRunAt: '2026-08-28T15:31:00' }))
    expect(text).toContain('下次自动选股：08-28 15:31')
  })

  it('有历史 + 已启用任务 + 无下次触发：点名调度器可能没跑', () => {
    const text = trackEmptyText(input({ nextScreenRunAt: null }))
    expect(text).toContain('没算出下次触发时间')
    expect(text).toContain('任务中心')
  })

  it('有历史 + 无已启用任务：不提定时时间，引导手动或新建', () => {
    const text = trackEmptyText(
      input({ hasEnabledScreenJob: false, nextScreenRunAt: '2026-08-28T15:30:00' }),
    )
    expect(text).toContain('没有已启用的定时选股任务')
    expect(text).not.toContain('08-28')
  })
})

describe('todayEmptyText', () => {
  it('历史未知：承认读不到', () => {
    expect(todayEmptyText(input({ screenHistoryTotal: null }))).toContain('没读到')
  })

  it('新用户：不提 15:30 / 定时任务', () => {
    const text = todayEmptyText(input({ screenHistoryTotal: 0 }))
    expect(text).toContain('立即跑一次')
    expect(text).not.toContain('15:30')
    expect(text).not.toContain('定时')
  })

  it('有历史 + 已启用任务：给后端算出的下次触发时间', () => {
    const text = todayEmptyText(input({ nextScreenRunAt: '2026-09-01T15:35:00' }))
    expect(text).toContain('今日还没有选股记录')
    expect(text).toContain('09-01 15:35')
  })

  it('有历史 + 已启用任务 + 无下次触发', () => {
    expect(todayEmptyText(input({ nextScreenRunAt: null }))).toContain('调度器可能没跑')
  })

  it('有历史 + 无任务', () => {
    const text = todayEmptyText(input({ hasEnabledScreenJob: false }))
    expect(text).toContain('去任务中心新建')
    expect(text).not.toContain('下次自动选股')
  })
})

describe('todayNoteText', () => {
  it('新用户不提定时', () => {
    expect(todayNoteText(input({ screenHistoryTotal: 0 }))).toBe('今日尚未落库 · 到【选股】手动跑一次')
  })

  it('有任务有时间就报时间', () => {
    expect(todayNoteText(input({ nextScreenRunAt: '2026-08-28T15:30:00' }))).toBe(
      '今日尚未落库 · 下次自动选股 08-28 15:30',
    )
  })

  it('无任务只说没任务', () => {
    expect(todayNoteText(input({ hasEnabledScreenJob: false }))).toBe('今日尚未落库 · 无定时选股任务')
  })
})

describe('空态短句', () => {
  it('三档与长文本同口径，且都不超过 14 字', () => {
    const cases: PulseEmptyInput[] = [
      input({ screenHistoryTotal: null }),
      input({ screenHistoryTotal: 0 }),
      input(),
    ]
    const shorts = [
      ...cases.map((c) => trackEmptyShort(c)),
      ...cases.map((c) => todayEmptyShort(c)),
    ]
    for (const text of shorts) expect(text.length).toBeLessThanOrEqual(14)
    expect(trackEmptyShort(cases[0])).toBe('选股历史没读到')
    expect(trackEmptyShort(cases[1])).toBe('还没跑过选股')
    expect(trackEmptyShort(cases[2])).toBe('近 5 日无精选入库')
    expect(todayEmptyShort(cases[2])).toBe('今日还没有选股')
  })

  it('短句里不出现定时/时间，那些只在 tooltip 长文本里', () => {
    for (const text of [trackEmptyShort(input()), todayEmptyShort(input())]) {
      expect(text).not.toContain('定时')
      expect(text).not.toContain('15:30')
    }
  })
})

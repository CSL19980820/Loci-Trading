import { describe, expect, it } from 'vitest'

import {
  TENANT_CRON_FLOOR_SECONDS,
  composeTradingCron,
  cronIntervalSeconds,
  defaultTradingSchedule,
  describeCronRuns,
  formatCronRun,
  nearestTradingInterval,
  normalizeCronWeekdays,
  previewCron,
} from './cronPreview'

/** 2026-08-27 是周四 10:07（本地时区）。所有断言都从这一刻起算。 */
const THURSDAY = new Date(2026, 7, 27, 10, 7, 30)

describe('previewCron 支持的写法', () => {
  it('*/5 9-14 * * 1-5：盘中每 5 分钟，只落在工作日 9–14 点', () => {
    const preview = previewCron('*/5 9-14 * * 1-5', { count: 3, from: THURSDAY })

    expect(preview).not.toBeNull()
    // 后端 normalize_cron_weekdays 把 1-5 改写成 mon-fri，前端必须同口径
    expect(preview!.normalized).toBe('*/5 9-14 * * mon-fri')
    expect(preview!.runs.map(formatCronRun)).toEqual([
      '2026-08-27 10:10',
      '2026-08-27 10:15',
      '2026-08-27 10:20',
    ])
    expect(preview!.intervalSeconds).toBe(300)
  })

  it('*/5 9-14 * * 1-5 跨过 14:55 后落到次日 09:00', () => {
    const runs = describeCronRuns('*/5 9-14 * * 1-5', {
      count: 2,
      from: new Date(2026, 7, 27, 14, 56),
    })

    expect(runs).toEqual(['2026-08-28 09:00', '2026-08-28 09:05'])
  })

  it('1-5 是周一至周五，不是 APScheduler 裸编号的周二至周六', () => {
    // 周五 23:00 起算，下一次必须是周一（跳过周六周日）
    const runs = describeCronRuns('*/5 9-14 * * 1-5', {
      count: 1,
      from: new Date(2026, 7, 28, 23, 0),
    })

    expect(runs).toEqual(['2026-08-31 09:00'])
  })

  it('30 15 * * *：每天 15:30', () => {
    const preview = previewCron('30 15 * * *', { count: 3, from: THURSDAY })

    expect(preview!.runs.map(formatCronRun)).toEqual([
      '2026-08-27 15:30',
      '2026-08-28 15:30',
      '2026-08-29 15:30',
    ])
    expect(preview!.intervalSeconds).toBe(86_400)
  })

  it('30 15 * * mon-fri：命名星期，周末不跑', () => {
    const runs = describeCronRuns('30 15 * * mon-fri', {
      count: 2,
      from: new Date(2026, 7, 28, 16, 0),
    })

    expect(runs).toEqual(['2026-08-31 15:30', '2026-09-01 15:30'])
  })
  it('逗号列表与 a-b 混写', () => {
    const runs = describeCronRuns('0,30 9-10 * * *', { count: 4, from: THURSDAY })

    // 10:07 起算：当天 09:30 已过，先给 10:30，再翻到次日
    expect(runs).toEqual([
      '2026-08-27 10:30',
      '2026-08-28 09:00',
      '2026-08-28 09:30',
      '2026-08-28 10:00',
    ])
  })

  it('多行 / 分号复合表达式：14:50 与 15:30 两个时点', () => {
    const multi = '50 14 * * mon-fri\n30 15 * * mon-fri'
    const runs = describeCronRuns(multi, { count: 4, from: THURSDAY })

    // 10:07 起算：当天先出 14:50，再出 15:30，次日再依次循环
    expect(runs).toEqual([
      '2026-08-27 14:50',
      '2026-08-27 15:30',
      '2026-08-28 14:50',
      '2026-08-28 15:30',
    ])
  })

  it('分号分隔复合表达式：14:50 与 15:30', () => {
    const multi = '50 14 * * mon-fri; 30 15 * * mon-fri'
    const runs = describeCronRuns(multi, { count: 3, from: THURSDAY })

    expect(runs).toEqual([
      '2026-08-27 14:50',
      '2026-08-27 15:30',
      '2026-08-28 14:50',
    ])
  })
  it('日 + 月固定：0 8 1 1 * 落到下一个元旦', () => {
    const runs = describeCronRuns('0 8 1 1 *', { count: 1, from: THURSDAY })

    expect(runs).toEqual(['2027-01-01 08:00'])
  })

  it('触发点严格晚于 from，不把「此刻」算成下一次', () => {
    const runs = describeCronRuns('*/5 * * * *', { count: 1, from: new Date(2026, 7, 27, 10, 10) })

    expect(runs).toEqual(['2026-08-27 10:15'])
  })
})

describe('previewCron 不支持的写法一律 null', () => {
  it.each([
    ['空表达式', ''],
    ['只有空白', '   '],
    ['四段', '*/5 9-14 * *'],
    ['六段（带秒）', '0 */5 9-14 * * 1-5'],
    ['Jenkins 风格 H', 'H/5 * * * *'],
    ['@ 快捷写法', '@daily'],
    ['第几个星期几 #', '0 9 * * mon#2'],
    ['最后一天 L', '0 9 L * *'],
    ['问号 ?', '0 9 ? * mon'],
    ['字段越界', '99 9 * * *'],
    ['倒序范围', '0 14-9 * * *'],
    ['步长为 0', '*/0 * * * *'],
    ['空列表项', '0,,30 9 * * *'],
    ['不认识的星期名', '0 9 * * funday'],
    ['永不成立的日月组合', '0 9 30 2 *'],
  ])('%s → null', (_label, expression) => {
    expect(previewCron(expression, { from: THURSDAY })).toBeNull()
    expect(describeCronRuns(expression, { from: THURSDAY })).toBeNull()
    expect(cronIntervalSeconds(expression, THURSDAY)).toBeNull()
  })
})

describe('cronIntervalSeconds', () => {
  it('* * * * * 是 60 秒，够触发「快于 5 分钟」的就地提示', () => {
    expect(cronIntervalSeconds('* * * * *', THURSDAY)).toBe(60)
  })

  it('*/5 是 300 秒，正好卡在下限上不该被判违规', () => {
    expect(cronIntervalSeconds('*/5 * * * *', THURSDAY)).toBe(300)
  })

  it('*/2 是 120 秒', () => {
    expect(cronIntervalSeconds('*/2 * * * *', THURSDAY)).toBe(120)
  })
})

describe('normalizeCronWeekdays', () => {
  it('只改写 1-5 / 1,2,3,4,5 两种历史写法', () => {
    expect(normalizeCronWeekdays('30 15 * * 1-5')).toBe('30 15 * * mon-fri')
    expect(normalizeCronWeekdays('30 15 * * 1,2,3,4,5')).toBe('30 15 * * mon-fri')
  })

  it('已按 APScheduler 编号写的 0-4 不动，避免误伤', () => {
    expect(normalizeCronWeekdays('30 15 * * 0-4')).toBe('30 15 * * 0-4')
    expect(normalizeCronWeekdays('30 15 * * mon-fri')).toBe('30 15 * * mon-fri')
    expect(normalizeCronWeekdays('@daily')).toBe('@daily')
  })
})

describe('composeTradingCron 与后端 compose_trading_cron 对齐', () => {
  it('once → 分 时 * * mon-fri（不写 1-5，APScheduler 的 1-5 是周二到周六）', () => {
    const cron = composeTradingCron({ ...defaultTradingSchedule(), mode: 'once', run_hour: 15, run_minute: 30 })

    expect(cron).toBe('30 15 * * mon-fri')
    expect(describeCronRuns(cron, { count: 1, from: THURSDAY })).toEqual(['2026-08-27 15:30'])
  })

  it('interval → 步长 + 小时窗', () => {
    const cron = composeTradingCron({
      ...defaultTradingSchedule(),
      mode: 'interval',
      interval_minutes: 10,
      window_start_hour: 9,
      window_end_hour: 14,
    })

    expect(cron).toBe('*/10 9-14 * * mon-fri')
    expect(cronIntervalSeconds(cron, THURSDAY)).toBe(600)
  })

  it('off → 空串（= 仅手动）', () => {
    expect(composeTradingCron({ ...defaultTradingSchedule(), mode: 'off' })).toBe('')
  })

  it('档位外的间隔靠到最近的合法档，别让后端 422', () => {
    expect(nearestTradingInterval(7)).toBe(5)
    expect(nearestTradingInterval(12)).toBe(10)
    expect(nearestTradingInterval(999)).toBe(60)
  })

  it('5 分钟档正好等于租户下限，不该被就地提示判违规', () => {
    const cron = composeTradingCron({ ...defaultTradingSchedule(), mode: 'interval', interval_minutes: 5 })

    expect(cronIntervalSeconds(cron, THURSDAY)).toBe(TENANT_CRON_FLOOR_SECONDS)
  })
})
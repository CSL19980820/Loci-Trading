import { describe, expect, it } from 'vitest'

import {
  previewSlots,
  readFields,
  screenDefaults,
  watchDefaults,
  writeFields,
} from './skillSchedule'

describe('skillSchedule', () => {
  it('once 模式只预览一个时点', () => {
    const slots = previewSlots({ ...screenDefaults(), mode: 'once', run_hour: 15, run_minute: 40 })
    expect(slots).toHaveLength(1)
    expect(slots[0]).toMatch(/ 15:40$/)
  })

  it('interval 模式预览含开头槽与当天末档 14:50', () => {
    const slots = previewSlots({ ...watchDefaults(), interval_minutes: 10 })
    expect(slots).toHaveLength(5)
    expect(slots[0]).toMatch(/ 09:30$/)
    expect(slots[1]).toMatch(/ 09:40$/)
    expect(slots[slots.length - 1]).toMatch(/ 14:50$/)
  })

  it('interval=0 不会死循环', () => {
    expect(previewSlots({ ...watchDefaults(), interval_minutes: 0 })).toHaveLength(5)
  })

  it('readFields 按前缀取值，缺字段回落默认', () => {
    const fields = readFields(
      { screen_run_hour: 9, screen_run_minute: 5 },
      'once',
      screenDefaults(),
      'screen_',
    )
    expect(fields.mode).toBe('once')
    expect(fields.run_hour).toBe(9)
    expect(fields.run_minute).toBe(5)
    expect(fields.interval_minutes).toBe(screenDefaults().interval_minutes)
  })

  it('readFields 遇到 off 保留档位默认 mode', () => {
    expect(readFields({}, 'off', watchDefaults(), 'watch_').mode).toBe('interval')
    expect(readFields({}, null, screenDefaults(), 'screen_').mode).toBe('once')
  })

  it('writeFields 关闭时写出 off，字段仍保留供再次开启', () => {
    const payload = writeFields(watchDefaults(), false, 'watch_')
    expect(payload.watch_schedule_mode).toBe('off')
    expect(payload.watch_interval_minutes).toBe(10)
  })

  it('writeFields 开启时写出当前 mode', () => {
    const payload = writeFields({ ...screenDefaults(), mode: 'interval' }, true, 'screen_')
    expect(payload.screen_schedule_mode).toBe('interval')
    expect(payload.screen_window_end_hour).toBe(14)
  })
})

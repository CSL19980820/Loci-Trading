import { describe, expect, it } from 'vitest'
import { formatDateTime } from './dateTime'

describe('北京时间秒级格式', () => {
  it.each([
    ['2026-09-18T06:28:09.123456+00:00', '2026-09-18 14:28:09'],
    ['2026-09-18T06:28:09Z', '2026-09-18 14:28:09'],
    ['2026-09-18T14:28:09+08:00', '2026-09-18 14:28:09'],
    ['2026-09-18 14:28:09', '2026-09-18 14:28:09'],
    ['2026-09-18T14:28:09', '2026-09-18 14:28:09'],
    ['2026-12-31T16:00:00Z', '2027-01-01 00:00:00'],
    ['', '—'], ['not-a-time', '—'], [null, '—'], [undefined, '—'],
  ])('formats %s without exposing ISO or browser-local timezone', (input, output) => {
    expect(formatDateTime(input)).toBe(output)
  })
})

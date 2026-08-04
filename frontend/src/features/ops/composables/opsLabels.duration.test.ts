import { describe, expect, it } from 'vitest'

import { formatRunDuration } from './opsLabels'

describe('formatRunDuration', () => {
  it('keeps ms below one second', () => {
    expect(formatRunDuration(0)).toBe('0ms')
    expect(formatRunDuration(500)).toBe('500ms')
    expect(formatRunDuration(999)).toBe('999ms')
  })

  it('drops ms once at or above one second', () => {
    expect(formatRunDuration(1000)).toBe('1s')
    expect(formatRunDuration(3125)).toBe('3s')
    expect(formatRunDuration(443719)).toBe('7min23s')
  })

  it('composes hours minutes seconds without zero parts', () => {
    expect(formatRunDuration(11 * 3600_000 + 2 * 60_000 + 3_000)).toBe('11h2min3s')
    expect(formatRunDuration(3600_000)).toBe('1h')
    expect(formatRunDuration(120_000)).toBe('2min')
  })
})

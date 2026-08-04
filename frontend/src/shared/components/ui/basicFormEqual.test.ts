import { describe, expect, it } from 'vitest'

import { formRecordsEqual, formValuesEqual } from './basicFormEqual'

describe('formValuesEqual', () => {
  it('treats equal daterange arrays as same despite new refs', () => {
    expect(formValuesEqual(['2026-07-01', '2026-07-29'], ['2026-07-01', '2026-07-29'])).toBe(true)
    expect(formValuesEqual(['2026-07-01', '2026-07-29'], ['2026-07-01', '2026-07-28'])).toBe(false)
    expect(formValuesEqual(null, null)).toBe(true)
    expect(formValuesEqual(null, ['2026-07-01', '2026-07-29'])).toBe(false)
  })

  it('compares Date by timestamp', () => {
    expect(formValuesEqual(new Date('2026-07-29T00:00:00'), new Date('2026-07-29T00:00:00'))).toBe(
      true,
    )
  })
})

describe('formRecordsEqual', () => {
  it('ignores object identity when field values match', () => {
    expect(
      formRecordsEqual(
        { keyword: '', dateRange: ['2026-07-01', '2026-07-29'] },
        { keyword: '', dateRange: ['2026-07-01', '2026-07-29'] },
      ),
    ).toBe(true)
    expect(
      formRecordsEqual(
        { keyword: 'a', dateRange: null },
        { keyword: 'a', dateRange: ['2026-07-01', '2026-07-29'] },
      ),
    ).toBe(false)
  })
})

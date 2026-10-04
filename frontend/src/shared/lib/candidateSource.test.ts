import { describe, expect, it } from 'vitest'
import { isHistoricalCandidate } from './candidateSource'

describe('candidate history classification matches the default list exclusions', () => {
  it.each([
    ['api:screen_backfill', '2026-09-29', true],
    ['API:SCREEN_BACKFILL', '2026-09-22', true],
    ['job:screen:history', '2026-09-22', true],
    ['api:screen', '2026-09-29', true],
    ['api:screen_today', '2026-09-29', true],
    ['api:screen', '2026-09-22', false],
    ['manual', '2026-09-29', false],
    ['ai_assistant', '2026-09-29', false],
    ['job:screen', '2026-09-29', false],
    ['manual:history-note', '2026-09-29', false],
    ['', '2026-09-29', false],
  ])('%s, written on %s => historical %s', (source, writtenOn, expected) => {
    const row = Object.freeze({ source, date: '2026-09-22', created_at: `${writtenOn}T15:30:00+08:00` })
    expect(isHistoricalCandidate(row)).toBe(expected)
    expect(row.source).toBe(source)
    expect(row.date).toBe('2026-09-22')
  })

  it('handles empty and incomplete records without throwing', () => {
    expect(isHistoricalCandidate(null)).toBe(false)
    expect(isHistoricalCandidate(undefined)).toBe(false)
    expect(isHistoricalCandidate({})).toBe(false)
    expect(isHistoricalCandidate({ source: 'api:screen', date: '2026-09-22' })).toBe(true)
  })
})

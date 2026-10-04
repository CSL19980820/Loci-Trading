import { describe, expect, it } from 'vitest'
import type { Candidate } from '@/shared/types/palace'
import { buildFootprintLanes } from './useStrategyFootprints'

const base: Candidate = {
  id: 'live', date: '2026-09-29', pool_id: 'fixture-yang@2026-09-29', code: '300616', name: '尚品宅配',
  score: 93.07, decision: '精选', timing: 'next_open', reason: '隔离测试', rule_version: 'fixture-yang',
  source: 'api:screen', created_at: '2026-09-29 15:30:00', evidence: {},
}

describe('historical picks in strategy footprints', () => {
  it.each(['api:screen_backfill', 'api:screen:history', 'api:screen'])('marks %s history without changing the selected date', source => {
    const history = { ...base, id: 'history', date: '2026-09-22', source }
    const lanes = buildFootprintLanes([base, history], null)
    expect(lanes).toHaveLength(1)
    expect(lanes[0]!.picks.map(pick => [pick.date, pick.backfill])).toEqual([
      ['2026-09-29', false], ['2026-09-22', true],
    ])
  })

  it('prefers the non-history pick when a same-day decision ties', () => {
    const history = { ...base, id: 'history', source: 'api:screen_backfill' }
    for (const rows of [[history, base], [base, history]]) {
      const picks = buildFootprintLanes(rows, null)[0]!.picks
      expect(picks).toHaveLength(1)
      expect(picks[0]).toMatchObject({ id: 'live', backfill: false })
    }
  })
})

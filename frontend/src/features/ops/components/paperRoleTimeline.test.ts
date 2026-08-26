import { describe, expect, it } from 'vitest'

import {
  buildRoleTimeline,
  latestRoleByCodeDate,
  roleRank,
  suggestTimelineCodes,
} from './paperRoleTimeline'

describe('paperRoleTimeline', () => {
  it('maps roles to discrete ranks', () => {
    expect(roleRank('leader')).toBe(4)
    expect(roleRank('failed')).toBe(0)
    expect(roleRank('unknown')).toBeNull()
  })

  it('keeps latest observation per code/day', () => {
    const map = latestRoleByCodeDate([
      {
        code: '600001',
        role: 'leader',
        trade_date: '2026-08-05',
        observed_at: '2026-08-05T10:00:00',
      },
      {
        code: '600001',
        role: 'weakened',
        trade_date: '2026-08-05',
        observed_at: '2026-08-05T15:00:00',
      },
    ])
    expect(map.get('600001|2026-08-05')?.role).toBe('weakened')
  })

  it('prefers position codes then dense history', () => {
    const history = [
      { code: '000001', name: 'A', trade_date: '2026-08-01', role: 'leader' },
      { code: '000001', name: 'A', trade_date: '2026-08-02', role: 'leader' },
      { code: '000001', name: 'A', trade_date: '2026-08-03', role: 'weakened' },
      { code: '600001', name: 'B', trade_date: '2026-08-03', role: 'leader' },
      { code: '600519', name: 'C', trade_date: '2026-08-03', role: 'secondary' },
    ]
    expect(suggestTimelineCodes(history, { preferCodes: ['600001'], limit: 2 })).toEqual([
      '600001',
      '000001',
    ])
  })

  it('builds step-aligned series with null gaps', () => {
    const model = buildRoleTimeline(
      [
        {
          code: '600001',
          name: '测试龙',
          trade_date: '2026-08-05',
          role: 'leader',
          observed_at: '2026-08-05T15:00:00',
        },
        {
          code: '600001',
          name: '测试龙',
          trade_date: '2026-08-07',
          role: 'weakened',
          observed_at: '2026-08-07T15:00:00',
        },
        {
          code: '000001',
          name: '旁观',
          trade_date: '2026-08-06',
          role: 'secondary',
        },
      ],
      { codes: ['600001'] },
    )
    expect(model.dates).toEqual(['2026-08-05', '2026-08-06', '2026-08-07'])
    expect(model.series).toHaveLength(1)
    expect(model.series[0].ranks).toEqual([4, null, 1])
    expect(model.series[0].roles).toEqual(['leader', null, 'weakened'])
  })
})

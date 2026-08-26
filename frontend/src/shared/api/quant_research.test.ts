import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createResearchBacktestRun,
  getResearchBacktestJob,
  importResearchMembershipSnapshots,
  importResearchPointInTimeFacts,
  listResearchMembershipSnapshots,
  listResearchPointInTimeFacts,
  publishResearchBacktestRun,
  rejectResearchBacktestRun,
  replayResearchBacktestRun,
  researchArtifactUrl,
  reviewResearchHypothesis,
  submitResearchBacktestJob,
  transitionResearchHypothesis,
} from './quant_research'

describe('research audit API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses the research run, replay, transition and review contracts', async () => {
    const fetchMock = vi.fn().mockImplementation(() => new Response(JSON.stringify({})))
    vi.stubGlobal('fetch', fetchMock)

    const request = {
      strategy: 's1',
      start: '2026-01-01',
      end: '2026-01-31',
      split: {
        train_start: '2025-01-01', train_end: '2025-06-30', oos_start: '2025-07-01', oos_end: '2025-12-31',
      },
      hypothesis_id: 'H-2026-001',
      hypothesis_revision: 3,
      historical_universe_id: 'ashare-2025',
      strict_pit: true,
    }
    await createResearchBacktestRun(request)
    await submitResearchBacktestJob(request)
    await getResearchBacktestJob('job/1')
    await replayResearchBacktestRun('RR/1')
    await publishResearchBacktestRun('RR/1', {
      manifest_sha256: 'a'.repeat(64),
      reviewer: 'reviewer',
      reason: 'evidence checked',
    })
    await rejectResearchBacktestRun('RR/1', {
      manifest_sha256: 'a'.repeat(64),
      reviewer: 'reviewer',
      reason: 'evidence rejected',
    })
    await listResearchMembershipSnapshots({ universeId: 'IDX/1', asOf: '2025-01-31' })
    await importResearchMembershipSnapshots({
      snapshots: [{
        universe_id: 'IDX/1', as_of: '2025-01-31', available_at: '2025-01-31', members: ['000001'], source_id: 'source',
        source_url: 'https://example.test/idx', snapshot_revision: 'r1', fetched_at: '2025-02-01T00:00:00Z',
        payload_sha256: 'a'.repeat(64), parser_revision: 'fixture-parser-v1', pit_membership: true,
      }],
    })
    await listResearchPointInTimeFacts({ entityId: '000001', factType: 'financial', asOf: '2025-01-31' })
    await importResearchPointInTimeFacts({
      facts: [{
        observation_id: 'fact-1', entity_id: '000001', observed_on: '2024-12-31', available_at: '2025-01-15',
        source_id: 'source', source_url: 'https://example.test/fact', revision: 'r1', fetched_at: '2025-02-01T00:00:00Z',
        payload_sha256: 'b'.repeat(64), parser_revision: 'fixture-parser-v1', fact_type: 'financial',
      }],
    })
    await transitionResearchHypothesis('H/1', {
      target: 'testing', actor: 'reviewer', reason: 'start', evidence: [], expected_revision: 1,
    })
    await reviewResearchHypothesis('H/1', {
      decision: 'rejected', actor: 'reviewer', reason: 'failed', evidence: [], expected_revision: 2,
    })

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/research/backtest-runs', expect.objectContaining({
      method: 'POST', body: JSON.stringify(request),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/research/backtest-jobs', expect.objectContaining({
      method: 'POST', body: JSON.stringify(request),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/research/backtest-jobs/job%2F1', expect.objectContaining({ credentials: 'same-origin' }))
    expect(fetchMock).toHaveBeenNthCalledWith(4, '/api/research/backtest-runs/RR%2F1/replay', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(5, '/api/research/backtest-runs/RR%2F1/publish', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ manifest_sha256: 'a'.repeat(64), reviewer: 'reviewer', reason: 'evidence checked' }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(6, '/api/research/backtest-runs/RR%2F1/reject', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ manifest_sha256: 'a'.repeat(64), reviewer: 'reviewer', reason: 'evidence rejected' }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(7, '/api/research/membership-snapshots?universe_id=IDX%2F1&as_of=2025-01-31', expect.objectContaining({ credentials: 'same-origin' }))
    expect(fetchMock).toHaveBeenNthCalledWith(8, '/api/research/membership-snapshots/import', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(9, '/api/research/point-in-time-facts?entity_id=000001&fact_type=financial&as_of=2025-01-31', expect.objectContaining({ credentials: 'same-origin' }))
    expect(fetchMock).toHaveBeenNthCalledWith(10, '/api/research/point-in-time-facts/import', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(11, '/api/research/hypotheses/H%2F1/transition', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(12, '/api/research/hypotheses/H%2F1/review', expect.objectContaining({ method: 'POST' }))
    expect(researchArtifactUrl('RR/1', 'report.json')).toBe('/api/research/backtest-runs/RR%2F1/artifact?path=report.json')
  })
})

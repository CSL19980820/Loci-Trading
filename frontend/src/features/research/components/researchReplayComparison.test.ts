import { describe, expect, it } from 'vitest'

import { summarizeReplayComparison } from './researchReplayComparison'

describe('summarizeReplayComparison', () => {
  it('passes only when the whole frozen execution comparison passes', () => {
    expect(summarizeReplayComparison({
      contract_version: 'research-replay-comparison-v2',
      run_id: 'RR-1',
      source_manifest_sha256: 'a',
      input_sha256: 'b',
      matches_card_metrics: true,
      execution_matches: { main: true, control: true, train: true, oos: true },
      matches_all_recomputed_execution: true,
    })).toMatchObject({ matches: true, mismatches: [] })
  })

  it('does not turn a matching main metric into a successful replay', () => {
    const result = summarizeReplayComparison({
      contract_version: 'research-replay-comparison-v2',
      run_id: 'RR-1',
      source_manifest_sha256: 'a',
      input_sha256: 'b',
      matches_card_metrics: true,
      execution_matches: { main: true, control: false, train: true, oos: false },
      matches_all_recomputed_execution: false,
    })

    expect(result.matches).toBe(false)
    expect(result.mismatches).toEqual(['随机对照', 'OOS 阶段'])
    expect(result.message).toContain('随机对照')
  })

  it('fails closed when the aggregate flag contradicts a component result', () => {
    expect(summarizeReplayComparison({
      contract_version: 'research-replay-comparison-v2',
      run_id: 'RR-1',
      source_manifest_sha256: 'a',
      input_sha256: 'b',
      matches_card_metrics: true,
      execution_matches: { main: true, control: false, train: true, oos: true },
      matches_all_recomputed_execution: true,
    })).toMatchObject({ matches: false, mismatches: ['随机对照'] })
  })
})

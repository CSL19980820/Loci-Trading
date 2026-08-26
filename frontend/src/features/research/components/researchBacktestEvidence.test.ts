import { describe, expect, it } from 'vitest'

import type { ResearchBacktestRun } from '@/shared/types/quant-research'

import {
  isExploratoryRun,
  provenanceEntries,
  sourceEvidenceIssues,
  sourceEvidenceRows,
} from './researchBacktestEvidence'

function run(): ResearchBacktestRun {
  return {
    contract_version: 'research-run-card-v1', run_id: 'run-evidence',
    strategy_slug: 'sanyuan-tail-v1', strategy_revision: 'builtin:v2', version: 'v2',
    hypothesis_id: null, hypothesis_revision: null, requested_as_of: '2025-12-31', actual_as_of: '2025-12-31',
    market_revision: 'market-r1', universe: {}, universe_funnel: {}, params: {}, backtest_config: {},
    data_snapshot: {
      frozen_input_sha256: 'frozen-r1',
      temporal_membership: {
        universe_id: 'CSI300-2025', available_at: '2025-01-02', source_id: 'fixture-membership',
        fetched_at: '2026-08-05T09:30:00Z', payload_sha256: 'a'.repeat(64), parser_revision: 'parser-r1',
      },
    },
    source_evidence: [{
      attempts_not_observed: true,
      unresolved_codes: ['600002'],
      sources: [{ source_id: 'fixture-source', state: 'failed', error: 'upstream timeout' }],
      receipts: [{ receipt_id: 'receipt-1', code: '600002', state: 'failed', error: 'coverage missing' }],
      attempts: [{ source_id: 'fixture-source', state: 'failed', error: 'upstream timeout' }],
    }],
    metrics: {}, validation: { status: 'degraded', strict_pit: false }, risk_xray: {}, conclusion: null,
    artifact_manifest: [], status: 'awaiting_human_review', created_at: '', updated_at: '',
    input_sha256: 'input-r1', artifact_manifest_sha256: 'm'.repeat(64), manifest_sha256: 'm'.repeat(64), error: '',
  }
}

describe('researchBacktestEvidence', () => {
  it('labels an unproven PIT run as exploratory and retains all backend receipt failures', () => {
    const evidenceRun = run()

    expect(isExploratoryRun(evidenceRun)).toBe(true)
    expect(provenanceEntries(evidenceRun)).toEqual(expect.arrayContaining([
      { key: 'temporal_membership.payload_sha256', value: 'a'.repeat(64) },
      { key: 'temporal_membership.parser_revision', value: 'parser-r1' },
    ]))
    expect(sourceEvidenceRows(evidenceRun).map((row) => row.kind)).toEqual([
      '来源', '路由回执', '来源尝试',
    ])
    expect(sourceEvidenceIssues(evidenceRun)).toEqual(expect.arrayContaining([
      '来源 attempt 未观测',
      '未解析代码：600002',
      '来源失败：fixture-source（upstream timeout）',
      '回执错误：600002（coverage missing）',
      '尝试错误：fixture-source（upstream timeout）',
    ]))
  })
})

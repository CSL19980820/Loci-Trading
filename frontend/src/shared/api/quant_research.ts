/** 研究：维度目录、来源状态和只读个股剖面。 */
import { quantRequest, query } from '@/shared/api/quant_client'
import type {
  ResearchBudget,
  CreateResearchBacktestRunPayload,
  CreateResearchHypothesisPayload,
  ResearchCatalog,
  ResearchBacktestRun,
  ResearchBacktestJob,
  ResearchHypothesis,
  ResearchHypothesisReviewPayload,
  ResearchHypothesisTransitionPayload,
  ResearchProfile,
  ResearchReplayResult,
  ResearchRunResult,
  ResearchWorkflow,
} from '@/shared/types/quant'
import type {
  CreatePth252FactorJobPayload,
  ResearchBacktestPublicationPayload,
  ResearchBacktestPublicationResult,
  ResearchBacktestRejectionPayload,
  ResearchBacktestRejectionResult,
  ResearchMembershipSnapshotImportPayload,
  ResearchMembershipSnapshotList,
  ResearchPointInTimeFactImportPayload,
  ResearchPointInTimeFactList,
} from '@/shared/types/quant-research'

export function getResearchCatalog(): Promise<ResearchCatalog> {
  return quantRequest<ResearchCatalog>('/research/catalog')
}

export function getResearchProfile(
  code: string,
  budget: ResearchBudget = 'standard',
  asOf?: string,
): Promise<ResearchProfile> {
  return quantRequest<ResearchProfile>(
    `/research/profile/${encodeURIComponent(code)}${query({ budget, as_of: asOf })}`,
  )
}

export function createResearchRun(payload: {
  code: string
  budget: ResearchBudget
  as_of?: string
}): Promise<ResearchRunResult> {
  return quantRequest<ResearchRunResult>('/research/runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getResearchRun(runId: string): Promise<ResearchRunResult> {
  return quantRequest<ResearchRunResult>(`/research/runs/${encodeURIComponent(runId)}`)
}

export function resumeResearchRun(runId: string): Promise<ResearchRunResult> {
  return quantRequest<ResearchRunResult>(`/research/runs/${encodeURIComponent(runId)}/resume`, {
    method: 'POST',
  })
}

export function createResearchBacktestRun(
  payload: CreateResearchBacktestRunPayload,
): Promise<{ job: ResearchBacktestJob }> {
  return quantRequest('/research/backtest-runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function submitResearchBacktestJob(
  payload: CreateResearchBacktestRunPayload,
): Promise<{ job: ResearchBacktestJob }> {
  return quantRequest('/research/backtest-jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getResearchBacktestJob(jobId: string): Promise<{ job: ResearchBacktestJob }> {
  return quantRequest(`/research/backtest-jobs/${encodeURIComponent(jobId)}`)
}

export function submitPth252FactorJob(
  payload: CreatePth252FactorJobPayload,
): Promise<{ job: ResearchBacktestJob }> {
  return quantRequest('/research/factor-jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getResearchFactorJob(jobId: string): Promise<{ job: ResearchBacktestJob }> {
  return quantRequest(`/research/factor-jobs/${encodeURIComponent(jobId)}`)
}

export function listResearchBacktestRuns(): Promise<{ items: ResearchBacktestRun[]; total: number }> {
  return quantRequest('/research/backtest-runs')
}

export function getResearchBacktestRun(runId: string): Promise<ResearchBacktestRun> {
  return quantRequest(`/research/backtest-runs/${encodeURIComponent(runId)}`)
}

export function getResearchWorkflow(runId: string): Promise<ResearchWorkflow> {
  return quantRequest(`/research/backtest-runs/${encodeURIComponent(runId)}/workflow`)
}

export function publishResearchBacktestRun(
  runId: string,
  payload: ResearchBacktestPublicationPayload,
): Promise<ResearchBacktestPublicationResult> {
  return quantRequest(`/research/backtest-runs/${encodeURIComponent(runId)}/publish`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function rejectResearchBacktestRun(
  runId: string,
  payload: ResearchBacktestRejectionPayload,
): Promise<ResearchBacktestRejectionResult> {
  return quantRequest(`/research/backtest-runs/${encodeURIComponent(runId)}/reject`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listResearchMembershipSnapshots(options: {
  universeId?: string
  asOf?: string
} = {}): Promise<ResearchMembershipSnapshotList> {
  return quantRequest(
    `/research/membership-snapshots${query({ universe_id: options.universeId, as_of: options.asOf })}`,
  )
}

export function importResearchMembershipSnapshots(
  payload: ResearchMembershipSnapshotImportPayload,
): Promise<{ items: ResearchMembershipSnapshotList['items']; total: number }> {
  return quantRequest('/research/membership-snapshots/import', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listResearchPointInTimeFacts(options: {
  entityId?: string
  factType?: 'financial' | 'event' | 'other'
  asOf?: string
} = {}): Promise<ResearchPointInTimeFactList> {
  return quantRequest(
    `/research/point-in-time-facts${query({
      entity_id: options.entityId,
      fact_type: options.factType,
      as_of: options.asOf,
    })}`,
  )
}

export function importResearchPointInTimeFacts(
  payload: ResearchPointInTimeFactImportPayload,
): Promise<{ items: ResearchPointInTimeFactList['items']; total: number }> {
  return quantRequest('/research/point-in-time-facts/import', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function replayResearchBacktestRun(
  runId: string,
  options: { signal?: AbortSignal } = {},
): Promise<ResearchReplayResult> {
  return quantRequest(`/research/backtest-runs/${encodeURIComponent(runId)}/replay`, {
    method: 'POST',
    timeoutMs: 300_000,
    signal: options.signal,
  })
}

export function researchArtifactUrl(runId: string, path: string): string {
  return `/api/research/backtest-runs/${encodeURIComponent(runId)}/artifact${query({ path })}`
}

export function listResearchHypotheses(): Promise<{ items: ResearchHypothesis[]; total: number }> {
  return quantRequest('/research/hypotheses')
}

export function createResearchHypothesis(
  payload: CreateResearchHypothesisPayload,
): Promise<{ hypothesis: ResearchHypothesis }> {
  return quantRequest('/research/hypotheses', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function reviewResearchHypothesis(
  hypothesisId: string,
  payload: ResearchHypothesisReviewPayload,
): Promise<{ hypothesis: ResearchHypothesis; reused: boolean }> {
  return quantRequest(`/research/hypotheses/${encodeURIComponent(hypothesisId)}/review`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function transitionResearchHypothesis(
  hypothesisId: string,
  payload: ResearchHypothesisTransitionPayload,
): Promise<{ hypothesis: ResearchHypothesis; reused: boolean }> {
  return quantRequest(`/research/hypotheses/${encodeURIComponent(hypothesisId)}/transition`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

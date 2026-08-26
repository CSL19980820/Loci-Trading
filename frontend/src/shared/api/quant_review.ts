/** 复盘：候选结果 / 预案兑现 / 胜率。 */
import { quantRequest, query } from '@/shared/api/quant_client'
import type {
  CandidateOutcome,
  CandidateSummary,
  PlanOutcome,
  WinRateSummary,
  WinRateTrendPoint,
} from '@/shared/types/quant'

export function getCandidateOutcomes(
  limit = 300,
  options: {
    window_days?: number
    selected_only?: boolean
    as_of?: string
    benchmark?: string
  } = {},
) {
  return quantRequest<{
    outcomes: CandidateOutcome[]
    summary: CandidateSummary
  }>(
    `/review/candidates${query({
      limit,
      window_days: options.window_days,
      selected_only:
        options.selected_only === undefined ? undefined : options.selected_only ? 1 : 0,
      as_of: options.as_of,
      benchmark: options.benchmark,
    })}`,
  )
}

export function getPlanOutcomes() {
  return quantRequest<PlanOutcome[]>('/review/plans')
}

export function getWinRateSummary(): Promise<WinRateSummary[]> {
  return quantRequest('/winrate/summary')
}

export function getWinRateTrend(options: {
  granularity?: 'month' | 'week'
  tags?: string
} = {}): Promise<WinRateTrendPoint[]> {
  return quantRequest(`/winrate/trend${query(options)}`)
}

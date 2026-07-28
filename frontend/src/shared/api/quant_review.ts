/** 复盘：权益曲线 / 往返交易 / 候选结果 / 胜率。 */
import { quantRequest, query } from '@/shared/api/quant_client'
import type {
  CandidateOutcome,
  CandidateSummary,
  EquityCurve,
  PlanOutcome,
  RoundTrip,
  RoundTripSummary,
  WinRateSummary,
  WinRateTrendPoint,
} from '@/shared/types/quant'

export function getEquityCurve(options: { start?: string; end?: string; benchmarks?: string } = {}) {
  return quantRequest<EquityCurve>(`/review/equity${query(options)}`)
}

export function getRoundTrips(code?: string) {
  return quantRequest<{
    trips: RoundTrip[]
    summary: RoundTripSummary
  }>(`/review/trips${query({ code })}`)
}

export function getCandidateOutcomes(limit = 300) {
  return quantRequest<{
    outcomes: CandidateOutcome[]
    summary: CandidateSummary
  }>(`/review/candidates${query({ limit })}`)
}

export function getPlanOutcomes() {
  return quantRequest<PlanOutcome[]>('/review/plans')
}

export function getPositionsAsOf(date?: string) {
  return quantRequest<{ code: string; name: string; shares: number; cost: number; cost_value: number }[]>(
    `/review/positions${query({ date })}`,
  )
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

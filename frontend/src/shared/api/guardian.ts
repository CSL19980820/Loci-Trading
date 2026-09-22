import { quantRequest, query } from './quant_client'
import { streamEvents } from './event_stream'
import type { GuardianConsultTurn } from '@/shared/types/guardian'

export const streamGuardianConsultation = (conversationId: string, requestId: string, onTurn: (turn: GuardianConsultTurn) => void, signal: AbortSignal) =>
  streamEvents(`/api/ops/guardian/consultations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(requestId)}/stream`, event => {
    if (event.type === 'snapshot' && event.data.id === requestId && typeof event.data.status === 'string' && event.data.result && typeof event.data.result === 'object') {
      onTurn(event.data as unknown as GuardianConsultTurn)
    }
  }, signal)
import type { GuardianConfig, GuardianStatus, GuardianTrade, GuardianReviewPeriod, GuardianReviewDetail, GuardianConversation, GuardianConversationDetail, GuardianHistoryQuery, GuardianPage, GuardianReviewSummary, GuardianRun, GuardianResearch, GuardianPerformance } from '@/shared/types/guardian'

export const getGuardian = (signal?: AbortSignal) => quantRequest<GuardianStatus>('/ops/guardian', { signal })
export const scanGuardian = () => quantRequest<{ status: string }>('/ops/guardian/scan', { method: 'POST' })
export const saveGuardian = (config: GuardianConfig) => quantRequest<GuardianStatus>('/ops/guardian', {
  method: 'PUT', body: JSON.stringify(config),
})
export const getGuardianTrades = (options: GuardianHistoryQuery, signal?: AbortSignal) => quantRequest<GuardianPage<GuardianTrade>>(`/ops/guardian/trades${query({ ...options })}`, { signal })
export const getGuardianReports = (options: GuardianHistoryQuery, signal?: AbortSignal) => quantRequest<GuardianPage<GuardianReviewSummary>>(`/ops/guardian/reviews${query({ ...options })}`, { signal })
export const getGuardianRuns = (options: GuardianHistoryQuery, signal?: AbortSignal) => quantRequest<GuardianPage<GuardianRun>>(`/ops/guardian/runs${query({ ...options })}`, { signal })
export const getGuardianActivity = (limit = 16, signal?: AbortSignal) => quantRequest<{ runs: GuardianRun[]; reports: GuardianReviewSummary[]; limit: number }>(`/ops/guardian/activity${query({ limit })}`, { signal })
export const getGuardianRun = (slot: string, signal?: AbortSignal) => quantRequest<GuardianRun>(`/ops/guardian/runs/${encodeURIComponent(slot)}`, { signal })
export const getGuardianResearch = (signal?: AbortSignal) => quantRequest<GuardianResearch>('/ops/guardian/research', { signal })
export const getGuardianPerformance = (offset = 0, limit = 20, signal?: AbortSignal) => quantRequest<GuardianPage<GuardianPerformance>>(`/ops/guardian/performance${query({ offset, limit })}`, { signal })
export const getGuardianReview = (period: GuardianReviewPeriod, day: string, signal?: AbortSignal) => quantRequest<GuardianReviewDetail>(`/ops/guardian/reviews/${period}/${day}`, { signal })
export const runGuardianReview = (period: GuardianReviewPeriod) => quantRequest<{ status: string; report_key: string }>('/ops/guardian/reviews/run', { method: 'POST', body: JSON.stringify({ period }) })
export const getGuardianConversations = () => quantRequest<{ conversations: GuardianConversation[] }>('/ops/guardian/consultations')
export const getGuardianConversation = (id: string, signal?: AbortSignal) => quantRequest<GuardianConversationDetail>(`/ops/guardian/consultations/${id}`, { signal })
export const askGuardian = (payload: { conversation_id: string; request_id: string; message: string; real_context: string }) => quantRequest<{ conversation_id: string; request_id: string; status: string }>('/ops/guardian/consultations', { method: 'POST', body: JSON.stringify(payload) })

export const deleteGuardianConversation = (id: string) => quantRequest<{ deleted: boolean }>(`/ops/guardian/consultations/${encodeURIComponent(id)}`, { method: 'DELETE' })

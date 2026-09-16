import { quantRequest, query } from './quant_client'
import type { AgentConfig, AgentOptions, AgentSummary, AgentProfile, AgentPage, AgentHistoryKind, AgentPhase, AgentEquity, AgentRunDetail, GuardianCard, GuardianStorageStats } from '@/shared/types/stock_agents'
const base = '/ops/stock-agents'
const path = (id: string) => `${base}/${encodeURIComponent(id)}`
export const getGuardianCard = (signal?:AbortSignal) => quantRequest<GuardianCard>(`${base}/guardian/overview`, { signal })
export const getGuardianStorage = (signal?:AbortSignal) => quantRequest<GuardianStorageStats>(`${base}/guardian/storage`, { signal })
export const saveGuardianStorage = (retention:GuardianStorageStats['retention']) => quantRequest<GuardianStorageStats>(`${base}/guardian/storage`, { method:'PUT',body:JSON.stringify(retention) })
export const cleanGuardianStorage = (dryRun = true) => quantRequest<{ removed:number; eligible:number; more_possible?:boolean }>(`${base}/guardian/cleanup${query({ dry_run:String(dryRun) })}`, { method:'POST' })
export const getStockAgents = (signal?: AbortSignal, includeArchived = false) => quantRequest<{ items: AgentSummary[]; as_of: string }>(`${base}${query({ include_archived: String(includeArchived) })}`, { signal })
export const getAgentOptions = (signal?: AbortSignal) => quantRequest<AgentOptions>(`${base}/options`, { signal })
export const getStockAgent = (id: string, signal?: AbortSignal) => quantRequest<AgentProfile>(path(id), { signal })
export const createStockAgent = (config: AgentConfig) => quantRequest<AgentProfile>(base, { method: 'POST', body: JSON.stringify(config) })
export const saveStockAgent = (id: string, config: AgentConfig, revision: number) => quantRequest<AgentProfile>(path(id), { method: 'PUT', body: JSON.stringify({ config, revision }) })
export const getAgentHistory = (id: string, kind: AgentHistoryKind, offset = 0, start?: string, end?: string, signal?: AbortSignal) => quantRequest<AgentPage>(`${path(id)}/history${query({ kind, limit: 20, offset, start, end })}`, { signal })
export const getAgentRun = (id: string, runId: string, signal?: AbortSignal) => quantRequest<AgentRunDetail>(`${path(id)}/runs/${encodeURIComponent(runId)}`, { signal })
export const getAgentEquity = (id: string, signal?: AbortSignal) => quantRequest<{ items: AgentEquity[]; total: number; truncated: boolean; caliber: string }>(`${path(id)}/equity`, { signal })
export const fundAgent = (id: string, amountCents: number, requestId: string) => quantRequest<AgentProfile>(`${path(id)}/funds`, { method: 'POST', body: JSON.stringify({ amount_cents: amountCents, request_id: requestId }) })
export const runStockAgent = (id: string, phase: AgentPhase, requestId: string) => quantRequest<{ status: string; run_id: string }>(`${path(id)}/run`, { method: 'POST', body: JSON.stringify({ phase, request_id: requestId }) })
export const cleanAgentDiary = (id: string, dryRun = true) => quantRequest<{ removed: number; eligible?: number; more_possible?: boolean; protected?: string }>(`${path(id)}/cleanup${query({ dry_run: String(dryRun) })}`, { method: 'POST' })
export const archiveStockAgent = (id: string, revision: number) => quantRequest<{ archived: boolean }>(`${path(id)}/archive${query({ revision })}`, { method: 'POST' })

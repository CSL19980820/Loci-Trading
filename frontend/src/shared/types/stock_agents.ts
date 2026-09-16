import type { GuardianAccount, GuardianRun, GuardianConfig } from './guardian'

export type AgentKind = 'custom' | 'leader'
export type AgentPhase = 'review' | 'premarket' | 'auction' | 'intraday' | 'closeout'
export type AgentHistoryKind = 'runs' | 'trades' | 'funding'
export interface GuardianStorageStats {
  total_runs:number; full_entries:number; compacted_entries:number; total_trades:number; total_reports:number
  retention:{ days:number; max_entries:number; cleanup_hours:number }; protected_recent:number
}
export interface GuardianCard {
  config:Pick<GuardianConfig,'enabled' | 'provider' | 'model'>; state:GuardianAccount; runs:GuardianRun[]
  stats:GuardianStorageStats; position_policy:{ close_max:number; temporary_max:number }
}
export interface AgentConfig {
  name: string; kind: AgentKind; description: string; provider: string; model: string
  prompt: string; enabled: boolean; initial_capital_cents: number; strategies: string[]
  daily_selection_limit: number; watch_limit: number; position_limit: number
  temporary_position_limit: number; max_position_pct: number; timeout_seconds: number
  schedule: { timezone: 'Asia/Shanghai'; review_time: string; premarket_time: string
    auction_time: '09:25'; intraday_minutes: 5 | 10 | 15 | 30; intraday_enabled: boolean }
  retention: { days: number; max_entries: number; cleanup_hours: number }
}
export interface AgentAction { code: string; name: string; action: string; quantity: number; status: string }
export interface AgentProfile {
  id: string; revision: number; state_version: number; config: AgentConfig
  archived: boolean | number; created_at: string; updated_at: string; running: boolean
  total_runs: number; total_actions: number; total_trades: number; cleaned_runs: number; history_kept: number
  latest_at: string | null; latest_phase: AgentPhase | null; latest_status: string | null
  latest_summary: string; latest_actions: AgentAction[]
  state: GuardianAccount & { watchlist?: { code: string; name: string; reason?: string }[]
    selected_today?: { date: string; codes: string[] }; agent_close_keep_codes?: string[] }
  schedules: { phase: AgentPhase; label: string; time: string; enabled: boolean }[]
}
export interface AgentSummary extends Omit<AgentProfile, 'config' | 'state'> {
  config: Pick<AgentConfig, 'name' | 'kind' | 'description' | 'provider' | 'model' | 'enabled'>
  state: Pick<GuardianAccount, 'equity_cents' | 'cash_cents' | 'initial_capital_cents' | 'total_pnl_cents' | 'valuation_at' | 'stale_codes'> & {
    position_count: number; watchlist: { code: string; name: string }[] }
}
export interface AgentHistoryRow {
  id?: string | number; request_id?: string; phase?: AgentPhase; started_at?: string; finished_at?: string
  at?: string; status?: string; summary?: string; actions?: AgentAction[]; code?: string; name?: string
  action?: string; side?: string; quantity?: number; price_cents?: number; amount_cents?: number; gross_cents?: number
  fees_cents?: number; realized_pnl_cents?: number; reason?: string; kind?: string
}
export interface AgentPage<T = AgentHistoryRow> { items: T[]; total: number; offset: number; limit: number }
export interface AgentEquity { day: string; at: string; equity_cents: number; funded_cents: number
  pnl_cents: number; realized_pnl_cents: number; fees_cents: number; stale: number }
export interface AgentRunDetail extends AgentHistoryRow {
  detail: { summary?: string; decisions?: { code: string; name?: string; action: string; quantity: number; reason: string }[]
    rejects?: { code?: string; action?: string; reason?: string }[]
    usage?: { model?: string; input_tokens?: number; output_tokens?: number; tool_calls?: number; elapsed_ms?: number }
    analysis_only?: boolean }
}
export interface AgentOptions { templates: Record<AgentKind, AgentConfig>; strategies: { slug: string; name: string; description: string }[]; timezone: string }

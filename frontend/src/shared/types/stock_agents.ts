import type { GuardianReportSection } from './guardian'
import type { GuardianAccount, GuardianPosition, GuardianRun, GuardianConfig } from './guardian'

export type AgentKind = 'custom' | 'leader' | 'falcon'
export type AgentPhase = 'review' | 'weekly_review' | 'premarket' | 'auction' | 'intraday' | 'closeout' | 'research'
export type AgentHistoryKind = 'runs' | 'trades' | 'funding'
export interface GuardianStorageStats {
  total_runs:number; full_entries:number; compacted_entries:number; total_trades:number; total_reports:number
  retention:{ days:number; max_entries:number; cleanup_hours:number }; protected_recent:number
}
export interface GuardianCard {
  config:Pick<GuardianConfig,'enabled' | 'provider' | 'model'>; state:GuardianAccount; runs:GuardianRun[]
  stats:GuardianStorageStats; position_policy:{ normal_max:number | null; absolute_max:number | null; close_max:number | null }
}
export interface GuardianSummary {
  config: GuardianCard['config']; runs: GuardianRun[]; position_count: number
  state: Pick<GuardianAccount, 'equity_cents' | 'total_pnl_cents' | 'valuation_at' | 'stale_codes'>
}
export interface AgentConfig {
  name: string; kind: AgentKind; description: string; provider: string; model: string
  prompt: string; enabled: boolean; initial_capital_cents: number; strategies: string[]
  premarket_prompt?: string; review_prompt?: string; weekly_review_prompt?: string
  common_prompt?: string
  daily_selection_limit: number; watch_limit: number; position_limit: number
  temporary_position_limit: number; max_position_pct: number; timeout_seconds: number
  thinking?: string; parallel_tools?: number
  schedule: { timezone: 'Asia/Shanghai'; review_time: string; premarket_time: string
    auction_time: '09:25'; intraday_minutes: 5 | 10 | 15 | 30; intraday_enabled: boolean
    weekly_review_enabled?: boolean; weekly_review_time?: string }
  retention: { days: number; max_entries: number; cleanup_hours: number }
}
export interface AgentAction { code: string; name: string; action: string; quantity: number; status: string }
export type AgentEquityRange = 'day' | 'week' | 'month' | 'half_year' | 'year'
export interface AgentPosition extends GuardianPosition {
  entry_price_cents?: number | null; entry_at?: string | null; holding_days?: number | null
  entry_reason?: string; pnl_pct?: number | null
}
export interface AgentWatch {
  code: string; name: string; reason?: string; added_at?: string; updated_at?: string
  entry_condition?: string; exit_condition?: string
  observed_at?: string | null; observed_price_cents?: number | null
  current_price_cents?: number | null; current_price_at?: string | null
  expected_entry_price_cents?: number | null; reviewed_at?: string | null
  review_reason?: string; review_status?: string
  source_reason?: string; source_signal_date?: string; source_expires_on?: string | null
  source_managed?: boolean; source_refs?: { strategy_slug?: string; source?: string; signal_date?: string; expires_on?: string | null; score?: number | null; reason?: string; evidence_id?: string }[]
}
export interface AgentAssessment {
  code: string; stance: 'participate' | 'wait' | 'avoid' | 'exit' | 'unreviewed'; summary: string
  expected_entry_price?: number | null; focus: boolean; evidence_refs: string[]
  data_status?: 'available' | 'partial' | 'missing'
}
export interface AgentResearchPlan {
  market_view: string; next_trade_date?: string | null
  stocks: { code: string; entry_condition: string; exit_condition: string; invalidation: string; next_check: string }[]
}
export interface AgentAssessmentCoverage {
  required_codes: string[]; reviewed_codes: string[]; unreviewed_codes: string[]; focus_codes: string[]
  total: number; reviewed: number; complete: boolean
}
export interface FalconLearningExample { evidence_ref: string; interpretation: string }
export interface FalconLesson {
  id: string; title: string; finding: string; conditions: string
  status: 'pending' | 'supported' | 'rejected'; evidence_refs: string[]; sample_size: number
  sample_basis: 'executed' | 'observed' | 'hypothetical'; sample_definition: string
  positive_examples: FalconLearningExample[]; counter_examples: FalconLearningExample[]; validation_plan: string
  first_review_date?: string; last_review_date?: string; last_review_phase?: 'review' | 'weekly_review'
}
export interface FalconOptimizationProposal extends FalconLesson { target: 'selection' | 'scoring'; proposed_change: string }
export interface FalconLearningReport { lessons: FalconLesson[]; optimization_proposals: FalconOptimizationProposal[] }
export interface FalconLearningMemory extends FalconLearningReport {
  agent_id?: string; tenant_id?: string; last_review_date?: string; last_review_phase?: 'review' | 'weekly_review'
  limits?: { lessons: number; optimization_proposals: number; max_characters?: number }
}
export interface AgentProfile {
  id: string; revision: number; state_version: number; config: AgentConfig
  archived: boolean | number; created_at: string; updated_at: string; running: boolean
  total_runs: number; total_actions: number; total_trades: number; cleaned_runs: number; history_kept: number
  latest_at: string | null; latest_phase: AgentPhase | null; latest_status: string | null
  latest_summary: string; latest_actions: AgentAction[]
  state: Omit<GuardianAccount, 'positions' | 'watchlist'> & { positions: AgentPosition[]; watchlist?: AgentWatch[]
    selected_today?: { date: string; codes: string[] }; agent_close_keep_codes?: string[]
    research_plan?: string; research_plan_structured?: AgentResearchPlan | null; research_plan_date?: string; research_plan_at?: string
    assessment_coverage?: AgentAssessmentCoverage; falcon_learning?: FalconLearningMemory | null }
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
  sections?: GuardianReportSection[]
  detail: { summary?: string; decisions?: { code: string; name?: string; action: string; quantity: number; reason: string
      holding_plan?: string; take_profit_plan?: string; stop_loss_plan?: string; entry_condition?: string; exit_condition?: string }[]
    rejects?: { code?: string; action?: string; reason?: string }[]
    usage?: { model?: string; input_tokens?: number; output_tokens?: number; tool_calls?: number; elapsed_ms?: number }
    analysis_only?: boolean; research_date?: string; research_cutoff?: string; historical_review?: boolean
    research_plan?: string; workshop_access?: boolean; learning?: FalconLearningReport | null
    assessments?: AgentAssessment[]; research_plan_structured?: AgentResearchPlan | null
    detail?: { market_summary: string; changes: string; next_steps: string } | null
    assessment_coverage?: AgentAssessmentCoverage
    fills?: { code: string; name?: string; side?: 'buy' | 'sell'; action: string; quantity: number; price_cents: number
      gross_cents?: number; fees_cents?: number; realized_pnl_cents?: number; occurred_at?: string; quote_at?: string; reason?: string
      origin?: string; quote_source?: string; at?: string; before_quantity?: number; after_quantity?: number }[]
    quotes?: Record<string, { name?: string; price?: number | null; trade_date?: string; trade_time?: string; source?: string; error?: string }>
    candidate_scope?: { candidates?: { code: string; name?: string; reason?: string }[]; sources?: { code: string; name?: string; reason?: string }[] }
    body?: string; analysis?: string; error?: string }
}
export interface AgentOptions { templates: Record<AgentKind, AgentConfig>; strategies: { slug: string; name: string; description: string }[]; timezone: string }

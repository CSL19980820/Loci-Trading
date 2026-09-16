export interface GuardianConfig {
  enabled: boolean
  provider: string
  model: string
  prompt: string
  strategies: string[]
  notify: boolean
}

export interface GuardianPosition {
  code: string
  name: string
  quantity: number
  available_quantity: number
  cost_cents: number
  average_cost: number
  mark_price_cents: number
  market_value_cents: number
  unrealized_pnl_cents: number
  mark_at: string
  mark_source?: string
  valuation_stale?: boolean
  strategies?: string[]
  holding_plan?: string
  take_profit_plan?: string
  stop_loss_plan?: string
  exit_today_plan?: string
  entry_context?: { reason?: string; opened_at?: string }
  last_review?: { action: string; reason: string; at: string }
}

export interface GuardianDecision {
  code: string
  action: 'buy' | 'add' | 'reduce' | 'sell' | 'take_profit' | 'stop_loss' | 'hold' | 'watch' | 'unwatch'
  reason: string
  holding_plan?: string
  take_profit_plan?: string
  stop_loss_plan?: string
  quantity?: number
  layers?: number
  entry_condition?: string
  exit_condition?: string
  exit_today_plan?: string
  replacement_for?: string
}

export interface GuardianWatch {
  code: string
  name: string
  strategies: string[]
  signals: Array<{ date?: string; reason?: string; rule_version?: string }>
  watch?: { code: string; name: string; reason: string; entry_condition: string; exit_condition: string; added_at: string; updated_at: string }
  position?: GuardianPosition
}

export interface GuardianHistoryQuery { start: string; end: string; limit: number; offset: number }
export interface GuardianPage<T> { items: T[]; total: number; start?: string; end?: string; limit?: number; offset?: number }
export type GuardianResearch = Pick<GuardianStatus, 'active_strategies' | 'watchlist' | 'watchlist_as_of' | 'watchlist_note'>

export interface GuardianRun {
  started?: number
  slot: string
  status: string
  result: {
    body?: string
    analysis?: string
    analysis_only?: boolean
    outcome?: 'traded' | 'no_action'
    deferred?: GuardianDecision[]
    decisions?: GuardianDecision[]
    fills?: Array<Partial<GuardianTrade> & { code: string; before_layers?: number; after_layers?: number; price?: number }>
    rejects?: Array<{ code: string; reason: string }>
    error?: string
    model?: string
    observed?: number
    as_of?: string
    notify?: { success?: boolean; skipped?: string }
  }
}

export interface GuardianStatus {
  notification_silence?: string
  reports?: GuardianReviewSummary[]
  watchlist?: GuardianWatch[]
  watchlist_as_of?: string
  watchlist_note?: string
  active_strategies?: Array<{ slug: string; name: string }>
  data_source?: { label: string; wudao: boolean; reason: string; tool_count: number }
  config: GuardianConfig
  default_prompt: string
  job_id: string | null
  state: GuardianAccount
  observation_count?: number
  trades?: { items: GuardianTrade[]; total: number }
  performance?: GuardianPerformance[]
  runs: GuardianRun[]
}

export interface GuardianConversation { id: string; title: string; notes: string; created: number; updated: number }
export interface GuardianConsultTurn { id: string; question: string; status: string; created: number; result: { answer?: string; error?: string; model?: string; as_of?: string; tools?: { name: string; ok: boolean }[] } }
export interface GuardianConversationDetail extends GuardianConversation { turns: GuardianConsultTurn[] }

export interface GuardianAccount {
  account_version: number
  initial_capital_cents: number
  cash_cents: number
  equity_cents: number
  market_value_cents: number
  realized_pnl_cents: number
  unrealized_pnl_cents: number
  total_pnl_cents: number
  fees_cents: number
  positions: GuardianPosition[]
  valuation_at?: string
  stale_codes: string[]
  valuation_kind?: string
  valuation_date?: string
}

export type GuardianReviewPeriod = 'premarket' | 'daily' | 'weekly'
export interface GuardianReviewSummary {
  started?: number
  report_key: string
  period: GuardianReviewPeriod
  trade_date: string
  status: string
  summary?: string
  error?: string
  created_at?: string
  notify?: { success?: boolean; skipped?: string }
}
export interface GuardianReviewDetail extends GuardianReviewSummary {
  result: { body?: string; sections?: GuardianReportSection[]; error?: string; notify?: { success?: boolean; skipped?: string } }
}
export interface GuardianReportSection {
  heading: string
  kind: string
  paragraphs: string[]
  stats: { label: string; value: string }[]
  plans: { label: string; detail: string; meta: string }[]
  plan_date?: string
}

export interface GuardianTrade {
  id: string
  code: string
  name: string
  side: 'buy' | 'sell'
  action?: GuardianDecision['action']
  quantity: number
  price_cents: number
  gross_cents: number
  fees_cents: number
  commission_cents: number
  stamp_tax_cents: number
  transfer_cents: number
  allocated_cost_cents: number
  realized_pnl_cents: number
  cash_after_cents: number
  before_quantity: number
  after_quantity: number
  occurred_at: string
  quote_at: string
  quote_source: string
  reason: string
  holding_plan?: string
  origin?: string
}

export interface GuardianPerformance {
  code: string
  name: string
  bought_quantity: number
  sold_quantity: number
  realized_pnl_cents: number
  fees_cents: number
  trade_count: number
}

export const GUARDIAN_ACTION_LABELS = { buy: '买入', add: '加仓', reduce: '减仓', sell: '卖出', take_profit: '止盈', stop_loss: '止损', hold: '持股', watch: '观察', unwatch: '撤出观察' } as const

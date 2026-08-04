export interface Position {
  code: string
  name: string
  shares: number
  /** A股 T+1：今日买入不可卖 */
  available_shares?: number
  /** 今日买入股数（冻结，计入持仓但不计入可卖） */
  today_buy_shares?: number
  cost: number
  cost_value: number
  updated_on: string
  /** 当前这轮持仓开仓日 */
  opened_on?: string
  holding_days?: number
  note: string
}

export interface Candidate {
  id: string
  date: string
  pool_id: string
  code: string
  name: string
  score: number | null
  decision: string
  timing: string
  reason: string
  rule_version: string
  evidence: Record<string, string>
  source: string
  created_at: string
}

export interface Plan {
  id: string
  date: string
  code: string
  title: string
  status: string
  scenario: string
  entry_zone: string
  stop_price: number | null
  target_price: number | null
  layers: number | null
  invalidation: string
  rule_version: string
  source: string
  supersedes_id: string
  note: string
  created_at: string
}

export interface Scorecard {
  closed_trades: number
  wins: number
  losses: number
  win_rate: number | null
  profit_factor: number | null
  average_realized: number | null
  realized_pnl: number
  review_groups: Record<string, { count: number; average_return_pct: number }>
}

export interface SummaryCard {
  id: string
  code: string
  name: string
  score: number | null
  decision: string
  timing: string
  reason: string
}

export interface CandidateDaySummary {
  headline: string
  note: string
  text: string
  total: number
  selected_count: number
  filtered_count: number
  all_selected: boolean
  picks: SummaryCard[]
  drops: SummaryCard[]
}

/** 当日卖出一行（dashboard.today_sells） */
export interface TodaySell {
  id: string
  date: string
  created_at: string
  code: string
  name: string
  shares: number
  price: number
  amount: number
  cost_before: number
  cost_after: number
  shares_after: number
  realized_pnl: number
  realized_pnl_pct: number | null
  reason: string
  source: string
  correlation_id: string
}

export interface MonthPnlPoint {
  date: string
  cumulative_pnl: number
}

export interface Dashboard {
  as_of: string
  account: {
    realized_pnl: number
    today_realized_pnl: number | null
    today_realized_note: string
    /** 当月已实现（不含潜龙累计基线） */
    month_realized_pnl?: number
    /** 本月已实现 / 账面总资产 */
    month_realized_pnl_pct?: number | null
    month_realized_note?: string
    total_assets: number | null
    snapshot_date: string | null
    cash: number | null
    cash_base?: number | null
    cash_implied?: boolean
    cost_exposure: number
    cost_exposure_pct: number | null
  }
  positions: Position[]
  /** 当日卖出列表（同花顺式） */
  today_sells?: TodaySell[]
  /** 本月逐日累计已实现曲线 */
  month_pnl_curve?: MonthPnlPoint[]
  candidates: Candidate[]
  candidate_summary: CandidateDaySummary
  plans: Plan[]
  scorecard: Scorecard
  evolution: {
    review_count: number
    gate: number
    ready: boolean
    message: string
  }
}

export interface TimelineEvent {
  id: string
  date: string
  created_at: string
  type: 'trade' | 'candidate' | 'plan' | 'review'
  label: string
  detail: Record<string, unknown>
}

export interface TradePayload {
  action: 'BUY' | 'SELL'
  code: string
  name?: string
  shares: number
  price: number
  occurred_on?: string
  reason?: string
  correlation_id?: string
}

export interface TradeRecord {
  id: string
  date: string
  created_at: string
  code: string
  name: string
  action: 'OPENING' | 'BUY' | 'SELL' | string
  shares: number
  price: number
  amount: number
  shares_before: number
  shares_after: number
  cost_before: number
  cost_after: number
  realized_pnl: number
  reason: string
  source: string
  correlation_id: string
}

export interface ReviewRecord {
  id: string
  date: string
  entity_type: 'plan' | 'candidate' | 'trade' | string
  entity_id: string
  strategy_tag: string
  outcome: string
  return_pct: number | null
  max_favorable_pct: number | null
  max_adverse_pct: number | null
  lesson: string
  next_rule: string
  source: string
  created_at: string
}

export interface PoolSummary {
  date: string
  pool_id: string
  total: number
  selected: number
  filtered: number
  scored: number
  avg_score: number | null
}

export interface PoolDay {
  date: string
  pool_id: string
  total: number
  selected_count: number
  filtered_count: number
  selected: Candidate[]
  filtered: Candidate[]
  all: Candidate[]
  summary: CandidateDaySummary
}

export interface Analytics {
  equity_curve: Array<{ date: string; cumulative_pnl: number }>
  daily_pnl: Array<{ date: string; pnl: number }>
  decisions: Array<{ decision: string; count: number }>
  review_returns: Array<{ date: string; return_pct: number; strategy_tag: string }>
  actions: Array<{ action: string; count: number; realized_pnl: number }>
  scorecard: Scorecard
}
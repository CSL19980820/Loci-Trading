// ---- 复盘 ------------------------------------------------------------
// 与回测问的是两个不同问题：回测问"这套战法有没有 alpha"，
// 复盘问"我自己做得怎么样"。

export interface EquityPoint {
  trade_date: string
  holding_value: number
  cash: number
  total_equity: number
  floating_pnl: number
  realized_pnl_cum: number
  drawdown_pct: number
  benchmarks: Record<string, number>
}

export interface EquityCurve {
  points: EquityPoint[]
  metrics: Record<string, number | string | null>
  /** anchored = 有资产快照校准；estimated = 绝对值仅供参考，形状仍可用 */
  confidence: 'anchored' | 'estimated' | 'none'
  note: string
}

export interface RoundTrip {
  code: string
  name: string
  opened_on: string
  closed_on: string | null
  is_open: boolean
  peak_shares: number
  avg_cost: number
  buy_amount: number
  sell_amount: number
  realized_pnl: number
  return_pct: number | null
  hold_days: number | null
  mae_pct: number | null
  mfe_pct: number | null
  event_ids: string[]
}

export interface RoundTripSummary {
  total: number
  closed: number
  open: number
  realized_pnl?: number
  win_rate?: number
  avg_return_pct?: number
  profit_factor?: number | null
  avg_mae_pct?: number
  avg_mfe_pct?: number
  winner_avg_mae_pct?: number
  loser_avg_mae_pct?: number
  profit_give_back_pct?: number
  avg_hold_days?: number
  best_pct?: number
  worst_pct?: number
  hint?: string
  caution?: string
  by_code: Record<string, { name: string; count: number; realized_pnl: number }>
  by_month: Record<string, { count: number; realized_pnl: number }>
}

export interface CandidateOutcome {
  candidate_id: string
  code: string
  name: string
  base_date: string
  decision: string
  selected: boolean
  score: number | null
  base_close: number | null
  returns: Record<string, number | null>
  alpha: Record<string, number | null>
  max_favorable_pct: number | null
  note: string
  tier?: string
  strategy_slug?: string
  rule_version?: string
  window?: {
    status: 'observing' | 'partial' | 'complete' | string
    ready_horizons: number[]
    pending_horizons: number[]
  }
}

export interface CandidateSummary {
  total: number
  evaluated: number
  by_decision: Record<string, Record<string, unknown>>
  selected: Record<string, unknown>
  rejected: Record<string, unknown>
  /** 当初否决、事后大涨的票——改进选股规则最直接的线索 */
  missed_winners: {
    code: string
    name: string
    base_date: string
    decision: string
    return_t20: number | null
    max_favorable_pct: number | null
  }[]
  score_buckets?: { range: string; count: number; avg_t20: number | null; win_rate: number | null }[]
}

export interface PlanOutcome {
  plan_id: string
  code: string
  title: string
  occurred_on: string
  stop_price: number | null
  target_price: number | null
  stop_hit_on: string | null
  target_hit_on: string | null
  status_final: string
  note?: string
}

// ---- 分析任务（异步）-------------------------------------------------
// 横向对比与退出扫描是分钟级的，同步返回会被网关超时掐断，
// 所以走后台任务 + 轮询。

export interface AnalysisStarted {
  job_id: string
  run_id: string
  kind: 'compare' | 'optimize'
  status: string
  poll: string
}

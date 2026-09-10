/**
 * 逐笔（trade）回测的产物：指标、净值曲线、成交明细。字段最多的一支，且只被
 * 回测报告页消费；与持有期回测（`horizon.ts`）是两套互不兼容的口径，不要混用。
 */

export interface BacktestMetrics {
  trades: number
  win_rate?: number
  wins?: number
  losses?: number
  avg_gross_return?: number
  avg_net_return?: number
  median_net_return?: number
  std_net_return?: number
  total_net_return?: number
  best?: number
  worst?: number
  expectancy?: number
  profit_factor?: number | null
  payoff_ratio?: number | null
  avg_win?: number | null
  avg_loss?: number | null
  avg_mfe?: number
  avg_mae?: number
  avg_hold_days?: number
  max_consecutive_wins?: number
  max_consecutive_losses?: number
  exit_reasons?: Record<string, number>
  data_end_trades?: number
  avg_alpha?: number
  alpha_win_rate?: number
  percentiles?: Record<string, number>
  return_distribution?: Array<{ lo: number; hi: number; n: number }>
  by_month?: Array<{ period: string; n: number; win_rate: number; avg: number; total?: number }>
  by_year?: Array<{ period: string; n: number; win_rate: number; avg: number; total?: number }>
  sample_confidence?: 'low' | 'medium' | 'high' | string
  caution?: string
}

export interface BacktestPerformancePoint {
  date: string
  equity: number
  drawdown_pct: number
  trade_count?: number
  return_pct?: number
  code?: string
}

export interface BacktestPerformance {
  available: boolean
  reason?: string
  assumption?: {
    model: string
    description?: string
    risk_free_rate_pct?: number
    initial_equity?: number
    excludes_data_end?: boolean
  }
  trades?: number
  cumulative_return_pct?: number
  cagr_pct?: number | null
  max_drawdown_pct?: number
  max_drawdown_peak_date?: string | null
  max_drawdown_trough_date?: string | null
  max_drawdown_recovery_days?: number | null
  volatility_pct?: number
  downside_volatility_pct?: number
  sharpe?: number | null
  sortino?: number | null
  calmar?: number | null
  years?: number | null
  trades_per_year?: number | null
  final_equity?: number
  equity_curve?: BacktestPerformancePoint[]
  drawdown_curve?: Array<{ date: string; drawdown_pct: number }>
  peak_equity?: number
  curve_peak_date?: string
}

export interface BacktestTrade {
  code: string
  signal_date: string
  entry_date: string
  entry_price: number
  exit_date: string
  exit_price: number
  hold_days: number
  gross_return_pct: number
  net_return_pct: number
  mae_pct: number
  mfe_pct: number
  exit_reason: string
  benchmark_return_pct: number | null
  alpha_pct: number | null
}

export interface BacktestResult {
  strategy: string
  mode?: 'trade' | 'horizon' | string
  config: Record<string, unknown>
  metrics: BacktestMetrics
  performance?: BacktestPerformance
  skipped: Record<string, number>
  trades?: BacktestTrade[]
}
